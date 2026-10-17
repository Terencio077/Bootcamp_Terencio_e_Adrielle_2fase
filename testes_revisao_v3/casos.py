"""Dados sintéticos próprios da revisão, independentes dos builders antigos."""

from dataclasses import replace
from datetime import datetime, timedelta

from rules import APPROVED, DestinationHistory, History, PastPix, PixRequest

NOW = datetime.fromisoformat("2026-10-15T14:00:00-03:00")
OLD = datetime.fromisoformat("2020-01-01T10:00:00-03:00")
PAYEE = "98765432100"
COMPANY = "12345678000195"
ACCOUNT = ("60701190", "3675", "10442")


def pix(**changes):
    return replace(PixRequest(
        pix_id="review-current", amount_cents=10000, transaction_date=NOW,
        source_document="12345678909", source_opening_date=OLD,
        destination_account=ACCOUNT, destination_document=PAYEE,
        destination_opening_date=OLD, device_id="device-a", channel="app", ip="198.51.100.23",
    ), **changes)


def past(**changes):
    return replace(PastPix(
        transaction_date=NOW - timedelta(days=1), amount_cents=10000,
        status=APPROVED, device_id="device-a", channel="app",
        destination_account=ACCOUNT, destination_document=PAYEE,
    ), **changes)


def history(*items, other_payers=0):
    return History(
        payer_pix=sorted(items, key=lambda item: item.transaction_date, reverse=True),
        destination=DestinationHistory(distinct_other_payers_in_window=other_payers),
    )


def usual(**changes):
    return [past(transaction_date=NOW - timedelta(days=day), **changes) for day in range(1, 7)]


def summary(decision):
    return f"status={decision.status}; ID={decision.identity_score}; TX={decision.transaction_score}; " + ", ".join(
        f"{hit.code}:{hit.points}:{hit.effect}" for hit in decision.hits
    )
