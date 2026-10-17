"""Suíte adicional: execute separadamente dos testes HTTP em tests/.

Não abre conexão com PostgreSQL. O controller recebe doubles de sessão;
a consulta da TX03 é exercitada em um SQLite temporário em memória.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "services" / "antifraud-service" / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture
def service_modules(monkeypatch):
    # O import de database constrói um Engine, mas não se conecta.
    # O teste nunca usa esse Engine: injeta a própria sessão em cada caso.
    monkeypatch.setenv("DATABASE_URL", "postgresql://review:review@127.0.0.1:1/review_unused")
    monkeypatch.setenv("INTERNAL_TOKEN", "review-test-only")
    from controllers.pix_transaction_controller import PixTransactionController, to_pix_request
    from errors import InvalidDateTime, PixIdConflict
    from repositories import HistoryRepository, PixRepository

    return SimpleNamespace(
        Controller=PixTransactionController,
        to_pix_request=to_pix_request,
        InvalidDateTime=InvalidDateTime,
        PixIdConflict=PixIdConflict,
        HistoryRepository=HistoryRepository,
        PixRepository=PixRepository,
    )


@pytest.fixture
def payload():
    return {
        "id": "review-duplicate-id",
        "amount": 5000,
        "transaction_date": "2026-10-15T14:00:00-03:00",
        "source_account": {
            "branch": "0001", "account_number": "88213",
            "opening_date": "2020-01-01T10:00:00-03:00",
            "owner": {"document_number": "12345678909"},
        },
        "destination_account": {
            "participant": "60701190", "branch": "3675", "account_number": "10442",
            "opening_date": "2020-01-01T10:00:00-03:00",
            "owner": {"document_number": "98765432100"},
        },
        "source": {"device_id": "device-a", "channel": "app", "ip": "198.51.100.23"},
    }


@pytest.fixture
def controller(service_modules):
    from rules import DecisionEngine, History

    # Evita BaseController.__init__: nenhuma sessão de produção é criada.
    obj = object.__new__(service_modules.Controller)
    obj.session = Mock()
    obj.context = SimpleNamespace(db_session=obj.session)
    obj.logger = Mock()
    obj.pix_repository = service_modules.PixRepository(obj.context)
    obj.history_repository = Mock()
    obj.history_repository.load.return_value = History()
    obj.engine = DecisionEngine()
    obj.previous_analysis = Mock()
    obj.get = Mock()
    return obj
