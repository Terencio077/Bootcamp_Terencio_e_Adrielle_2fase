import os
import random
import uuid
from datetime import datetime, timedelta

import requests

URL = os.environ.get("ANTIFRAUD_URL", "http://localhost:8005")
HEADERS = {"INTERNAL-TOKEN": os.environ.get("INTERNAL_TOKEN", "default_token")}
NOW = datetime.fromisoformat("2026-10-17T14:00:00-03:00")
OLD = "2020-01-10T10:00:00-03:00"

STATUS_LABEL = {"approved": "APROVADO", "two_factor_required": "PEDE 2FA", "rejected": "RECUSADO"}


def cpf() -> str:
    digits = [random.randint(0, 9) for _ in range(9)]
    for position in (9, 10):
        remainder = sum(digits[i] * (position + 1 - i) for i in range(position)) % 11
        digits.append(0 if remainder < 2 else 11 - remainder)
    text = "".join(map(str, digits))
    return f"{text[:3]}.{text[3:6]}.{text[6:9]}-{text[9:]}"


def account(opened: str = OLD, document: str = None) -> dict:
    return {"participant": f"{random.randint(0, 99999999):08d}", "branch": "0001",
            "account_number": str(random.randint(10000, 99999999)), "opening_date": opened,
            "owner": {"document_number": document or cpf()}}


def payer() -> dict:
    return {"branch": "0001", "account_number": str(random.randint(10000, 99999)),
            "opening_date": "2023-03-02T10:00:00-03:00", "owner": {"document_number": cpf()},
            "device": f"dvc-{uuid.uuid4().hex[:8]}"}


def pix(who: dict, to: dict, amount: int, when: datetime, device: str = None, geo: dict = None) -> dict:
    source = {"device_id": device or who["device"], "channel": "app", "ip": "198.51.100.23"}
    if geo:
        source["geolocation"] = geo
    body = {"id": f"pix-{uuid.uuid4().hex[:12]}", "amount": amount, "transaction_date": when.isoformat(),
            "source_account": {k: who[k] for k in ("branch", "account_number", "opening_date", "owner")},
            "destination_account": to, "source": source}
    response = requests.post(f"{URL}/pix/transaction", json=body, headers=HEADERS)
    response.raise_for_status()
    return response.json()


def daily_life(who: dict, days: int = 6, amount: int = 8000, until: datetime = NOW) -> dict:
    market = account()
    pix(who, market, 8000, until - timedelta(days=days + 1))
    for day in range(days, 0, -1):
        pix(who, market, amount, until - timedelta(days=day))
    return market


def show(title: str, story: str, analysis: dict) -> None:
    metadata = analysis["metadata"]
    print("─" * 78)
    print(f"{title}")
    print(f"  {story}")
    print(f"  => {STATUS_LABEL[analysis['status']]}   "
          f"identidade={metadata['scores']['identity']}  transação={metadata['scores']['transaction']}   "
          f"({metadata['decision_latency_ms']:.1f} ms)")
    print(f"     {metadata['decision_reason']}")
    for hit in metadata["rules_triggered"]:
        print(f"     {hit['rule']} {hit['points']:+4d}  {hit['reason']}")


def main() -> None:
    print("Motor antifraude de Pix — demonstração\n")

    tenant = payer()
    daily_life(tenant, amount=80000, until=NOW - timedelta(days=95))
    landlord = account()
    for month in (3, 2, 1):
        pix(tenant, landlord, 150000, NOW - timedelta(days=30 * month))
    show("1. Aluguel de todo mês", "R$ 1.500 para o mesmo dono do apartamento, como nos últimos meses.",
         pix(tenant, landlord, 150000, NOW))

    owner = payer()
    usual = daily_life(owner)
    show("2. Celular novo", "R$ 150 para o mercado de sempre, mas de um aparelho que ele nunca usou.",
         pix(owner, usual, 15000, NOW, device="dvc-celular-novo"))

    victim = payer()
    daily_life(victim)
    mule = account(opened=(NOW - timedelta(days=2)).isoformat())
    show("3. Golpe do falso parente", "Aparelho de sempre, R$ 3.000 para uma conta aberta há 2 dias.",
         pix(victim, mule, 300000, NOW))

    hub = account(opened=(NOW - timedelta(days=3)).isoformat())
    for minute in range(9):
        pix(payer(), hub, 9000, NOW + timedelta(minutes=minute))
    show("4a. Conta de CPF aberta há 3 dias", "O 10º pagador diferente em menos de uma hora.",
         pix(payer(), hub, 9000, NOW + timedelta(minutes=10)))

    shop = account(document="12.345.678/0001-95")
    for minute in range(9):
        pix(payer(), shop, 3500, NOW + timedelta(minutes=minute))
    show("4b. Lanchonete antiga (CNPJ)", "O mesmo movimento: o 10º cliente diferente na hora do almoço.",
         pix(payer(), shop, 3500, NOW + timedelta(minutes=10)))

    example_payer = payer()
    show("5. Exemplo do enunciado", "R$ 1.500 às 22h15, destino aberto há 7 dias, primeiro Pix do pagador.",
         pix(example_payer, account(opened="2026-10-10T09:00:00-03:00"), 150000,
             datetime.fromisoformat("2026-10-17T22:15:00-03:00"), geo={"latitude": -23.56, "longitude": -46.65}))
    print("─" * 78)


if __name__ == "__main__":
    main()
