"""Cenários combinados e invariantes que complementam os 92 unitários da v3."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from casos import COMPANY, NOW, history, past, pix, summary, usual
from rules import APPROVED, REJECTED, TWO_FACTOR_REQUIRED, DecisionEngine
from rules.parameters import DEFAULT_PARAMETERS as P
from rules.rule import FORCE_TWO_FACTOR, TRANSACTION, Rule
from rules.transaction_rules import NightLimit
from rules.trust_rules import RecurringPayee


@pytest.mark.parametrize("minutes", [11, 59], ids=["apos_janela_de_rajada", "quase_uma_hora"])
def test_novo_id_apos_2fa_sem_confirmacao_continua_exigindo_desafio(minutes):
    engine = DecisionEngine()
    current = pix(device_id="new-phone", amount_cents=15000)
    first = engine.evaluate(current, history(*usual()))
    assert first.status == TWO_FACTOR_REQUIRED, summary(first)
    pending = past(transaction_date=NOW, amount_cents=current.amount_cents,
                   device_id=current.device_id, status=first.status)
    retry = replace(current, pix_id="review-retry", transaction_date=NOW + timedelta(minutes=minutes))
    second = engine.evaluate(retry, history(pending, *usual()))
    assert second.status == TWO_FACTOR_REQUIRED, summary(second)


def test_pix_pequeno_nao_libera_aparelho_um_segundo_antes_de_24h():
    engine = DecisionEngine()
    first_pix = pix(amount_cents=5000)
    first = engine.evaluate(first_pix, history())
    assert first.status == APPROVED, summary(first)
    approved = past(transaction_date=NOW, amount_cents=5000, status=first.status)
    large = replace(first_pix, pix_id="review-large", amount_cents=50000,
                    transaction_date=NOW + timedelta(hours=24) - timedelta(seconds=1))
    decision = engine.evaluate(large, history(approved))
    assert decision.status == TWO_FACTOR_REQUIRED, summary(decision)


# AJUSTE (decisão do time, 17/10): a recorrência (TR01) passou a exigir 30 dias
# desde o primeiro Pix aprovado ao recebedor. Os dois testes que dependem de
# recorrência ganharam um Pix antigo (35 dias) no histórico; nenhuma asserção mudou.


def test_comercio_com_35_pagadores_e_relacao_recorrente_aprova_compra_pequena():
    decision = DecisionEngine().evaluate(
        pix(amount_cents=3000, destination_document=COMPANY),
        history(*usual(destination_document=COMPANY),
                past(transaction_date=NOW - timedelta(days=35), destination_document=COMPANY), other_payers=34),
    )
    assert decision.status == APPROVED, summary(decision)


def test_mesmo_comercio_sem_relacao_recorrente_pede_confirmacao_sem_recusa():
    decision = DecisionEngine().evaluate(
        pix(amount_cents=3000, destination_document=COMPANY),
        history(*usual(), other_payers=34),
    )
    assert decision.status == TWO_FACTOR_REQUIRED, summary(decision)


def test_cnpj_antigo_nao_ganha_imunidade_a_outros_sinais_fortes():
    decision = DecisionEngine().evaluate(
        pix(amount_cents=1000000, destination_document=COMPANY),
        history(*usual(), other_payers=34),
    )
    assert decision.status == REJECTED, summary(decision)
    assert any(hit.code == "TX04" for hit in decision.hits)


def test_descontos_de_recorrencia_e_mesma_titularidade_nao_removem_piso_noturno():
    current = pix(amount_cents=150000, transaction_date=NOW.replace(hour=22))
    current = replace(current, destination_document=current.source_document)
    decision = DecisionEngine().evaluate(
        current,
        history(*usual(amount_cents=150000, destination_document=current.source_document),
                past(transaction_date=NOW - timedelta(days=35), amount_cents=150000,
                     destination_document=current.source_document)),
    )
    assert {"TX07", "TR01", "TR02"}.issubset({hit.code for hit in decision.hits})
    assert decision.status == TWO_FACTOR_REQUIRED, summary(decision)


@pytest.mark.parametrize("clock, triggered", [
    ("19:59:59", False), ("20:00:00", True), ("05:59:59", True), ("06:00:00", False),
])
def test_fronteiras_da_janela_noturna(clock, triggered):
    moment = datetime.fromisoformat(f"2026-10-15T{clock}-03:00")
    hit = NightLimit().evaluate(pix(amount_cents=150000, transaction_date=moment), history(), P)
    assert (hit is not None) is triggered
    if triggered:
        assert hit.effect == FORCE_TWO_FACTOR


class FailingTransactionRule(Rule):
    code = "ZZTEST"
    axis = TRANSACTION

    def evaluate(self, pix, history, parameters):
        raise RuntimeError("falha injetada pelo teste")


@pytest.mark.parametrize("amount, expected", [(99999, TWO_FACTOR_REQUIRED), (100000, REJECTED)])
def test_desconto_nao_esconde_falha_da_regra_na_fronteira_de_valor(amount, expected):
    # Exercita a política atual de fallback; não afirma que 2FA resolve falta de informação.
    decision = DecisionEngine(rules=[FailingTransactionRule(), RecurringPayee()]).evaluate(
        pix(amount_cents=amount), history(*usual()),
    )
    assert decision.transaction_score == 0
    assert decision.status == expected, summary(decision)


def test_mesmo_instante_em_tres_offsets_nao_pode_fabricar_tres_dias_de_relacao():
    # Três pagamentos distintos no mesmo instante; muda apenas a representação do fuso.
    # Em qualquer fuso fixo, todos aconteceram no mesmo dia.
    instant = datetime.fromisoformat("2026-10-14T11:30:00+00:00")
    offsets = [-12, 0, 14]
    mixed = history(*(past(transaction_date=instant.astimezone(timezone(timedelta(hours=offset))))
                      for offset in offsets))
    normalized = history(*(replace(item, transaction_date=item.transaction_date.astimezone(timezone.utc))
                           for item in mixed.payer_pix))
    assert len({item.transaction_date for item in mixed.payer_pix}) == 1
    assert RecurringPayee().evaluate(pix(), normalized, P) is None
    assert RecurringPayee().evaluate(pix(), mixed, P) is None, (
        "TR01 concedeu confiança contando datas locais de offsets diferentes para o mesmo instante."
    )
