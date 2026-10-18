from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

APPROVED = "APPROVED"
TWO_FACTOR_REQUIRED = "TWO_FACTOR_REQUIRED"
REJECTED = "REJECTED"

BUSINESS_TIMEZONE = timezone(timedelta(hours=-3))


def business_date(moment: datetime) -> date:
    return moment.astimezone(BUSINESS_TIMEZONE).date()


AccountKey = Tuple[str, str, str]


@dataclass(frozen=True)
class PixRequest:
    pix_id: str
    amount_cents: int
    transaction_date: datetime
    source_document: str
    source_opening_date: datetime
    destination_account: AccountKey
    destination_document: str
    destination_opening_date: datetime
    device_id: str
    channel: str
    ip: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def local_hour(self) -> int:
        return self.transaction_date.hour

    @property
    def payer_is_person(self) -> bool:
        return len(self.source_document) == 11


@dataclass(frozen=True)
class PastPix:
    transaction_date: datetime
    amount_cents: int
    status: str
    device_id: str
    channel: str
    destination_account: AccountKey
    destination_document: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def local_hour(self) -> int:
        return self.transaction_date.hour

    @property
    def money_may_have_left(self) -> bool:
        return self.status in (APPROVED, TWO_FACTOR_REQUIRED)


@dataclass(frozen=True)
class DestinationHistory:
    distinct_other_payers_in_window: int = 0
    rejected_payers_in_window: int = 0
    peak_payers_30d: int = 0


@dataclass(frozen=True)
class History:
    payer_pix: List[PastPix] = field(default_factory=list)
    destination: DestinationHistory = field(default_factory=DestinationHistory)
    payer_first_seen: Optional[datetime] = None
    payer_baseline_30d_cents: Optional[int] = None
    payer_lock_timed_out: bool = False

    def payer_since(self, moment: datetime) -> List[PastPix]:
        return [past for past in self.payer_pix if past.transaction_date >= moment]

    def payer_within(self, now: datetime, window: timedelta) -> List[PastPix]:
        return self.payer_since(now - window)
