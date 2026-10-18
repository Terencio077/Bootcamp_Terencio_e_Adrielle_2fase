import random
import uuid
from datetime import datetime, timedelta

import requests

from utils.settings import ANTIFRAUD_URL, HEADERS

BASE_TIME = datetime.fromisoformat("2026-09-15T14:00:00-03:00")
OLD_DATE = "2020-01-10T10:00:00-03:00"


def random_cpf() -> str:
    digits = [random.randint(0, 9) for _ in range(9)]
    for position in (9, 10):
        total = sum(digits[index] * (position + 1 - index) for index in range(position))
        remainder = total % 11
        digits.append(0 if remainder < 2 else 11 - remainder)
    text = "".join(str(digit) for digit in digits)
    return f"{text[:3]}.{text[3:6]}.{text[6:9]}-{text[9:]}"


def new_account(opening_date: str = OLD_DATE, document: str = None) -> dict:
    return {
        "participant": f"{random.randint(0, 99999999):08d}",
        "branch": f"{random.randint(1, 9999):04d}",
        "account_number": str(random.randint(10000, 99999999)),
        "opening_date": opening_date,
        "owner": {"document_number": document or random_cpf()},
    }


def new_payer() -> dict:
    return {
        "branch": "0001",
        "account_number": str(random.randint(10000, 99999)),
        "opening_date": "2023-03-02T10:00:00-03:00",
        "owner": {"document_number": random_cpf()},
        "device_id": f"dvc-{uuid.uuid4().hex[:8]}",
    }


def build_pix(payer: dict, destination: dict, amount: int, when: datetime, device_id: str = None,
              channel: str = "app", geolocation: dict = None, pix_id: str = None) -> dict:
    source = {"device_id": device_id or payer["device_id"], "channel": channel, "ip": "198.51.100.23"}
    if geolocation is not None:
        source["geolocation"] = geolocation

    return {
        "id": pix_id or f"pix-{uuid.uuid4().hex[:16]}",
        "amount": amount,
        "transaction_date": when.isoformat(),
        "source_account": {key: payer[key] for key in ("branch", "account_number", "opening_date", "owner")},
        "destination_account": destination,
        "source": source,
    }


def post_pix(payload: dict) -> requests.Response:
    return requests.post(f"{ANTIFRAUD_URL}/pix/transaction", json=payload, headers=HEADERS)


def send(payload: dict) -> dict:
    response = post_pix(payload)
    assert response.status_code == 201, response.text
    return response.json()


def get_pix(pix_id: str) -> requests.Response:
    return requests.get(f"{ANTIFRAUD_URL}/pix/transaction/{pix_id}", headers=HEADERS)


def rules_of(analysis: dict) -> set:
    return {hit["rule"] for hit in analysis["metadata"]["rules_triggered"]}


def warm_up_payer(payer: dict, days: int = 6, amount: int = 10000, start: datetime = BASE_TIME) -> dict:
    payee = new_account()
    first = send(build_pix(payer, payee, amount, start - timedelta(days=35)))
    assert first["status"] == "approved", first
    for day in range(days, 0, -1):
        analysis = send(build_pix(payer, payee, amount, start - timedelta(days=day)))
        assert analysis["status"] == "approved", analysis
    return payee
