from typing import Optional

from rules.context import APPROVED, History, PixRequest, business_date
from rules.parameters import Parameters
from rules.rule import TRANSACTION, Rule, RuleHit


class RecurringPayee(Rule):

    code = "TR01"
    axis = TRANSACTION
    name = "Recebedor recorrente"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        to_payee = [past for past in history.payer_pix
                    if past.destination_document == pix.destination_document and past.status == APPROVED]
        days = {business_date(past.transaction_date) for past in to_payee}
        if len(days) < parameters.recurring_payee_min_count:
            return None

        first = min(past.transaction_date for past in to_payee)
        age_days = (pix.transaction_date - first).total_seconds() / 86400
        if age_days < parameters.recurring_payee_min_age_days:
            return None

        largest = max(past.amount_cents for past in to_payee)
        ratio = pix.amount_cents / largest
        evidence = {"approved_days_to_payee": len(days), "largest_to_payee_cents": largest,
                    "ratio": round(ratio, 2), "max_ratio": parameters.recurring_payee_max_ratio}

        if ratio > parameters.recurring_payee_max_ratio:
            return self.hit(0, "Recebedor recorrente, mas o valor é muito maior que os pagamentos anteriores a "
                               "ele: a recorrência não avaliza este Pix.", evidence)

        return self.hit(parameters.recurring_payee_points,
                        "Recebedor pago por este pagador em vários dias diferentes.", evidence)


class OwnAccount(Rule):

    code = "TR02"
    axis = TRANSACTION
    name = "Mesma titularidade"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if pix.source_document != pix.destination_document:
            return None
        return self.hit(parameters.own_account_points, "Transferência entre contas do mesmo titular.", {})


TRUST_RULES = [RecurringPayee(), OwnAccount()]
