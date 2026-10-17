"""Eixo TRANSAÇÃO — "a transação é legítima?"

Mesmo que seja o dono da conta pagando, o Pix pode ser golpe: o falso
funcionário do banco, o falso parente, o sequestro relâmpago. Nesses
casos a pessoa é quem diz ser e passa no 2FA — o problema é PARA ONDE e
QUANTO. Por isso este eixo recusa mais cedo (ver rules/parameters.py).
"""

from datetime import datetime, timedelta
from typing import Optional

from rules.context import APPROVED, History, PixRequest
from rules.parameters import Parameters
from rules.rule import REJECT, TRANSACTION, Rule, RuleHit


class YoungDestination(Rule):
    """TX01 — a conta que recebe acabou de ser aberta.

    Conta laranja tem vida curta: é aberta, recebe o dinheiro do golpe e é
    abandonada. O payload traz a data de abertura do destino, e é o sinal
    mais barato que existe: não custa consulta nenhuma.
    """

    code = "TX01"
    axis = TRANSACTION
    name = "Conta de destino recém-aberta"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        age_days = (pix.transaction_date - pix.destination_opening_date).total_seconds() / 86400
        evidence = {"destination_age_days": round(age_days, 1)}

        if age_days <= parameters.young_destination_days:
            return self.hit(parameters.young_destination_points,
                            f"A conta de destino foi aberta há no máximo {parameters.young_destination_days} dias.",
                            evidence)
        if age_days <= parameters.recent_destination_days:
            return self.hit(parameters.recent_destination_points,
                            f"A conta de destino foi aberta há menos de {parameters.recent_destination_days} dias.",
                            evidence)
        return None


class MuleAccount(Rule):
    """TX02 — muitos pagadores diferentes mandando para a mesma conta em pouco tempo.

    É o desenho da conta laranja vista do lado de quem recebe: dezenas de
    vítimas pagando o mesmo "boleto falso" ou o mesmo "produto" que não
    existe. Nenhuma das vítimas parece estranha sozinha; o destino parece.
    """

    code = "TX02"
    axis = TRANSACTION
    name = "Conta laranja"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        payers = 1 + history.destination.distinct_other_payers_in_window
        evidence = {"distinct_payers": payers, "window_minutes": parameters.mule_window_minutes}

        if payers >= parameters.mule_reject_payers:
            return self.hit(0, "A conta de destino recebeu de muitos pagadores diferentes em pouco tempo.",
                            evidence, effect=REJECT)
        if payers >= parameters.mule_score_payers:
            return self.hit(parameters.mule_points,
                            "A conta de destino está recebendo de vários pagadores diferentes em pouco tempo.",
                            evidence)
        return None


class RejectedDestination(Rule):
    """TX03 — esta conta de destino já teve Pix recusados recentemente.

    O motor aprende com as próprias decisões: um destino que já foi barrado
    por outras regras continua suspeito para os próximos pagadores.
    """

    code = "TX03"
    axis = TRANSACTION
    name = "Destino com recusas recentes"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        rejected = history.destination.rejected_in_window
        if rejected == 0:
            return None
        evidence = {"rejected_pix": rejected, "window_days": parameters.rejected_destination_days}
        if rejected >= parameters.rejected_destination_many:
            return self.hit(parameters.rejected_destination_many_points,
                            "A conta de destino teve vários Pix recusados recentemente.", evidence)
        return self.hit(parameters.rejected_destination_points,
                        "A conta de destino teve Pix recusado recentemente.", evidence)


class OutOfProfileAmount(Rule):
    """TX04 — valor muito acima do que este pagador costuma mandar.

    Compara com o MAIOR Pix aprovado do pagador, e não com a média: a média
    pune quem paga o aluguel uma vez por mês e faz pequenos Pix o resto do
    tempo. "Maior que o dobro do maior Pix que você já fez" é fácil de
    explicar ao cliente e difícil de acontecer por acaso.
    """

    code = "TX04"
    axis = TRANSACTION
    name = "Valor fora do perfil"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        approved = [past.amount_cents for past in history.payer_pix if past.status == APPROVED]

        if len(approved) < parameters.profile_min_history:
            if pix.amount_cents > parameters.no_profile_high_amount_cents:
                return self.hit(parameters.no_profile_high_amount_points,
                                "Valor alto para um pagador ainda sem perfil formado.",
                                {"amount_cents": pix.amount_cents, "approved_history": len(approved)})
            return None

        largest = max(approved)
        ratio = pix.amount_cents / largest
        evidence = {"amount_cents": pix.amount_cents, "largest_approved_cents": largest, "ratio": round(ratio, 2)}

        if ratio > parameters.profile_extreme_factor:
            return self.hit(parameters.profile_extreme_points,
                            "Valor muito acima do maior Pix que este pagador já fez.", evidence)
        if ratio > parameters.profile_high_factor:
            return self.hit(parameters.profile_high_points,
                            "Valor acima do dobro do maior Pix que este pagador já fez.", evidence)
        return None


class UnusualDailySum(Rule):
    """TX05 — a soma do dia passou muito do que o pagador movimenta por dia.

    Pega o que o TX04 não vê: vários Pix médios que, somados, esvaziam a
    conta. Compara as últimas 24 h com a média diária dos 29 dias antes
    delas, e só para quem tem pelo menos uma semana de histórico.
    """

    code = "TX05"
    axis = TRANSACTION
    name = "Soma do dia fora do padrão"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if not history.payer_pix:
            return None
        oldest = history.payer_pix[-1].transaction_date
        if pix.transaction_date - oldest < timedelta(days=parameters.daily_sum_min_history_days):
            return None

        now = pix.transaction_date
        day_start = now - timedelta(hours=24)
        baseline_start = now - timedelta(days=30)

        day_total = pix.amount_cents
        baseline_total = 0
        for past in history.payer_pix:
            if not past.money_may_have_left:
                continue
            if past.transaction_date >= day_start:
                day_total += past.amount_cents
            elif past.transaction_date >= baseline_start:
                baseline_total += past.amount_cents

        daily_average = baseline_total / 29
        threshold = max(parameters.daily_sum_factor * daily_average, parameters.daily_sum_floor_cents)
        if day_total <= threshold:
            return None

        return self.hit(parameters.daily_sum_points,
                        "O total enviado nas últimas 24 horas está muito acima da média diária deste pagador.",
                        {"day_total_cents": day_total, "daily_average_cents": round(daily_average),
                         "threshold_cents": round(threshold)})


class Structuring(Rule):
    """TX06 — vários Pix logo abaixo de um limite conhecido.

    Quem conhece o teto (R$ 200 do aparelho novo, R$ 1.000 da noite) quebra
    o valor em pedaços de R$ 199. Cada pedaço passa nas regras de limite; a
    repetição dentro da faixa é que denuncia.
    """

    code = "TX06"
    axis = TRANSACTION
    name = "Fracionamento"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        limits = [parameters.untrusted_device_max_per_pix_cents, parameters.night_limit_cents]

        def band_of(amount: int):
            for limit in limits:
                if parameters.structuring_band_ratio * limit <= amount <= limit:
                    return limit
            return None

        limit = band_of(pix.amount_cents)
        if limit is None:
            return None

        window = timedelta(minutes=parameters.structuring_window_minutes)
        in_band = 1 + sum(1 for past in history.payer_within(pix.transaction_date, window)
                          if past.money_may_have_left and band_of(past.amount_cents) == limit)
        if in_band < parameters.structuring_min_count:
            return None

        return self.hit(parameters.structuring_points,
                        "Vários Pix seguidos com valor logo abaixo de um limite.",
                        {"pix_in_band": in_band, "limit_cents": limit,
                         "window_minutes": parameters.structuring_window_minutes})


class NightLimit(Rule):
    """TX07 — regulação: Pix de pessoa física entre 20h e 6h tem teto (R$ 1.000 por padrão).

    O limite noturno existe por causa do sequestro relâmpago: a vítima está
    com o celular, desbloqueia com o próprio rosto e passaria no 2FA. Por
    isso ele mora no eixo da TRANSAÇÃO, e não no da identidade. Soma o que
    já saiu na mesma noite, para não ser driblado com vários Pix menores.
    """

    code = "TX07"
    axis = TRANSACTION
    name = "Limite noturno"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if not pix.payer_is_person:
            return None

        night_start = night_window_start(pix.transaction_date, parameters)
        if night_start is None:
            return None

        night_total = pix.amount_cents + sum(past.amount_cents for past in history.payer_since(night_start)
                                             if past.money_may_have_left)
        if night_total <= parameters.night_limit_cents:
            return None

        return self.hit(parameters.night_points,
                        "Pix noturno de pessoa física acima do limite noturno padrão.",
                        {"night_total_cents": night_total, "night_limit_cents": parameters.night_limit_cents,
                         "local_hour": pix.local_hour})


class FirstPaymentToPayee(Rule):
    """TX08 — primeira vez que este pagador manda dinheiro para este recebedor, com valor relevante.

    Sozinho é o dia a dia (todo mundo paga alguém pela primeira vez um dia)
    e por isso vale pouco. Ele existe para somar: destino novo + valor alto
    + primeira vez é o retrato do golpe.

    Para um pagador que o motor nunca viu, todo recebedor é "o primeiro" —
    a regra não diria nada sobre ele, só sobre o nosso cold start. Por isso
    ela só roda para quem já tem histórico (mesmo critério do ID01).
    """

    code = "TX08"
    axis = TRANSACTION
    name = "Primeiro Pix para este recebedor"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if not history.payer_pix:
            return None
        if pix.amount_cents < parameters.first_payment_amount_cents:
            return None
        if pix.source_document == pix.destination_document:
            return None
        if any(past.destination_document == pix.destination_document for past in history.payer_pix):
            return None
        return self.hit(parameters.first_payment_points,
                        "Primeiro Pix deste pagador para este recebedor, com valor relevante.",
                        {"amount_cents": pix.amount_cents})


def night_window_start(moment: datetime, parameters: Parameters) -> Optional[datetime]:
    """Início da noite em que o Pix caiu (20h do dia ou da véspera), ou None se for dia.

    Usa a hora local do próprio Pix (o fuso que veio na transaction_date):
    o limite noturno é sobre o relógio de quem paga.
    """
    hour = moment.hour
    if hour >= parameters.night_start_hour:
        return moment.replace(hour=parameters.night_start_hour, minute=0, second=0, microsecond=0)
    if hour < parameters.night_end_hour:
        previous_day = moment - timedelta(days=1)
        return previous_day.replace(hour=parameters.night_start_hour, minute=0, second=0, microsecond=0)
    return None


TRANSACTION_RULES = [YoungDestination(), MuleAccount(), RejectedDestination(), OutOfProfileAmount(),
                     UnusualDailySum(), Structuring(), NightLimit(), FirstPaymentToPayee()]
