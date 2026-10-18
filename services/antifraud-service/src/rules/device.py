from datetime import datetime, timedelta

from rules.context import APPROVED, REJECTED, History, business_date
from rules.parameters import Parameters

NEW = "NEW"
OBSERVED = "OBSERVED"
RECURRING = "RECURRING"
TRUSTED = "TRUSTED"


def device_trust(device_id: str, now: datetime, history: History, parameters: Parameters) -> str:
    uses = [past for past in history.payer_pix if past.device_id == device_id]
    if not uses:
        return NEW

    trusted_until = now - timedelta(hours=parameters.device_trust_min_age_hours)
    if any(past.status == APPROVED and past.transaction_date <= trusted_until for past in uses):
        return TRUSTED

    if any(past.status == REJECTED for past in uses):
        return OBSERVED

    days_used = {business_date(past.transaction_date) for past in uses}
    first_use = min(past.transaction_date for past in uses)
    if (len(days_used) >= parameters.device_recurring_min_days
            and now - first_use >= timedelta(days=parameters.device_recurring_min_age_days)):
        return RECURRING

    return OBSERVED


def payer_has_trusted_device(now: datetime, history: History, parameters: Parameters) -> bool:
    devices = {past.device_id for past in history.payer_pix}
    return any(device_trust(device, now, history, parameters) == TRUSTED for device in devices)
