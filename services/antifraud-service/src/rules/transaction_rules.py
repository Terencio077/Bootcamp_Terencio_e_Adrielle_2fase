from datetime import datetime, timedelta
from typing import Optional

from rules.context import APPROVED, History, PixRequest
from rules.parameters import Parameters
from rules.rule import FORCE_TWO_FACTOR, TRANSACTION, Rule, RuleHit


class YoungDestination(Rule):

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


class PayerConcentration(Rule):

    code = "TX02"
    axis = TRANSACTION
    name = "Concentração de pagadores acima do padrão da conta"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        payers = 1 + history.destination.distinct_other_payers_in_window
        peak = history.destination.peak_payers_30d
        usual = int(peak * parameters.concentration_own_peak_factor)
        excess = payers - usual
        is_person = len(pix.destination_document) == 11
        evidence = {"distinct_payers": payers, "window_minutes": parameters.concentration_window_minutes,
                    "own_peak_30d": peak, "excess_over_usual": max(excess, 0),
                    "destination_type": "cpf" if is_person else "cnpj"}

        if is_person:
            tiers = [(parameters.concentration_person_high_payers, parameters.concentration_person_high_points),
                     (parameters.concentration_person_payers, parameters.concentration_person_points)]
        else:
            tiers = [(parameters.concentration_company_high_payers, parameters.concentration_company_high_points),
                     (parameters.concentration_company_payers, parameters.concentration_company_points)]

        for minimum, points in tiers:
            if excess >= minimum:
                return self.hit(points, "Muito mais pagadores diferentes tentando pagar esta conta do que ela "
                                        "costuma receber.", evidence)
        return None


class RejectedDestination(Rule):

    code = "TX03"
    axis = TRANSACTION
    name = "Destino com recusas recentes"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        payers = history.destination.rejected_payers_in_window
        if payers < parameters.rejected_destination_min_payers:
            return None
        return self.hit(parameters.rejected_destination_points,
                        "Pix de outros pagadores para esta conta foram recusados recentemente por risco da transação.",
                        {"rejected_payers": payers, "window_days": parameters.rejected_destination_days})


class OutOfProfileAmount(Rule):

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

    code = "TX05"
    axis = TRANSACTION
    name = "Soma do dia fora do padrão"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if not history.payer_pix:
            return None
        oldest = history.payer_first_seen or history.payer_pix[-1].transaction_date
        if pix.transaction_date - oldest < timedelta(days=parameters.daily_sum_min_history_days):
            return None

        now = pix.transaction_date
        day_start = now - timedelta(hours=24)
        baseline_start = now - timedelta(days=30)

        previous_today = 0
        baseline_total = 0
        for past in history.payer_pix:
            if not past.money_may_have_left:
                continue
            if past.transaction_date >= day_start:
                previous_today += past.amount_cents
            elif past.transaction_date >= baseline_start:
                baseline_total += past.amount_cents
        if history.payer_baseline_30d_cents is not None:
            baseline_total = history.payer_baseline_30d_cents
        day_total = previous_today + pix.amount_cents

        daily_average = baseline_total / 29
        threshold = max(parameters.daily_sum_factor * daily_average, parameters.daily_sum_floor_cents)
        if day_total <= threshold:
            return None
        explained_by_current_only = previous_today <= threshold and pix.amount_cents >= threshold
        if explained_by_current_only:
            return None

        return self.hit(parameters.daily_sum_points,
                        "O total enviado nas últimas 24 horas está muito acima da média diária deste pagador.",
                        {"day_total_cents": day_total, "daily_average_cents": round(daily_average),
                         "threshold_cents": round(threshold)})


class Structuring(Rule):

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
                        "Pix noturno de pessoa física acima do limite noturno padrão: confirmação obrigatória.",
                        {"night_total_cents": night_total, "night_limit_cents": parameters.night_limit_cents,
                         "local_hour": pix.local_hour, "assumed_default_limit": True},
                        effect=FORCE_TWO_FACTOR)


class FirstPaymentToPayee(Rule):

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
        if any(past.destination_document == pix.destination_document and past.status == APPROVED
               for past in history.payer_pix):
            return None
        return self.hit(parameters.first_payment_points,
                        "Primeiro Pix deste pagador para este recebedor, com valor relevante.",
                        {"amount_cents": pix.amount_cents})


def night_window_start(moment: datetime, parameters: Parameters) -> Optional[datetime]:
    hour = moment.hour
    if hour >= parameters.night_start_hour:
        return moment.replace(hour=parameters.night_start_hour, minute=0, second=0, microsecond=0)
    if hour < parameters.night_end_hour:
        previous_day = moment - timedelta(days=1)
        return previous_day.replace(hour=parameters.night_start_hour, minute=0, second=0, microsecond=0)
    return None


class PayerQueueOverflow(Rule):

    code = "TX09"
    axis = TRANSACTION
    name = "Pix simultâneos demais do mesmo pagador"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if not history.payer_lock_timed_out:
            return None
        return RuleHit(self.code, self.axis, FORCE_TWO_FACTOR, 0,
                       "Muitos Pix simultâneos do mesmo pagador; o cliente confirma antes de seguir.",
                       {"queue_wait_limit_ms": parameters.payer_lock_timeout_ms})


TRANSACTION_RULES = [YoungDestination(), PayerConcentration(), RejectedDestination(), OutOfProfileAmount(),
                     UnusualDailySum(), Structuring(), NightLimit(), FirstPaymentToPayee(),
                     PayerQueueOverflow()]
