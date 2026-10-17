"""O motor: roda todas as regras, soma os dois eixos e decide.

────────────────────────────────────────────────────────────────────
POR QUE DOIS EIXOS, E NÃO UMA NOTA SÓ
────────────────────────────────────────────────────────────────────
A apresentação da QI Tech fez duas perguntas diferentes: "quem é essa
pessoa?" e "essa transação é legítima?". E as três decisões do desafio
não respondem às duas do mesmo jeito:

• O 2FA responde à PRIMEIRA. Ele prova que é o dono da conta no aparelho.
• Ninguém responde à SEGUNDA na hora do Pix. No golpe do falso parente, o
  dono da conta passa no 2FA e paga o golpista assim mesmo.

Uma nota única misturaria as duas, e o motor pediria 2FA para um Pix que
o 2FA não protege. Com dois eixos, a decisão sabe QUAL dúvida tem:

    1. Alguma regra de bloqueio disparou (risco claro)  -> rejected
    2. Transação >= 60                                   -> rejected
       (o 2FA não resolve dúvida sobre "o quê")
    3. Identidade >= 80                                  -> rejected
       (sinais tão fortes que nem o 2FA convence)
    4. Os dois eixos >= 40                               -> rejected
       (dúvida séria sobre quem E sobre o quê: roubo de conta)
    5. Algum eixo >= 30, ou piso regulatório de 2FA      -> two_factor_required
    6. Senão                                             -> approved

Repare que o eixo da transação recusa mais cedo (60) que o da identidade
(80). Na faixa de 30 a 59 da transação o 2FA ainda é pedido, mas pelo
outro motivo: é uma pausa de confirmação que quebra o ritmo do golpe —
quem está sendo enganado ao telefone ganha um momento para pensar.

────────────────────────────────────────────────────────────────────
POR QUE PONTOS, E NÃO UMA FILA DE IFs
────────────────────────────────────────────────────────────────────
Com ifs, cada sinal fraco decide sozinho: "destino com menos de 7 dias"
bloquearia todo mundo que paga um prestador novo. Com pontos, sinal fraco
só pesa somado a outros, e cada ponto continua explicável: o metadata
lista cada regra que disparou, quanto ela somou e o que ela viu.

Nenhuma regra de hoje bloqueia sozinha. Os sinais que pareciam "risco
claro" (dez Pix em dez minutos, dez pagadores numa hora) também aparecem
em gente legítima: o churrasco dividido entre amigos, a lanchonete na hora
do almoço. A recusa sai da COMBINAÇÃO de sinais. O efeito REJECT continua
existindo no motor para a política de falha logo abaixo.

Os limites regulatórios (ID02, TX07) são outra coisa: são pisos de 2FA
(efeito FORCE_TWO_FACTOR) e nenhum desconto de confiança os derruba.

────────────────────────────────────────────────────────────────────
SE UMA REGRA QUEBRAR
────────────────────────────────────────────────────────────────────
Uma exceção numa regra não derruba a análise, e o tratamento depende do
eixo da regra que falhou — coerente com a tese do motor:

• regra de IDENTIDADE: piso de 2FA. A dúvida que ficou é sobre quem
  paga, e é exatamente o que o 2FA resolve;
• regra de TRANSAÇÃO: o 2FA não resolveria a dúvida que ficou. Recusa a
  partir de R$ 1.000 (dano potencial alto) e pede 2FA abaixo disso, para
  não travar todo Pix pequeno por um defeito nosso.

O erro fica gravado nos motivos, com o tipo da exceção, para alguém
consertar.
"""

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
