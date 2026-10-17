import time
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from dtos import analysis_to_dict
from errors import InvalidTransactionDate, PixIdConflict, PixTransactionNotFound
from repositories import HistoryRepository, PixRepository
from rules import DEFAULT_PARAMETERS, DecisionEngine, PixRequest
from utils.document_number import only_digits
from utils.request_hash import request_hash


class PixTransactionController(BaseController):
    """Recebe um Pix, pede o histórico, roda o motor e grava a decisão.

    O controller é o maestro, e de propósito não decide nada sobre fraude:
    quem decide é o motor (src/rules/). Ele só garante a ordem:

        1. Idempotência: o mesmo Pix (mesmo id) nunca é analisado duas vezes.
        2. Histórico: uma ida ao banco, antes das regras.
        3. Motor: regras puras, sem banco.
        4. Gravação: transação + análise + motivos, num commit só.

    O tempo medido (decision_latency_ms) vai do passo 2 ao 3, que é o
    tempo do motor de verdade, e é gravado em toda análise: o Banco Central
    acompanha o p95/p99 do tempo de resposta do Pix, e este é o pedaço dele
    que é nosso.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.pix_repository = PixRepository(self.context)
        self.history_repository = HistoryRepository(self.context)
        self.engine = DecisionEngine(parameters=DEFAULT_PARAMETERS)

    def create(self, payload: dict) -> tuple:
        """Devolve (análise, criada_agora). Criada agora vira 201; repetição vira 200."""
        body_hash = request_hash(payload)

        previous = self.previous_analysis(payload["id"], body_hash)
        if previous is not None:
            return previous, False

        started_at = time.perf_counter()
        pix = to_pix_request(payload)
        history = self.history_repository.load(pix, self.engine.parameters)
        decision = self.engine.evaluate(pix, history)
        latency_ms = (time.perf_counter() - started_at) * 1000

        self.pix_repository.save(payload, pix, body_hash, decision, latency_ms)
        self.logger.info(f"Pix {pix.pix_id}: {decision.status} "
                         f"(identidade={decision.identity_score}, transação={decision.transaction_score}, "
                         f"{latency_ms:.1f} ms)")

        try:
            self.session.commit()
        except IntegrityError:
            # Duas chegadas simultâneas do mesmo Pix: o UNIQUE(pix_id) deixa
            # passar uma só, e a outra devolve a análise que ganhou.
            self.session.rollback()
            previous = self.previous_analysis(payload["id"], body_hash)
            if previous is not None:
                return previous, False
            raise

        return self.get(pix.pix_id), True

    def get(self, pix_id: str) -> dict:
        found = self.pix_repository.find_analysis(pix_id)
        if found is None:
            raise PixTransactionNotFound(pix_id)
        return analysis_to_dict(*found)

    def previous_analysis(self, pix_id: str, body_hash: str):
        """A análise já gravada deste Pix, ou None.

        Mesmo id com outro corpo é conflito (409): o id identifica UM Pix, e
        reanalisar com outros dados apagaria a decisão que o cliente já viu.
        """
        transaction = self.pix_repository.find_transaction(pix_id)
        if transaction is None:
            return None
        if transaction.request_hash != body_hash:
            raise PixIdConflict(pix_id)
        return self.get(pix_id)


def parse_date(value: str) -> datetime:
    """ISO 8601 com fuso obrigatório. Sem fuso, "22:15" não diz se é noite para quem pagou."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidTransactionDate(value)
    if parsed.tzinfo is None:
        raise InvalidTransactionDate(value)
    return parsed


def to_pix_request(payload: dict) -> PixRequest:
    source_account = payload["source_account"]
    destination_account = payload["destination_account"]
    source = payload["source"]
    geolocation = source.get("geolocation") or {}

    return PixRequest(
        pix_id=payload["id"],
        amount_cents=payload["amount"],
        transaction_date=parse_date(payload["transaction_date"]),
        source_document=only_digits(source_account["owner"]["document_number"]),
        source_opening_date=parse_date(source_account["opening_date"]),
        destination_account=(destination_account["participant"], destination_account["branch"],
                             destination_account["account_number"]),
        destination_document=only_digits(destination_account["owner"]["document_number"]),
        destination_opening_date=parse_date(destination_account["opening_date"]),
        device_id=source["device_id"],
        channel=source["channel"],
        ip=source["ip"],
        latitude=geolocation.get("latitude"),
        longitude=geolocation.get("longitude"),
    )
