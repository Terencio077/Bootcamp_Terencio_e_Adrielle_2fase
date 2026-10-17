"""Como as notas viram decisão — e os cenários que justificam cada limiar."""

from datetime import datetime, timedelta

from builders import NOW, history, known_payer, make_pix, past

from rules import APPROVED, REJECTED, TWO_FACTOR_REQUIRED, DecisionEngine
from rules.rule import FORCE_TWO_FACTOR, IDENTITY, REJECT, TRANSACTION, Rule, RuleHit

engine = DecisionEngine()


class FixedRule(Rule):
    """Regra de mentira, para testar a decisão sem depender das regras reais."""

    def __init__(self, axis: str, points: int, effect: str = "SCORE", code: str = "FX01") -> None:
        self.code, self.axis, self.points, self.effect = code, axis, points, effect

    def evaluate(self, pix, history, parameters):
        return RuleHit(self.code, self.axis, self.effect, self.points, "teste", {})


class BrokenRule(Rule):
    code, axis = "BR01", TRANSACTION

    def evaluate(self, pix, history, parameters):
        raise ZeroDivisionError()


def decide(*rules):
    return DecisionEngine(rules=list(rules)).evaluate(make_pix(), history())


# ── a tabela de decisão ────────────────────────────────────────────────

def test_sem_pontos_aprova():
    assert decide().status == APPROVED


def test_29_pontos_em_qualquer_eixo_ainda_aprova():
    assert decide(FixedRule(IDENTITY, 29), FixedRule(TRANSACTION, 29, code="FX02")).status == APPROVED


def test_30_pontos_de_identidade_pedem_2fa():
    assert decide(FixedRule(IDENTITY, 30)).status == TWO_FACTOR_REQUIRED


def test_30_pontos_de_transacao_pedem_2fa_como_pausa_de_confirmacao():
    assert decide(FixedRule(TRANSACTION, 30)).status == TWO_FACTOR_REQUIRED


def test_transacao_recusa_mais_cedo_que_identidade():
    # O ponto central do motor: com 60 pontos, a dúvida sobre QUEM ainda se
    # resolve com 2FA; a dúvida sobre O QUÊ, não.
    assert decide(FixedRule(TRANSACTION, 60)).status == REJECTED
    assert decide(FixedRule(IDENTITY, 60)).status == TWO_FACTOR_REQUIRED
    assert decide(FixedRule(IDENTITY, 80)).status == REJECTED


def test_duvida_nos_dois_eixos_ao_mesmo_tempo_recusa():
    assert decide(FixedRule(IDENTITY, 40), FixedRule(TRANSACTION, 40, code="FX02")).status == REJECTED
    assert decide(FixedRule(IDENTITY, 39), FixedRule(TRANSACTION, 40, code="FX02")).status == TWO_FACTOR_REQUIRED


def test_regra_de_bloqueio_recusa_sozinha():
    assert decide(FixedRule(IDENTITY, 0, effect=REJECT)).status == REJECTED


def test_piso_regulatorio_pede_2fa_mesmo_sem_pontos():
    decision = decide(FixedRule(IDENTITY, 0, effect=FORCE_TWO_FACTOR))
    assert decision.status == TWO_FACTOR_REQUIRED
    assert "FX01" in decision.reason


def test_confianca_nao_deixa_nota_negativa():
    decision = decide(FixedRule(TRANSACTION, -30))
    assert decision.transaction_score == 0


def test_regra_quebrada_nao_derruba_a_analise_e_pede_2fa():
    decision = decide(BrokenRule())
    assert decision.status == TWO_FACTOR_REQUIRED
    assert decision.hits[0].evidence == {"error": "ZeroDivisionError"}


# ── cenários com as regras reais ───────────────────────────────────────

def test_exemplo_do_enunciado_pede_2fa():
    pix = make_pix(
        amount_cents=150000,
        transaction_date=datetime.fromisoformat("2026-10-17T22:15:00-03:00"),
        destination_opening_date=datetime.fromisoformat("2026-10-10T09:00:00-03:00"),
    )
    decision = engine.evaluate(pix, history())
    assert decision.status == TWO_FACTOR_REQUIRED
    assert {hit.code for hit in decision.hits} == {"ID01", "ID02", "TX01", "TX07"}


def test_aluguel_para_o_mesmo_recebedor_de_sempre_passa_sem_friccao():
    rents = [past(minutes_ago=60 * 24 * 30 * month, amount_cents=150000) for month in (1, 2, 3)]
    decision = engine.evaluate(make_pix(amount_cents=150000), history(*known_payer(), *rents))
    assert decision.status == APPROVED


def test_golpe_dono_da_conta_pagando_conta_nova_e_recusado_sem_2fa():
    # Aparelho de sempre (identidade limpa), mas valor muito acima do perfil,
    # para uma conta aberta há 2 dias, recebedor nunca pago. 2FA não ajudaria.
    pix = make_pix(amount_cents=300000, destination_document="55566677788",
                   destination_account=("00000000", "0001", "999"),
                   destination_opening_date=NOW - timedelta(days=2))
    decision = engine.evaluate(pix, history(*known_payer()))
    assert decision.identity_score == 0
    assert decision.status == REJECTED


def test_aparelho_novo_pagando_recebedor_de_sempre_pede_2fa():
    decision = engine.evaluate(make_pix(device_id="device-b", amount_cents=50000), history(*known_payer()))
    assert decision.status == TWO_FACTOR_REQUIRED
    assert decision.transaction_score == 0


def test_pix_pequeno_do_aparelho_de_sempre_aprova():
    assert engine.evaluate(make_pix(), history(*known_payer())).status == APPROVED
