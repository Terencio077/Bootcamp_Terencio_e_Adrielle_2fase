"""Eixo IDENTIDADE — "quem é essa pessoa?"

Sinais de que quem está mandando o Pix pode não ser o dono da conta:
aparelho que ele nunca usou, um lugar onde ele não poderia estar, uma
pressa que não é dele. É a dúvida que o 2FA resolve: se é mesmo ele, ele
confirma com o rosto no aparelho e segue.
"""

from datetime import timedelta
from typing import Optional

from rules.context import History, PixRequest
from rules.device import RECURRING, TRUSTED, device_trust, payer_has_trusted_device
from rules.parameters import Parameters
from rules.rule import FORCE_TWO_FACTOR, IDENTITY, Rule, RuleHit
from rules.geo import haversine_km


class UntrustedDevice(Rule):
    """ID01 — o Pix sai de um aparelho que ainda não é confiável para este pagador.

    Trocar de aparelho é o primeiro passo do roubo de conta: o fraudador
    entra com a senha num celular dele. O que conta não é "já vimos este
    aparelho" (uma tentativa que pediu 2FA não prova nada), e sim "este
    aparelho já teve um Pix aprovado há pelo menos 24 h" (rules/device.py).

    Quanto pesa depende do contexto:
    • pagador que já tem outro aparelho confiável: é troca de aparelho, +30;
    • aparelho em uso recorrente (vários dias, uma semana, sem recusa):
      +15. Reduz a suspeita, mas não confirma nada;
    • pagador sem nenhum aparelho confiável ainda: tudo é novo para o
      motor (cold start), +10.
    """

    code = "ID01"
    axis = IDENTITY
    name = "Dispositivo não confiável"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        trust = device_trust(pix.device_id, pix.transaction_date, history, parameters)
        if trust == TRUSTED:
            return None

        evidence = {"device_id": pix.device_id, "device_state": trust.lower(),
                    "payer_history": len(history.payer_pix)}

        if not payer_has_trusted_device(pix.transaction_date, history, parameters):
            return self.hit(parameters.first_seen_payer_device_points,
                            "Pagador ainda sem aparelho confirmado no histórico do motor.", evidence)

        if trust == RECURRING:
            return self.hit(parameters.recurring_device_points,
                            "Aparelho em uso há alguns dias, mas ainda sem Pix aprovado que o confirme.",
                            evidence)

        return self.hit(parameters.new_device_points,
                        "Pix enviado de um aparelho diferente do aparelho confirmado deste pagador.", evidence)


class UntrustedDeviceLimit(Rule):
    """ID02 — regulação: aparelho não cadastrado tem teto por Pix e por dia.

    HIPÓTESE: o contrato não informa o cadastro de dispositivos. O motor usa
    o próprio histórico como cadastro, com o mesmo critério da ID01: só um
    aparelho CONFIÁVEL (Pix aprovado há 24 h ou mais) escapa do teto. Acima
    do teto, o Pix precisa da prova de vida — que é o 2FA. É limite, não
    suspeita: por isso é piso de 2FA, que a confiança não derruba.
    """

    code = "ID02"
    axis = IDENTITY
    name = "Limite de dispositivo não cadastrado"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if device_trust(pix.device_id, pix.transaction_date, history, parameters) == TRUSTED:
            return None

        day = history.payer_within(pix.transaction_date, timedelta(hours=24))
        day_total = pix.amount_cents + sum(past.amount_cents for past in day
                                           if past.device_id == pix.device_id and past.money_may_have_left)

        over_per_pix = pix.amount_cents > parameters.untrusted_device_max_per_pix_cents
        over_per_day = day_total > parameters.untrusted_device_max_per_day_cents
        if not (over_per_pix or over_per_day):
            return None

        return self.hit(0,
                        "Aparelho ainda não confirmado para este pagador, acima do teto de dispositivo não "
                        "cadastrado: o cliente confirma a identidade antes de seguir.",
                        {"device_id": pix.device_id, "amount_cents": pix.amount_cents,
                         "device_24h_total_cents": day_total,
                         "max_per_pix_cents": parameters.untrusted_device_max_per_pix_cents,
                         "max_per_day_cents": parameters.untrusted_device_max_per_day_cents},
                        effect=FORCE_TWO_FACTOR)


class ImpossibleTravel(Rule):
    """ID03 — entre o último Pix e este, a pessoa teria viajado rápido demais.

    Mesmo pagador em São Paulo e, meia hora depois, em Manaus: ou são duas
    pessoas, ou alguém está mentindo a localização. Só roda quando os dois
    Pix trazem geolocalização (o campo é opcional no contrato).
    """

    code = "ID03"
    axis = IDENTITY
    name = "Viagem impossível"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if pix.latitude is None or pix.longitude is None:
            return None

        last = next((past for past in history.payer_pix if past.latitude is not None), None)
        if last is None:
            return None

        distance_km = haversine_km(last.latitude, last.longitude, pix.latitude, pix.longitude)
        if distance_km < parameters.impossible_travel_min_distance_km:
            return None

        hours = (pix.transaction_date - last.transaction_date).total_seconds() / 3600
        speed_kmh = distance_km / hours if hours > 0 else float("inf")
        if speed_kmh <= parameters.impossible_travel_speed_kmh:
            return None

        return self.hit(parameters.impossible_travel_points,
                        "A distância até o Pix anterior deste pagador não poderia ser percorrida no tempo entre eles.",
                        {"distance_km": round(distance_km, 1), "minutes_since_last": round(hours * 60, 1),
                         "speed_kmh": None if speed_kmh == float("inf") else round(speed_kmh)})


class Velocity(Rule):
    """ID04 — rajada: muitos Pix do mesmo pagador em poucos minutos.

    Conta TODAS as tentativas, inclusive as recusadas: insistir depois de
    uma recusa é justamente o sinal. Não bloqueia sozinha: dividir a conta
    do churrasco com dez amigos em dez minutos é legítimo. O 2FA é a
    resposta certa aqui, porque também barra automação; a recusa só vem
    somada a outro sinal (ex.: aparelho não confiável).
    """

    code = "ID04"
    axis = IDENTITY
    name = "Rajada de Pix"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        window = timedelta(minutes=parameters.velocity_window_minutes)
        count = 1 + len(history.payer_within(pix.transaction_date, window))
        evidence = {"pix_in_window": count, "window_minutes": parameters.velocity_window_minutes}

        if count >= parameters.velocity_high_count:
            return self.hit(parameters.velocity_high_points, "Volume muito alto de Pix deste pagador em poucos minutos.",
                            evidence)
        if count >= parameters.velocity_count:
            return self.hit(parameters.velocity_points, "Muitos Pix deste pagador em poucos minutos.", evidence)
        return None


class NewChannel(Rule):
    """ID05 — canal que o pagador nunca usou (ex.: sempre app, agora internet banking).

    Sinal fraco sozinho, e por isso vale pouco; pesa quando soma com outros.
    No internet banking o banco não consegue amarrar o aparelho, que é
    justamente onde o fraudador prefere operar.
    """

    code = "ID05"
    axis = IDENTITY
    name = "Canal novo"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if len(history.payer_pix) < parameters.new_channel_min_history:
            return None
        known = {past.channel for past in history.payer_pix}
        if pix.channel in known:
            return None
        return self.hit(parameters.new_channel_points, "Pix por um canal que este pagador nunca usou.",
                        {"channel": pix.channel, "known_channels": sorted(known)})


class UnusualDawn(Rule):
    """ID06 — Pix de madrugada para quem nunca faz Pix de madrugada.

    O "está no padrão do cliente?" da apresentação, olhando o horário.
    Só vale para quem tem histórico suficiente para ter um hábito.
    """

    code = "ID06"
    axis = IDENTITY
    name = "Madrugada fora do hábito"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        def at_dawn(hour: int) -> bool:
            return parameters.dawn_start_hour <= hour <= parameters.dawn_end_hour

        if not at_dawn(pix.local_hour) or len(history.payer_pix) < parameters.dawn_min_history:
            return None
        if any(at_dawn(past.local_hour) for past in history.payer_pix):
            return None
        return self.hit(parameters.dawn_points, "Pix de madrugada de um pagador que não tem esse hábito.",
                        {"local_hour": pix.local_hour, "payer_history": len(history.payer_pix)})


IDENTITY_RULES = [UntrustedDevice(), UntrustedDeviceLimit(), ImpossibleTravel(), Velocity(), NewChannel(), UnusualDawn()]
