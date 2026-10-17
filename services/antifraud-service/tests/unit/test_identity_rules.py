"""Eixo identidade: cada regra dispara no limite e fica quieta logo abaixo dele."""

from builders import NOW, history, known_payer, make_pix, past

from rules import DEFAULT_PARAMETERS as P
from rules import REJECTED, TWO_FACTOR_REQUIRED
from rules.identity_rules import ImpossibleTravel, NewChannel, NewDevice, UnusualDawn, UntrustedDeviceLimit, Velocity
from rules.rule import FORCE_TWO_FACTOR, REJECT


# ── ID01 Dispositivo novo ──────────────────────────────────────────────

def test_aparelho_conhecido_nao_pontua():
    assert NewDevice().evaluate(make_pix(), history(*known_payer()), P) is None


def test_aparelho_novo_para_quem_tem_historico_pontua_cheio():
    hit = NewDevice().evaluate(make_pix(device_id="device-b"), history(*known_payer()), P)
    assert hit.points == P.new_device_points
    assert hit.evidence["known_devices"] == 1


def test_primeiro_pix_do_pagador_pontua_pouco_para_nao_punir_o_cold_start():
    hit = NewDevice().evaluate(make_pix(), history(), P)
    assert hit.points == P.first_seen_payer_device_points


# ── ID02 Limite de dispositivo não cadastrado ──────────────────────────

def test_aparelho_nao_confirmado_ate_200_reais_passa():
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=20000), history(), P) is None


def test_aparelho_nao_confirmado_acima_de_200_reais_exige_2fa():
    hit = UntrustedDeviceLimit().evaluate(make_pix(amount_cents=20001), history(), P)
    assert hit.effect == FORCE_TWO_FACTOR


def test_aparelho_nao_confirmado_soma_do_dia_acima_de_1000_reais_exige_2fa():
    # Cinco Pix de R$ 200 no mesmo aparelho novo já somam o teto do dia.
    earlier = [past(minutes_ago=30 * (i + 1), amount_cents=20000, device_id="device-new", status=TWO_FACTOR_REQUIRED)
               for i in range(5)]
    hit = UntrustedDeviceLimit().evaluate(make_pix(amount_cents=100, device_id="device-new"), history(*earlier), P)
    assert hit.evidence["device_24h_total_cents"] == 100100


def test_aparelho_vira_confiavel_depois_de_um_pix_aprovado():
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=500000), history(past()), P) is None


def test_pix_recusado_nao_torna_o_aparelho_confiavel_nem_conta_no_teto():
    rejected = past(device_id="device-x", status=REJECTED, amount_cents=90000, minutes_ago=10)
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=15000, device_id="device-x"),
                                           history(rejected), P) is None
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=25000, device_id="device-x"),
                                           history(rejected), P) is not None


# ── ID03 Viagem impossível ─────────────────────────────────────────────

SAO_PAULO = (-23.55, -46.63)
MANAUS = (-3.12, -60.02)
CAMPINAS = (-22.90, -47.06)


def test_sao_paulo_e_manaus_em_30_minutos_e_impossivel():
    before = past(minutes_ago=30, latitude=SAO_PAULO[0], longitude=SAO_PAULO[1])
    hit = ImpossibleTravel().evaluate(make_pix(latitude=MANAUS[0], longitude=MANAUS[1]), history(before), P)
    assert hit.points == P.impossible_travel_points
    assert hit.evidence["distance_km"] > 2500


def test_sao_paulo_e_manaus_em_um_dia_e_possivel():
    before = past(minutes_ago=60 * 24, latitude=SAO_PAULO[0], longitude=SAO_PAULO[1])
    assert ImpossibleTravel().evaluate(make_pix(latitude=MANAUS[0], longitude=MANAUS[1]), history(before), P) is None


def test_distancia_curta_e_ruido_de_gps_mesmo_em_pouco_tempo():
    before = past(minutes_ago=1, latitude=SAO_PAULO[0], longitude=SAO_PAULO[1])
    assert ImpossibleTravel().evaluate(make_pix(latitude=CAMPINAS[0], longitude=CAMPINAS[1]),
                                       history(before), P) is None


def test_sem_geolocalizacao_a_regra_nao_roda():
    before = past(minutes_ago=30, latitude=SAO_PAULO[0], longitude=SAO_PAULO[1])
    assert ImpossibleTravel().evaluate(make_pix(), history(before), P) is None


# ── ID04 Rajada ────────────────────────────────────────────────────────

def burst(count: int) -> list:
    return [past(minutes_ago=i + 1) for i in range(count)]


def test_quatro_pix_em_dez_minutos_nao_pontua():
    assert Velocity().evaluate(make_pix(), history(*burst(3)), P) is None


def test_quinto_pix_em_dez_minutos_pontua():
    assert Velocity().evaluate(make_pix(), history(*burst(4)), P).points == P.velocity_points


def test_decimo_pix_em_dez_minutos_bloqueia():
    assert Velocity().evaluate(make_pix(), history(*burst(9)), P).effect == REJECT


def test_rajada_conta_tambem_as_tentativas_recusadas():
    attempts = [past(minutes_ago=i + 1, status=REJECTED) for i in range(4)]
    assert Velocity().evaluate(make_pix(), history(*attempts), P) is not None


def test_pix_fora_da_janela_nao_entra_na_rajada():
    old = [past(minutes_ago=11 + i) for i in range(20)]
    assert Velocity().evaluate(make_pix(), history(*old), P) is None


# ── ID05 Canal novo e ID06 Madrugada ───────────────────────────────────

def test_canal_novo_para_quem_sempre_usou_o_app():
    assert NewChannel().evaluate(make_pix(channel="internet_banking"), history(*known_payer()), P) is not None


def test_canal_novo_sem_historico_suficiente_nao_pontua():
    assert NewChannel().evaluate(make_pix(channel="internet_banking"), history(*known_payer(4)), P) is None


def test_madrugada_para_quem_nunca_faz_pix_de_madrugada():
    dawn = NOW.replace(hour=3)
    assert UnusualDawn().evaluate(make_pix(transaction_date=dawn), history(*known_payer(10)), P) is not None


def test_madrugada_para_quem_tem_o_habito_nao_pontua():
    habit = known_payer(9) + [past(minutes_ago=60 * 24 * 20 + 11 * 60)]  # 03h da manhã, 20 dias atrás
    dawn = NOW.replace(hour=3)
    assert UnusualDawn().evaluate(make_pix(transaction_date=dawn), history(*habit), P) is None
