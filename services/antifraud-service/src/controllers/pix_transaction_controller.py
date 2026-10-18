import time
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import analysis_to_dict
from errors import InvalidDateTime, PixIdConflict, PixTransactionNotFound
from repositories import HistoryRepository, PixRepository
from rules import DEFAULT_PARAMETERS, DecisionEngine, PixRequest
from utils.document_number import only_digits
from utils.request_hash import request_hash


class PixTransactionController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_repository = PixRepository(self.context)
        self.history_repository = HistoryRepository(self.context)
        self.engine = DecisionEngine(parameters=DEFAULT_PARAMETERS)

    def create(self, payload: dict) -> tuple:
        body_hash = request_hash(payload)

        previous = self.previous_analysis(payload["id"], body_hash)
        if previous is not None:
            return previous, False

        started_at = time.perf_counter()
        pix = to_pix_request(payload)
        locked = self.history_repository.lock_participants(pix, self.engine.parameters.payer_lock_timeout_ms)

        previous = self.previous_analysis(payload["id"], body_hash)
        if previous is not None:
            return previous, False

        history = self.history_repository.load(pix, self.engine.parameters, payer_lock_timed_out=not locked)
        decision = self.engine.evaluate(pix, history)
        latency_ms = (time.perf_counter() - started_at) * 1000

        try:
            self.pix_repository.save(payload, pix, body_hash, decision, latency_ms)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            previous = self.previous_analysis(payload["id"], body_hash)
            if previous is not None:
                return previous, False
            raise

        self.logger.info(f"Pix {pix.pix_id}: {decision.status} "
                         f"(identidade={decision.identity_score}, transação={decision.transaction_score}, "
                         f"{latency_ms:.1f} ms)")
        return self.get(pix.pix_id), True

    def get(self, pix_id: str) -> dict:
        found = self.pix_repository.find_analysis(pix_id)
        if found is None:
            raise PixTransactionNotFound(pix_id)
        return analysis_to_dict(*found)

    def previous_analysis(self, pix_id: str, body_hash: str):
        transaction = self.pix_repository.find_transaction(pix_id)
        if transaction is None:
            return None
        if transaction.request_hash != body_hash:
            raise PixIdConflict(pix_id)
        return self.get(pix_id)


def parse_date(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidDateTime(field, value)
    if parsed.tzinfo is None:
        raise InvalidDateTime(field, value)
    return parsed


def to_pix_request(payload: dict) -> PixRequest:
    source_account = payload["source_account"]
    destination_account = payload["destination_account"]
    source = payload["source"]
    geolocation = source.get("geolocation") or {}

    return PixRequest(
        pix_id=payload["id"],
        amount_cents=payload["amount"],
        transaction_date=parse_date(payload["transaction_date"], "transaction_date"),
        source_document=only_digits(source_account["owner"]["document_number"]),
        source_opening_date=parse_date(source_account["opening_date"], "source_account.opening_date"),
        destination_account=(destination_account["participant"], destination_account["branch"],
                             destination_account["account_number"]),
        destination_document=only_digits(destination_account["owner"]["document_number"]),
        destination_opening_date=parse_date(destination_account["opening_date"],
                                            "destination_account.opening_date"),
        device_id=source["device_id"],
        channel=source["channel"],
        ip=source["ip"],
        latitude=geolocation.get("latitude"),
        longitude=geolocation.get("longitude"),
    )
