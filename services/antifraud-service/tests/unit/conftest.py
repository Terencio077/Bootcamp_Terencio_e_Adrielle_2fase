"""Testes unitários do motor: rodam sem banco, sem rede e sem Docker.

O motor (src/rules/) é Python puro, então estes testes importam direto
de lá. É a diferença em relação aos testes de integração em tests/, que
falam só HTTP com o serviço no ar.

    pytest services/antifraud-service/tests
"""

import os
import sys

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
