"""Regras de CONFIANÇA — descontam pontos do eixo da transação.

Sem elas, o motor só sabe desconfiar, e quem paga o aluguel todo mês
para o mesmo dono do apartamento esbarraria nas mesmas regras que um
golpista. A fricção é prejuízo também: estas regras são o "não travar
quem só quer pagar o aluguel" do enunciado.

Elas NÃO descontam do eixo da identidade. Pagar sempre a mesma pessoa
não prova que é o dono da conta quem está pagando: um ladrão com o
celular desbloqueado também consegue pagar o aluguel de alguém.
"""

from typing import Optional

from rules.context import APPROVED, History, PixRequest
from rules.parameters import Parameters
from rules.rule import TRANSACTION, Rule, RuleHit


class RecurringPayee(Rule):
    """TR01 — o pagador já mandou Pix aprovado para este recebedor várias vezes."""

    code = "TR01"
    axis = TRANSACTION
    name = "Recebedor recorrente"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        count = sum(1 for past in history.payer_pix
                    if past.destination_document == pix.destination_document and past.status == APPROVED)
        if count < parameters.recurring_payee_min_count:
            return None
        return self.hit(parameters.recurring_payee_points,
                        "Recebedor recorrente deste pagador.", {"approved_to_payee": count})


class OwnAccount(Rule):
    """TR02 — o pagador está mandando para ele mesmo (mesmo CPF/CNPJ em outra conta)."""

    code = "TR02"
    axis = TRANSACTION
    name = "Mesma titularidade"

    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        if pix.source_document != pix.destination_document:
            return None
        return self.hit(parameters.own_account_points, "Transferência entre contas do mesmo titular.", {})


TRUST_RULES = [RecurringPayee(), OwnAccount()]
