from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from rules.context import History, PixRequest
from rules.parameters import Parameters

IDENTITY = "IDENTITY"
TRANSACTION = "TRANSACTION"

SCORE = "SCORE"
FORCE_TWO_FACTOR = "FORCE_TWO_FACTOR"
REJECT = "REJECT"
FAILSAFE_REJECT = "FAILSAFE_REJECT"
FAILSAFE_TWO_FACTOR = "FAILSAFE_TWO_FACTOR"


@dataclass(frozen=True)
class RuleHit:
    code: str
    axis: str
    effect: str
    points: int
    reason: str
    evidence: dict = field(default_factory=dict)

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
        pass

    def hit(self, points: int, reason: str, evidence: dict = None, effect: str = SCORE) -> RuleHit:
        return RuleHit(self.code, self.axis, effect, points, reason, evidence or {})
