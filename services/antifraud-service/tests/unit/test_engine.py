from datetime import datetime, timedelta

from builders import NOW, history, known_payer, long_relationship, make_pix, past

from rules import APPROVED, REJECTED, TWO_FACTOR_REQUIRED, DecisionEngine, History
from rules.rule import FORCE_TWO_FACTOR, IDENTITY, REJECT, TRANSACTION, Rule, RuleHit

engine = DecisionEngine()


class FixedRule(Rule):
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


def test_sem_pontos_aprova():
    assert decide().status == APPROVED


def test_29_pontos_em_qualquer_eixo_ainda_aprova():
    assert decide(FixedRule(IDENTITY, 29), FixedRule(TRANSACTION, 29, code="FX02")).status == APPROVED


def test_30_pontos_de_identidade_pedem_2fa():
    assert decide(FixedRule(IDENTITY, 30)).status == TWO_FACTOR_REQUIRED


def test_30_pontos_de_transacao_pedem_2fa_como_pausa_de_confirmacao():
    assert decide(FixedRule(TRANSACTION, 30)).status == TWO_FACTOR_REQUIRED


def test_transacao_recusa_mais_cedo_que_identidade():
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
    pix = make_pix(amount_cents=300000, destination_document="55566677788",
                   destination_account=("00000000", "0001", "999"),
                   destination_opening_date=NOW - timedelta(days=2))
    decision = engine.evaluate(pix, history(*known_payer()))
    assert decision.identity_score == 0
    assert decision.status == REJECTED


def test_aparelho_novo_pagando_recebedor_de_sempre_pede_2fa():
    decision = engine.evaluate(make_pix(device_id="device-b", amount_cents=50000), history(*known_payer(), *long_relationship()))
    assert decision.status == TWO_FACTOR_REQUIRED
    assert decision.transaction_score == 0


def test_pix_pequeno_do_aparelho_de_sempre_aprova():
    assert engine.evaluate(make_pix(), history(*known_payer())).status == APPROVED


class BrokenIdentityRule(Rule):
    code, axis = "BR02", IDENTITY

    def evaluate(self, pix, history, parameters):
        raise KeyError()


def test_regra_de_transacao_quebrada_em_pix_alto_recusa():
    decision = DecisionEngine(rules=[BrokenRule()]).evaluate(make_pix(amount_cents=100000), history())
    assert decision.status == REJECTED


def test_regra_de_identidade_quebrada_pede_2fa_mesmo_em_pix_alto():
    decision = DecisionEngine(rules=[BrokenIdentityRule()]).evaluate(make_pix(amount_cents=900000), history())
    assert decision.status == TWO_FACTOR_REQUIRED


NIGHT = NOW.replace(hour=22, minute=15)


def rent_payer() -> list:
    return known_payer(amount_cents=150000) + long_relationship(amount_cents=150000)


def test_furo_noturno_acima_do_limite_para_recebedor_recorrente_nao_aprova():
    decision = engine.evaluate(make_pix(amount_cents=150000, transaction_date=NIGHT), history(*rent_payer()))
    assert {"TX07", "TR01"} <= {hit.code for hit in decision.hits}
    assert decision.status == TWO_FACTOR_REQUIRED


def test_legitimo_noturno_dentro_do_limite_para_recebedor_recorrente_aprova():
    decision = engine.evaluate(make_pix(amount_cents=90000, transaction_date=NIGHT), history(*rent_payer()))
    assert decision.status == APPROVED


def friends_burst() -> list:
    return [past(minutes_ago=i + 1, amount_cents=5000, destination_document=f"0000000000{i}") for i in range(9)]


def test_legitimo_churrasco_dividido_com_dez_amigos_pede_2fa_e_nao_recusa():
    pix = make_pix(amount_cents=5000, destination_document="99999999999")
    decision = engine.evaluate(pix, history(*known_payer(), *friends_burst()))
    assert decision.status == TWO_FACTOR_REQUIRED


def test_rajada_de_aparelho_nao_confiavel_recusa_pela_combinacao():
    burst = [past(minutes_ago=i + 1, amount_cents=5000, device_id="device-b", status=TWO_FACTOR_REQUIRED)
             for i in range(9)]
    decision = engine.evaluate(make_pix(amount_cents=5000, device_id="device-b"), history(*known_payer(), *burst))
    assert decision.status == REJECTED


COMPANY = "12345678000195"


def test_conta_de_cpf_aberta_ha_3_dias_recebendo_de_dez_pagadores_recusa_pela_combinacao():
    pix = make_pix(destination_opening_date=NOW - timedelta(days=3), destination_document="55566677788")
    decision = engine.evaluate(pix, history(*known_payer(), distinct_other_payers=9))
    assert {"TX01", "TX02"} <= {hit.code for hit in decision.hits}
    assert decision.status == REJECTED


def test_legitimo_cpf_novo_recebendo_dos_primeiros_clientes_nao_e_recusado():
    pix = make_pix(destination_opening_date=NOW - timedelta(days=5), destination_document="55566677788")
    decision = engine.evaluate(pix, history(*known_payer(), distinct_other_payers=4))
    assert decision.status == TWO_FACTOR_REQUIRED


def test_legitimo_comercio_antigo_recebendo_de_dez_pagadores_aprova_o_cliente_habitual():
    habitual = known_payer(destination_document=COMPANY)
    pix = make_pix(destination_document=COMPANY)
    decision = engine.evaluate(pix, history(*habitual, distinct_other_payers=9))
    assert decision.status == APPROVED


def test_tres_pix_de_1_real_em_dias_diferentes_nao_aprovam_5000():
    warming = [past(minutes_ago=60 * 24 * day, amount_cents=100) for day in (1, 2, 3)]
    others = [past(minutes_ago=60 * 24 * day, destination_document="11122233344") for day in (4, 5, 6)]
    decision = engine.evaluate(make_pix(amount_cents=500000), history(*warming, *others))
    assert decision.status == TWO_FACTOR_REQUIRED
    assert decision.transaction_score >= 40


def test_legitimo_emprestimo_ao_amigo_de_sempre_pede_2fa_e_nao_recusa():
    friend = [past(minutes_ago=60 * 24 * day, amount_cents=5000) for day in (1, 8, 15, 22, 29)]
    decision = engine.evaluate(make_pix(amount_cents=200000), history(*friend))
    assert decision.status == TWO_FACTOR_REQUIRED
    assert "TX05" not in {hit.code for hit in decision.hits}


def exposure_history() -> list:
    old = [past(minutes_ago=60 * 24 * day, amount_cents=150000, destination_document=f"9000000000{day % 10}")
           for day in range(8, 20)]
    today = [past(minutes_ago=60 * hour, amount_cents=150000, destination_document=f"8000000000{hour}")
             for hour in (1, 2, 3)]
    return old + today


def test_furo_tx05_aumentar_o_valor_nao_desliga_a_soma_do_dia():
    for amount in (199999, 200000, 250000):
        decision = engine.evaluate(make_pix(amount_cents=amount, destination_document="70000000000"),
                                   history(*exposure_history()))
        assert "TX05" in {hit.code for hit in decision.hits}, amount
        assert decision.status != APPROVED, amount


def test_furo_tx08_tentativa_pendente_nao_tira_o_primeiro_pagamento():
    pending = past(minutes_ago=0.02, amount_cents=100000, destination_document="70000000000",
                   status=TWO_FACTOR_REQUIRED)
    pix = make_pix(amount_cents=100000, destination_document="70000000000",
                   destination_opening_date=NOW - timedelta(days=3))
    decision = engine.evaluate(pix, history(*known_payer(), pending))
    assert "TX08" in {hit.code for hit in decision.hits}
    assert decision.status != APPROVED


def test_furo_corte_de_500_antiguidade_vem_do_agregado():
    recent_only = [past(minutes_ago=60 * hour, amount_cents=150000, destination_document=f"8000000000{hour}")
                   for hour in (1, 2, 3)]
    cut = History(payer_pix=sorted(recent_only, key=lambda p: p.transaction_date, reverse=True),
                  payer_first_seen=NOW - timedelta(days=80), payer_baseline_30d_cents=29 * 10000)
    decision = engine.evaluate(make_pix(amount_cents=150000, destination_document="70000000000"), cut)
    assert "TX05" in {hit.code for hit in decision.hits}
