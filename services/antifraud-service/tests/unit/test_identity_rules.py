"""Eixo identidade: cada regra dispara no limite e fica quieta logo abaixo dele.

Cada brecha corrigida tem dois testes lado a lado: o que reproduz o furo
(e agora falha para o fraudador) e o caso legítimo parecido com ele (que
continua passando sem fricção desnecessária).
"""

from datetime import timedelta

from builders import NOW, history, known_payer, make_pix, past

from rules import DEFAULT_PARAMETERS as P
from rules import REJECTED, TWO_FACTOR_REQUIRED
from rules.device import NEW, OBSERVED, RECURRING, TRUSTED, device_trust
from rules.identity_rules import (
    ImpossibleTravel,
    NewChannel,
    UnusualDawn,
    UntrustedDevice,
    UntrustedDeviceLimit,
    Velocity,
)
from rules.rule import FORCE_TWO_FACTOR


# ── Estados do aparelho ────────────────────────────────────────────────

def test_aparelho_nunca_visto_e_novo():
    assert device_trust("device-z", NOW, history(*known_payer()), P) == NEW


def test_aparelho_com_pix_aprovado_ha_24h_e_confiavel():
    assert device_trust("device-a", NOW, history(past(minutes_ago=24 * 60)), P) == TRUSTED


def test_pix_aprovado_ha_10_minutos_ainda_nao_confirma_o_aparelho():
    assert device_trust("device-a", NOW, history(past(minutes_ago=10)), P) == OBSERVED


def test_tentativa_que_pediu_2fa_nunca_confirma_o_aparelho():
    attempts = [past(minutes_ago=60 * 24 * day, status=TWO_FACTOR_REQUIRED) for day in (1, 2)]
    assert device_trust("device-a", NOW, history(*attempts), P) == OBSERVED


def test_uso_em_varios_dias_por_uma_semana_reduz_suspeita_mas_nao_confirma():
    uses = [past(minutes_ago=60 * 24 * day, status=TWO_FACTOR_REQUIRED) for day in (1, 4, 8)]
    assert device_trust("device-a", NOW, history(*uses), P) == RECURRING


def test_uso_recorrente_com_uma_recusa_nao_conta():
    uses = [past(minutes_ago=60 * 24 * day, status=TWO_FACTOR_REQUIRED) for day in (1, 4)]
    uses.append(past(minutes_ago=60 * 24 * 8, status=REJECTED))
    assert device_trust("device-a", NOW, history(*uses), P) == OBSERVED


def test_tres_dias_seguidos_nao_bastam_sem_uma_semana():
    uses = [past(minutes_ago=60 * 24 * day, status=TWO_FACTOR_REQUIRED) for day in (1, 2, 3)]
    assert device_trust("device-a", NOW, history(*uses), P) == OBSERVED


# ── ID01 Dispositivo não confiável ─────────────────────────────────────

def test_aparelho_confiavel_nao_pontua():
    assert UntrustedDevice().evaluate(make_pix(), history(*known_payer()), P) is None


def test_aparelho_novo_para_quem_tem_aparelho_confiavel_pontua_cheio():
    hit = UntrustedDevice().evaluate(make_pix(device_id="device-b"), history(*known_payer()), P)
    assert hit.points == P.new_device_points


def test_furo_segundo_pix_do_aparelho_novo_logo_apos_o_2fa_continua_suspeito():
    # O furo que o revisor reproduziu: celular novo pede 2FA; 11 minutos
    # depois, um segundo Pix do mesmo celular era aprovado sem prova nenhuma.
    first_try = past(minutes_ago=11, device_id="device-b", amount_cents=15000, status=TWO_FACTOR_REQUIRED)
    hit = UntrustedDevice().evaluate(make_pix(device_id="device-b", amount_cents=15000),
                                     history(*known_payer(), first_try), P)
    assert hit.points == P.new_device_points


def test_legitimo_celular_novo_usado_ha_uma_semana_pontua_menos():
    uses = [past(minutes_ago=60 * 24 * day, device_id="device-b", status=TWO_FACTOR_REQUIRED) for day in (1, 4, 8)]
    hit = UntrustedDevice().evaluate(make_pix(device_id="device-b"), history(*known_payer(), *uses), P)
    assert hit.points == P.recurring_device_points


def test_primeiro_contato_do_pagador_pontua_pouco_para_nao_punir_o_cold_start():
    assert UntrustedDevice().evaluate(make_pix(), history(), P).points == P.first_seen_payer_device_points


def test_segundo_pix_do_primeiro_contato_continua_como_primeiro_contato():
    hit = UntrustedDevice().evaluate(make_pix(), history(past(minutes_ago=10)), P)
    assert hit.points == P.first_seen_payer_device_points


# ── ID02 Limite de dispositivo não cadastrado ──────────────────────────

def test_aparelho_nao_confirmado_ate_200_reais_passa():
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=20000), history(), P) is None


def test_aparelho_nao_confirmado_acima_de_200_reais_exige_2fa():
    hit = UntrustedDeviceLimit().evaluate(make_pix(amount_cents=20001), history(), P)
    assert hit.effect == FORCE_TWO_FACTOR


def test_aparelho_nao_confirmado_soma_do_dia_acima_de_1000_reais_exige_2fa():
    earlier = [past(minutes_ago=30 * (i + 1), amount_cents=20000, device_id="device-new", status=TWO_FACTOR_REQUIRED)
               for i in range(5)]
    hit = UntrustedDeviceLimit().evaluate(make_pix(amount_cents=100, device_id="device-new"), history(*earlier), P)
    assert hit.evidence["device_24h_total_cents"] == 100100


def test_furo_pix_de_50_aprovado_nao_libera_500_logo_em_seguida():
    small = past(minutes_ago=10, amount_cents=5000)
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=50000), history(small), P) is not None


def test_legitimo_aparelho_confirmado_ha_um_dia_libera_valor_alto():
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=500000), history(past()), P) is None


def test_uso_recorrente_nao_escapa_do_teto_regulatorio():
    uses = [past(minutes_ago=60 * 24 * day, status=TWO_FACTOR_REQUIRED) for day in (1, 4, 8)]
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=50000), history(*uses), P) is not None


def test_pix_recusado_nao_conta_no_teto_do_dia():
    rejected = past(device_id="device-x", status=REJECTED, amount_cents=90000, minutes_ago=10)
    assert UntrustedDeviceLimit().evaluate(make_pix(amount_cents=15000, device_id="device-x"),
                                           history(rejected), P) is None


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


def test_distancia_curta_e_erro_de_geolocalizacao_mesmo_em_pouco_tempo():
    before = past(minutes_ago=1, latitude=SAO_PAULO[0], longitude=SAO_PAULO[1])
    assert ImpossibleTravel().evaluate(make_pix(latitude=CAMPINAS[0], longitude=CAMPINAS[1]),
                                       history(before), P) is None


def test_sem_geolocalizacao_a_regra_nao_roda():
    before = past(minutes_ago=30, latitude=SAO_PAULO[0], longitude=SAO_PAULO[1])
    assert ImpossibleTravel().evaluate(make_pix(), history(before), P) is None


# ── ID04 Rajada ────────────────────────────────────────────────────────

def burst(count: int, **overrides) -> list:
    return [past(minutes_ago=i + 1, **overrides) for i in range(count)]


def test_quatro_pix_em_dez_minutos_nao_pontua():
    assert Velocity().evaluate(make_pix(), history(*burst(3)), P) is None


def test_quinto_pix_em_dez_minutos_pontua():
    assert Velocity().evaluate(make_pix(), history(*burst(4)), P).points == P.velocity_points


def test_decimo_pix_pontua_mais_mas_nao_bloqueia_sozinho():
    hit = Velocity().evaluate(make_pix(), history(*burst(9)), P)
    assert hit.points == P.velocity_high_points
    assert hit.effect == "SCORE"


def test_rajada_conta_tambem_as_tentativas_recusadas():
    assert Velocity().evaluate(make_pix(), history(*burst(4, status=REJECTED)), P) is not None


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
    habit = known_payer(9) + [past(transaction_date=NOW.replace(hour=3) - timedelta(days=20))]
    dawn = NOW.replace(hour=3)
    assert UnusualDawn().evaluate(make_pix(transaction_date=dawn), history(*habit), P) is None
