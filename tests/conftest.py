import time

import pytest
import requests

from utils.settings import ANTIFRAUD_URL

STARTUP_TIMEOUT_SECONDS = 60


@pytest.fixture(scope="session", autouse=True)
def servico_no_ar():
    limite = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < limite:
        try:
            if requests.get(f"{ANTIFRAUD_URL}/health_check", timeout=2).status_code == 204:
                return
        except requests.ConnectionError:
            pass
        time.sleep(1)
    raise RuntimeError(f"antifraud-service não respondeu em {STARTUP_TIMEOUT_SECONDS}s. "
                       + "Rode: docker compose up -d --build --wait")
