from dataclasses import dataclass, field
from typing import List

from rules.context import APPROVED, REJECTED, TWO_FACTOR_REQUIRED, History, PixRequest
from rules.identity_rules import IDENTITY_RULES
from rules.parameters import DEFAULT_PARAMETERS, RULES_VERSION, Parameters
from rules.rule import (
    FAILSAFE_REJECT,
    FAILSAFE_TWO_FACTOR,
    FORCE_TWO_FACTOR,
    IDENTITY,
    REJECT,
    TRANSACTION,
    RuleHit,
)
from rules.transaction_rules import TRANSACTION_RULES
from rules.trust_rules import TRUST_RULES

ALL_RULES = IDENTITY_RULES + TRANSACTION_RULES + TRUST_RULES


@dataclass(frozen=True)
class Decision:
    status: str
    identity_score: int
    transaction_score: int
    reason: str
    hits: List[RuleHit] = field(default_factory=list)
    rules_version: str = RULES_VERSION


class DecisionEngine:
    def __init__(self, rules: list = None, parameters: Parameters = DEFAULT_PARAMETERS) -> None:
        self.rules = rules if rules is not None else ALL_RULES
        self.parameters = parameters

    def evaluate(self, pix: PixRequest, history: History) -> Decision:
        hits = []
        for rule in self.rules:
            try:
                hit = rule.evaluate(pix, history, self.parameters)
            except Exception as error:
                hit = self.failure_hit(rule, pix, error)
            if hit is not None:
                hits.append(hit)

        identity_score = max(0, sum(hit.points for hit in hits if hit.axis == IDENTITY))
        transaction_score = max(0, sum(hit.points for hit in hits if hit.axis == TRANSACTION))
        status, reason = self.decide(hits, identity_score, transaction_score)

        return Decision(status, identity_score, transaction_score, reason, hits)

    def failure_hit(self, rule, pix: PixRequest, error: Exception) -> RuleHit:
        evidence = {"error": type(error).__name__}
        if rule.axis == TRANSACTION and pix.amount_cents >= self.parameters.rule_error_reject_amount_cents:
            return RuleHit(rule.code, rule.axis, FAILSAFE_REJECT, 0,
                           "Falha ao avaliar uma regra da transação em Pix de valor alto; por segurança, recusado.",
                           evidence)
        return RuleHit(rule.code, rule.axis, FAILSAFE_TWO_FACTOR, 0,
                       "Falha ao avaliar uma regra; por segurança, o cliente confirma antes de seguir.", evidence)

    def decide(self, hits: list, identity_score: int, transaction_score: int) -> tuple:
        p = self.parameters

        blocking = [hit.code for hit in hits if hit.effect == REJECT]
        if blocking:
            return REJECTED, f"Regra de bloqueio disparou: {', '.join(blocking)}."

        failed = [hit.code for hit in hits if hit.effect == FAILSAFE_REJECT]
        if failed:
            return REJECTED, f"Falha técnica em regra da transação, Pix de valor alto: {', '.join(failed)}."

        if transaction_score >= p.transaction_reject_threshold:
            return REJECTED, ("Risco alto na transação. O 2FA confirmaria quem paga, "
                              "mas não torna a transação legítima.")

        if identity_score >= p.identity_reject_threshold:
            return REJECTED, "Sinais fortes de que quem está pagando não é o titular da conta."

        if identity_score >= p.both_axes_reject_threshold and transaction_score >= p.both_axes_reject_threshold:
            return REJECTED, "Dúvida sobre quem está pagando e sobre a transação ao mesmo tempo."

        forced = [hit.code for hit in hits if hit.effect in (FORCE_TWO_FACTOR, FAILSAFE_TWO_FACTOR)]
        doubts = []
        if identity_score >= p.two_factor_threshold:
            doubts.append("identidade")
        if transaction_score >= p.two_factor_threshold:
            doubts.append("transação")

        if doubts or forced:
            parts = []
            if doubts:
                parts.append(f"dúvida sobre {' e '.join(doubts)}")
            if forced:
                parts.append(f"confirmação obrigatória ({', '.join(forced)})")
            return TWO_FACTOR_REQUIRED, "Pedir 2FA: " + "; ".join(parts) + "."

        return APPROVED, "Nenhum sinal de risco relevante."
