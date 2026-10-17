"""Executa o SQL real da TX03 em tabelas mínimas no SQLite em memória.

Valida filtragem, agregação e autorreforço. Não valida migrations,
tipos/planos PostgreSQL, advisory locks ou concorrência.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from casos import ACCOUNT, NOW, pix
from rules.parameters import DEFAULT_PARAMETERS as P


@pytest.fixture
def ledger(service_modules):
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as session:
        definitions = [
            "CREATE TABLE analysis_statuses (id INTEGER PRIMARY KEY, enumerator TEXT)",
            "CREATE TABLE risk_axes (id INTEGER PRIMARY KEY, enumerator TEXT)",
            "CREATE TABLE pix_transactions (id INTEGER PRIMARY KEY, pix_id TEXT, source_document TEXT, "
            "destination_participant TEXT, destination_branch TEXT, destination_account_number TEXT, "
            "transaction_date TEXT)",
            "CREATE TABLE pix_analyses (id INTEGER PRIMARY KEY, pix_transaction_id INTEGER, analysis_status_id INTEGER)",
            "CREATE TABLE rule_hits (id INTEGER PRIMARY KEY, pix_analysis_id INTEGER, rule_code TEXT, "
            "risk_axis_id INTEGER, effect TEXT, points INTEGER)",
        ]
        for sql in definitions:
            session.execute(text(sql))
        session.execute(text("INSERT INTO analysis_statuses VALUES (1, 'REJECTED'), (2, 'APPROVED')"))
        session.execute(text("INSERT INTO risk_axes VALUES (1, 'IDENTITY'), (2, 'TRANSACTION')"))
        repo = service_modules.HistoryRepository(SimpleNamespace(db_session=session))
        counter = 0

        def add(payer, hits, *, date=None, destination=ACCOUNT, status_id=1):
            nonlocal counter
            counter += 1
            # Offset único em todos os dados deste fixture: comparação textual é cronológica.
            when = (date or NOW - timedelta(days=1)).isoformat(sep=" ")
            session.execute(text("INSERT INTO pix_transactions VALUES (:id, :pix_id, :payer, :p, :b, :a, :date)"),
                            {"id": counter, "pix_id": f"old-{counter}", "payer": payer,
                             "p": destination[0], "b": destination[1], "a": destination[2], "date": when})
            session.execute(text("INSERT INTO pix_analyses VALUES (:id, :id, :status)"),
                            {"id": counter, "status": status_id})
            for code, axis, effect, points in hits:
                session.execute(text("INSERT INTO rule_hits (pix_analysis_id, rule_code, risk_axis_id, effect, points) "
                                     "VALUES (:id, :code, :axis, :effect, :points)"),
                                {"id": counter, "code": code, "axis": 1 if axis == "ID" else 2,
                                 "effect": effect, "points": points})

        yield SimpleNamespace(add=add, count=lambda: repo.rejected_destination_payers(pix(), P))
    engine.dispose()


def test_recusas_so_de_identidade_nao_contaminam_destino(ledger):
    for payer in ("11111111111", "22222222222"):
        ledger.add(payer, [("ID03", "ID", "SCORE", 45), ("ID04", "ID", "SCORE", 50)])
    assert ledger.count() == 0


def test_recusa_que_precisou_dos_pontos_da_tx03_nao_se_reproduz(ledger):
    ledger.add("11111111111", [("TX04", "TX", "SCORE", 40), ("TX03", "TX", "SCORE", 25)])
    assert ledger.count() == 0


def test_descontos_participam_do_calculo_sem_tx03(ledger):
    ledger.add("11111111111", [("TX04", "TX", "SCORE", 40), ("TX01", "TX", "SCORE", 25),
                               ("TR01", "TX", "SCORE", -30), ("TX03", "TX", "SCORE", 25)])
    assert ledger.count() == 0


def test_varias_recusas_do_mesmo_pagador_contam_uma_vez(ledger):
    for _ in range(3):
        ledger.add("11111111111", [("TX04", "TX", "SCORE", 40), ("TX01", "TX", "SCORE", 25)])
    assert ledger.count() == 1


def test_so_entram_destino_janela_e_status_corretos(ledger):
    hits = [("TX04", "TX", "SCORE", 40), ("TX01", "TX", "SCORE", 25)]
    ledger.add("11111111111", hits)  # único elegível
    ledger.add("22222222222", hits, date=NOW - timedelta(days=31))
    ledger.add("33333333333", hits, date=NOW + timedelta(seconds=1))
    ledger.add("44444444444", hits, destination=(ACCOUNT[0], ACCOUNT[1], "another-account"))
    ledger.add("55555555555", hits, status_id=2)
    assert ledger.count() == 1


def test_reject_da_propria_tx03_tambem_deve_ser_excluido_do_autorreforco(ledger):
    # É o formato persistido quando TX03 falha num Pix >= R$ 1.000:
    # DecisionEngine.failure_hit gera TX03 / TRANSACTION / REJECT / 0.
    ledger.add("11111111111", [("TX03", "TX", "REJECT", 0)])
    assert ledger.count() == 0, "O ramo EXISTS inclui REJECT da própria TX03 e volta a alimentar a regra."


def test_reject_de_outra_regra_transacional_continua_elegivel(ledger):
    ledger.add("11111111111", [("TX99", "TX", "REJECT", 0)])
    assert ledger.count() == 1
