"""Monta Pix e históricos à mão, com padrões neutros (nenhuma regra dispara).

Cada teste muda só o campo que interessa. O Pix padrão é de dia, valor
baixo, para uma conta antiga, de um aparelho que o pagador já usa: um Pix
que o motor aprova sem pontuar nada.
"""

from dataclasses import replace
from datetime import datetime, timedelta

from rules import APPROVED, DestinationHistory, History, PastPix, PixRequest

NOW = datetime.fromisoformat("2026-10-15T14:00:00-03:00")
PAYER = "12345678909"
PAYEE = "98765432100"
OLD_ACCOUNT = datetime.fromisoformat("2020-01-01T10:00:00-03:00")
DESTINATION = ("60701190", "3675", "10442")


def make_pix(**overrides) -> PixRequest:
    pix = PixRequest(
        pix_id="pix-test",
        amount_cents=10000,
        transaction_date=NOW,
        source_document=PAYER,
        source_opening_date=OLD_ACCOUNT,
        destination_account=DESTINATION,
        destination_document=PAYEE,
        destination_opening_date=OLD_ACCOUNT,
        device_id="device-a",
        channel="app",
        ip="198.51.100.23",
    )
    return replace(pix, **overrides)


def past(minutes_ago: float = 60 * 24, **overrides) -> PastPix:
    pix = PastPix(
        transaction_date=NOW - timedelta(minutes=minutes_ago),
        amount_cents=10000,
        status=APPROVED,
        device_id="device-a",
        channel="app",
        destination_account=DESTINATION,
        destination_document=PAYEE,
    )
    return replace(pix, **overrides)


def history(*payer_pix: PastPix, distinct_other_payers: int = 0, rejected: int = 0) -> History:
    ordered = sorted(payer_pix, key=lambda item: item.transaction_date, reverse=True)
    return History(payer_pix=ordered,
                   destination=DestinationHistory(distinct_other_payers_in_window=distinct_other_payers,
                                                  rejected_payers_in_window=rejected))


def long_relationship(**overrides) -> list:
    """Pagador que paga o mesmo recebedor uma vez por mês, há três meses."""
    return [past(minutes_ago=60 * 24 * 30 * month, **overrides) for month in (1, 2, 3)]


def known_payer(count: int = 6, **overrides) -> list:
    """Um pagador com histórico: um Pix aprovado por dia, nos últimos `count` dias."""
    return [past(minutes_ago=60 * 24 * (day + 1), **overrides) for day in range(count)]
