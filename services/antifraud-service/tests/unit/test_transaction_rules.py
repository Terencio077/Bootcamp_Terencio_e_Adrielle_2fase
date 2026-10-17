"""Eixo transação e regras de confiança: limite exato e logo abaixo."""

from datetime import timedelta

from builders import NOW, PAYER, history, known_payer, long_relationship, make_pix, past

from rules import DEFAULT_PARAMETERS as P
from rules import REJECTED, TWO_FACTOR_REQUIRED
from rules.rule import FORCE_TWO_FACTOR
from rules.transaction_rules import (
    FirstPaymentToPayee,
    PayerConcentration,
    NightLimit,
    OutOfProfileAmount,
    RejectedDestination,
    Structuring,
    UnusualDailySum,
    YoungDestination,
    night_window_start,
)
from rules.trust_rules import OwnAccount, RecurringPayee


# ── TX01 Destino recém-aberto ──────────────────────────────────────────

def test_destino_aberto_ha_3_dias():
    hit = YoungDestination().evaluate(make_pix(destination_opening_date=NOW - timedelta(days=3)), history(), P)
    assert hit.points == P.young_destination_points


def test_destino_aberto_ha_20_dias_pontua_menos():
    hit = YoungDestination().evaluate(make_pix(destination_opening_date=NOW - timedelta(days=20)), history(), P)
    assert hit.points == P.recent_destination_points


def test_destino_antigo_nao_pontua():
    assert YoungDestination().evaluate(make_pix(destination_opening_date=NOW - timedelta(days=31)),
                                       history(), P) is None


# ── TX02 Concentração de pagadores ─────────────────────────────────────

COMPANY = "12345678000195"


def test_cpf_com_quatro_pagadores_na_hora_e_normal():
    assert PayerConcentration().evaluate(make_pix(), history(distinct_other_payers=3), P) is None


def test_cpf_com_cinco_pagadores_diferentes_na_hora_pontua():
    hit = PayerConcentration().evaluate(make_pix(), history(distinct_other_payers=4), P)
    assert hit.points == P.concentration_person_points


def test_cpf_com_dez_pagadores_pontua_mais_mas_nao_bloqueia_sozinho():
    hit = PayerConcentration().evaluate(make_pix(), history(distinct_other_payers=9), P)
    assert hit.points == P.concentration_person_high_points
    assert hit.effect == "SCORE"


def test_legitimo_comercio_com_dez_pagadores_na_hora_nao_pontua():
    # A lanchonete na hora do almoço: o que o revisor reproduziu como bloqueio indevido.
    assert PayerConcentration().evaluate(make_pix(destination_document=COMPANY),
                                         history(distinct_other_payers=9), P) is None


def test_comercio_com_volume_muito_alto_pontua_pouco():
    hit = PayerConcentration().evaluate(make_pix(destination_document=COMPANY),
                                        history(distinct_other_payers=29), P)
    assert hit.points == P.concentration_company_high_points


# ── TX03 Destino com recusas ───────────────────────────────────────────
# Quem filtra a CAUSA das recusas é o repository (testado na integração);
# aqui chega a contagem de pagadores distintos já filtrada.

def test_uma_vitima_so_nao_marca_o_destino():
    assert RejectedDestination().evaluate(make_pix(), history(rejected=1), P) is None


def test_dois_pagadores_recusados_marcam_o_destino_com_peso_limitado():
    for payers in (2, 10):
        hit = RejectedDestination().evaluate(make_pix(), history(rejected=payers), P)
        assert hit.points == P.rejected_destination_points


# ── TX04 Valor fora do perfil ──────────────────────────────────────────

def test_ate_o_dobro_do_maior_pix_e_normal():
    assert OutOfProfileAmount().evaluate(make_pix(amount_cents=20000), history(*known_payer()), P) is None


def test_mais_que_o_dobro_do_maior_pix_pontua():
    hit = OutOfProfileAmount().evaluate(make_pix(amount_cents=20001), history(*known_payer()), P)
    assert hit.points == P.profile_high_points


def test_mais_que_cinco_vezes_o_maior_pix_pontua_mais():
    hit = OutOfProfileAmount().evaluate(make_pix(amount_cents=50001), history(*known_payer()), P)
    assert hit.points == P.profile_extreme_points


def test_compara_com_o_maior_e_nao_com_a_media():
    # O aluguel de R$ 1.500 uma vez, e Pix de R$ 100 o resto do tempo: um
    # novo aluguel não é "fora do perfil", mesmo sendo 15x a média.
    rent = past(minutes_ago=60 * 24 * 30, amount_cents=150000)
    assert OutOfProfileAmount().evaluate(make_pix(amount_cents=150000),
                                         history(*known_payer(), rent), P) is None


def test_sem_perfil_so_valor_alto_pesa():
    assert OutOfProfileAmount().evaluate(make_pix(amount_cents=500000), history(), P) is None
    assert OutOfProfileAmount().evaluate(make_pix(amount_cents=500001), history(), P).points == \
        P.no_profile_high_amount_points


# ── TX05 Soma do dia ───────────────────────────────────────────────────

def month_of_small_pix() -> list:
    return [past(minutes_ago=60 * 24 * day + 60, amount_cents=10000) for day in range(2, 30)]


def test_soma_do_dia_muito_acima_da_media_pontua():
    today = [past(minutes_ago=60 * i, amount_cents=60000) for i in range(1, 4)]
    hit = UnusualDailySum().evaluate(make_pix(amount_cents=60000), history(*month_of_small_pix(), *today), P)
    assert hit.evidence["day_total_cents"] == 240000


def test_um_pix_grande_sozinho_e_caso_do_tx04_e_nao_da_soma_do_dia():
    assert UnusualDailySum().evaluate(make_pix(amount_cents=900000), history(*month_of_small_pix()), P) is None


def test_soma_do_dia_abaixo_do_piso_nao_pontua():
    assert UnusualDailySum().evaluate(make_pix(amount_cents=150000), history(*month_of_small_pix()), P) is None


def test_soma_do_dia_precisa_de_uma_semana_de_historico():
    assert UnusualDailySum().evaluate(make_pix(amount_cents=900000), history(*known_payer(5)), P) is None


# ── TX06 Fracionamento ─────────────────────────────────────────────────

def test_terceiro_pix_logo_abaixo_de_200_reais_na_hora():
    pieces = [past(minutes_ago=10 * (i + 1), amount_cents=19500) for i in range(2)]
    hit = Structuring().evaluate(make_pix(amount_cents=19900), history(*pieces), P)
    assert hit.evidence == {"pix_in_band": 3, "limit_cents": 20000, "window_minutes": 60}


def test_dois_pix_na_faixa_ainda_nao_e_fracionamento():
    pieces = [past(minutes_ago=10, amount_cents=19500)]
    assert Structuring().evaluate(make_pix(amount_cents=19900), history(*pieces), P) is None


def test_valor_fora_da_faixa_nao_e_fracionamento():
    pieces = [past(minutes_ago=10 * (i + 1), amount_cents=19500) for i in range(5)]
    assert Structuring().evaluate(make_pix(amount_cents=17000), history(*pieces), P) is None


# ── TX07 Limite noturno ────────────────────────────────────────────────

NIGHT = NOW.replace(hour=22, minute=15)


def test_pix_noturno_acima_de_1000_reais_e_piso_de_2fa():
    hit = NightLimit().evaluate(make_pix(amount_cents=100001, transaction_date=NIGHT), history(), P)
    assert hit.effect == FORCE_TWO_FACTOR
    assert hit.points == P.night_points


def test_pix_noturno_de_1000_reais_cabe_no_limite():
    assert NightLimit().evaluate(make_pix(amount_cents=100000, transaction_date=NIGHT), history(), P) is None


def test_limite_noturno_soma_a_noite_inteira():
    earlier = past(transaction_date=NIGHT - timedelta(hours=1), amount_cents=70000)   # 21h15, mesma noite
    hit = NightLimit().evaluate(make_pix(amount_cents=40000, transaction_date=NIGHT), history(earlier), P)
    assert hit.evidence["night_total_cents"] == 110000


def test_limite_noturno_nao_soma_o_que_saiu_de_dia():
    afternoon = past(transaction_date=NIGHT - timedelta(hours=3), amount_cents=70000)   # 19h15
    assert NightLimit().evaluate(make_pix(amount_cents=40000, transaction_date=NIGHT), history(afternoon), P) is None


def test_limite_noturno_nao_conta_o_que_foi_recusado():
    earlier = past(transaction_date=NIGHT - timedelta(hours=1), amount_cents=70000, status=REJECTED)
    assert NightLimit().evaluate(make_pix(amount_cents=40000, transaction_date=NIGHT), history(earlier), P) is None


def test_limite_noturno_vale_so_para_pessoa_fisica():
    company = make_pix(amount_cents=500000, transaction_date=NIGHT, source_document="12345678000195")
    assert NightLimit().evaluate(company, history(), P) is None


def test_janela_noturna_atravessa_a_meia_noite():
    after_midnight = NOW.replace(hour=1)
    start = night_window_start(after_midnight, P)
    assert start == (after_midnight - timedelta(days=1)).replace(hour=20)
    assert night_window_start(NOW, P) is None   # 14h


# ── TX08 Primeiro Pix para o recebedor ─────────────────────────────────

def test_primeiro_pix_alto_para_recebedor_novo():
    assert FirstPaymentToPayee().evaluate(make_pix(amount_cents=100000, destination_document="11122233344"),
                                          history(*known_payer()), P) is not None


def test_primeiro_pix_nao_conta_para_quem_o_motor_nunca_viu():
    assert FirstPaymentToPayee().evaluate(make_pix(amount_cents=100000), history(), P) is None


# ── Confiança ──────────────────────────────────────────────────────────

def test_recebedor_recorrente_desconta():
    hit = RecurringPayee().evaluate(make_pix(), history(*long_relationship()), P)
    assert hit.points == P.recurring_payee_points


def test_furo_tres_dias_seguidos_ainda_e_relacionamento_novo():
    # Decisão do time: menos de 30 dias desde o primeiro Pix aprovado = ainda é novo.
    assert RecurringPayee().evaluate(make_pix(), history(*known_payer(3)), P) is None


def test_relacionamento_com_29_dias_ainda_e_novo_e_com_30_ja_vale():
    young = [past(minutes_ago=60 * 24 * d) for d in (1, 15, 29)]
    mature = [past(minutes_ago=60 * 24 * d) for d in (1, 15, 30)]
    assert RecurringPayee().evaluate(make_pix(), history(*young), P) is None
    assert RecurringPayee().evaluate(make_pix(), history(*mature), P).points == P.recurring_payee_points


def test_recebedor_pago_em_dois_dias_ainda_nao_e_recorrente():
    assert RecurringPayee().evaluate(make_pix(), history(*known_payer(2)), P) is None


def test_furo_aquecimento_tres_pix_na_mesma_tarde_nao_e_recorrencia():
    warming = [past(minutes_ago=10 * (i + 1)) for i in range(5)]
    assert RecurringPayee().evaluate(make_pix(), history(*warming), P) is None


def test_recorrencia_so_conta_pix_aprovado():
    asked = known_payer(3, status=TWO_FACTOR_REQUIRED)
    assert RecurringPayee().evaluate(make_pix(), history(*asked), P) is None


def test_mesma_titularidade_desconta():
    assert OwnAccount().evaluate(make_pix(destination_document=PAYER), history(), P).points == P.own_account_points


# ── TR01 materialidade (decisão do time: 5x, a mesma régua do TX04) ─────
# Os casos da tabela que o time usou para escolher o número.

def rent_history(amount: int) -> list:
    return [past(minutes_ago=60 * 24 * 30 * month, amount_cents=amount) for month in (1, 2, 3)]


def recurring_effect(current: int, previous: int) -> int:
    hit = RecurringPayee().evaluate(make_pix(amount_cents=current), history(*rent_history(previous)), P)
    return hit.points


def test_legitimo_aluguel_com_reajuste_mantem_o_desconto():
    assert recurring_effect(165000, 150000) == P.recurring_payee_points


def test_legitimo_restante_do_empreiteiro_mantem_o_desconto():
    assert recurring_effect(70000, 30000) == P.recurring_payee_points


def test_legitimo_compra_maior_no_mercado_de_sempre_mantem_o_desconto():
    assert recurring_effect(30000, 10000) == P.recurring_payee_points


def test_exatamente_5x_ainda_mantem_o_desconto():
    assert recurring_effect(50000, 10000) == P.recurring_payee_points


def test_emprestimo_ao_amigo_de_sempre_perde_o_desconto():
    assert recurring_effect(200000, 5000) == 0


def test_furo_aquecimento_com_1_real_nao_avaliza_5000():
    assert recurring_effect(500000, 100) == 0


def test_furo_aquecimento_com_600_reais_nao_avaliza_5000():
    hit = RecurringPayee().evaluate(make_pix(amount_cents=500000), history(*rent_history(60000)), P)
    assert hit.points == 0
    assert hit.evidence["ratio"] == 8.33
