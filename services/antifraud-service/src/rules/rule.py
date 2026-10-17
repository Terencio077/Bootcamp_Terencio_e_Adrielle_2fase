"""O formato comum de toda regra, e do que ela devolve quando dispara.

Uma regra é uma classe pequena com uma pergunta só. Ela devolve um
`RuleHit` quando o sinal aparece, ou `None` quando não tem nada a dizer.
O motor (rules/engine.py) não conhece regra nenhuma pelo nome: ele recebe
a lista e soma. Regra nova é uma classe nova na lista; o motor não muda.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from rules.context import History, PixRequest
from rules.parameters import Parameters

# Os dois eixos de risco, nas palavras da apresentação da QI Tech.
IDENTITY = "IDENTITY"         # "Quem é essa pessoa?"
TRANSACTION = "TRANSACTION"   # "A transação é legítima?"

# O que o disparo faz com a decisão.
SCORE = "SCORE"                       # soma pontos no eixo (podem ser negativos: confiança)
FORCE_TWO_FACTOR = "FORCE_TWO_FACTOR"  # piso de 2FA: abaixo disso não aprova (regulatório)
REJECT = "REJECT"                     # risco claro: recusa sozinha


@dataclass(frozen=True)
class RuleHit:
    code: str
    axis: str
    effect: str
    points: int
    reason: str                       # frase para o atendimento ler ao cliente
    evidence: dict = field(default_factory=dict)   # os números que a regra viu

    def to_dict(self) -> dict:
        return {
            "rule": self.code,
            "axis": self.axis,
            "effect": self.effect,
            "points": self.points,
            "reason": self.reason,
            "evidence": self.evidence,
        }


class Rule(ABC):
    code: str = ""
    axis: str = ""
    name: str = ""

    @abstractmethod
    def evaluate(self, pix: PixRequest, history: History, parameters: Parameters) -> Optional[RuleHit]:
        """Olha o Pix e o passado; devolve o disparo ou None."""

    def hit(self, points: int, reason: str, evidence: dict = None, effect: str = SCORE) -> RuleHit:
        return RuleHit(self.code, self.axis, effect, points, reason, evidence or {})
