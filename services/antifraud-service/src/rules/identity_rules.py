"""Eixo IDENTIDADE — "quem é essa pessoa?"

Sinais de que quem está mandando o Pix pode não ser o dono da conta:
aparelho que ele nunca usou, um lugar onde ele não poderia estar, uma
pressa que não é dele. É a dúvida que o 2FA resolve: se é mesmo ele, ele
confirma com o rosto no aparelho e segue.
"""

from datetime import timedelta
from typing import Optional

from rules.context import APPROVED, History, PixRequest
from rules.parameters import Parameters
from rules.rule import FORCE_TWO_FACTOR, IDENTITY, REJECT, Rule, RuleHit
from rules.geo import haversine_km


class NewDevice(Rule):
    """ID01 — o pagador nunca usou este aparelho.

    Trocar de aparelho é o primeiro passo do roubo de conta: o fraudador
    entra com a senha num celular dele. Para quem já tem histórico, aparelho
    novo pesa; para o primeiro Pix que o motor vê, tudo é novo e pesa pouco.
    """

    code = "ID01"
    axis = IDENTITY
    name = "Dispositivo novo"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if any(past.device_id == pix.device_id for past in history.payer_pix):
            return None

        if not history.payer_pix:
            return self.hit(parameters.first_seen_payer_device_points,
                            "Primeiro Pix deste pagador que o motor analisa; o aparelho ainda não tem histórico.",
                            {"device_id": pix.device_id, "payer_history": 0})

        known_devices = len({past.device_id for past in history.payer_pix})
        return self.hit(parameters.new_device_points,
                        "Pix enviado de um aparelho que este pagador nunca usou.",
                        {"device_id": pix.device_id, "known_devices": known_devices,
                         "payer_history": len(history.payer_pix)})


class UntrustedDeviceLimit(Rule):
    """ID02 — regulação: aparelho não cadastrado tem teto por Pix e por dia.

    O motor não recebe o cadastro de dispositivos, então ele usa o próprio
    histórico como cadastro: um aparelho fica confiável depois de um Pix
    APROVADO a partir dele. Acima do teto, o Pix não pode seguir sem a prova
    de vida — que é exatamente o 2FA. Por isso o efeito é um piso de 2FA, e
    não pontos: não é suspeita, é regra.
    """

    code = "ID02"
    axis = IDENTITY
    name = "Limite de dispositivo não cadastrado"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        trusted = any(past.device_id == pix.device_id and past.status == APPROVED
                      for past in history.payer_pix)
        if trusted:
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

    Cliente de verdade não manda dez Pix em dez minutos; quem esvazia uma
    conta roubada, ou um robô, manda. Conta TODAS as tentativas, inclusive
    as recusadas: insistir depois de uma recusa é justamente o sinal.
    """

    code = "ID04"
    axis = IDENTITY
    name = "Rajada de Pix"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        window = timedelta(minutes=parameters.velocity_window_minutes)
        count = 1 + len(history.payer_within(pix.transaction_date, window))
        evidence = {"pix_in_window": count, "window_minutes": parameters.velocity_window_minutes}

        if count >= parameters.velocity_reject_count:
            return self.hit(0, "Volume de Pix em poucos minutos típico de conta sendo esvaziada ou de automação.",
                            evidence, effect=REJECT)

        if count >= parameters.velocity_two_factor_count:
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


IDENTITY_RULES = [NewDevice(), UntrustedDeviceLimit(), ImpossibleTravel(), Velocity(), NewChannel(), UnusualDawn()]
