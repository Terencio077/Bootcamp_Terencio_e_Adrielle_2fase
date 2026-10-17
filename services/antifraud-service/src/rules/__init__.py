"""O motor antifraude: regras puras, sem banco, sem rede, sem relógio.

Esta camada é nova em relação ao base-service. Ela fica ENTRE o
controller e o repository: o controller pede o histórico ao repository,
entrega ao motor e grava a decisão. O motor só recebe dados e devolve
uma decisão — por isso ele é testável sem subir nada.
"""

from rules.context import APPROVED, REJECTED, TWO_FACTOR_REQUIRED, DestinationHistory, History, PastPix, PixRequest
from rules.engine import ALL_RULES, Decision, DecisionEngine
from rules.parameters import DEFAULT_PARAMETERS, RULES_VERSION, Parameters
