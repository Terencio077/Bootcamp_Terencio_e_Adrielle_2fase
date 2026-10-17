"""Jornadas de ponta a ponta: o histórico é montado pela API e a decisão conferida.

Cada cenário é uma história que a apresentação conta, e cada um prova uma
escolha do motor:

• aluguel recorrente      -> confiança derruba a fricção (approved)
• aparelho novo           -> dúvida só sobre QUEM: 2FA resolve (two_factor_required)
• golpe                   -> dúvida sobre O QUÊ: 2FA não resolve (rejected)
• conta laranja           -> o destino denuncia o que nenhum pagador mostra
• rajada                  -> conta tentativas recusadas também
• viagem impossível       -> geolocalização
• fracionamento           -> quem conhece o limite e fica logo abaixo
• destino com recusa      -> o motor aprende com as próprias decisões
"""

from datetime import timedelta

from utils.pix_utils import (
    BASE_TIME,
    build_pix,
    new_account,
    new_payer,
    rules_of,
    send,
    warm_up_payer,
)


def test_aluguel_para_o_mesmo_recebedor_passa_sem_friccao():
    # Um cliente de verdade: Pix médios do dia a dia (até R$ 800) e, uma vez
    # por mês, o aluguel de R$ 1.500 para o mesmo dono do apartamento.
    payer = new_payer()
    market = new_account()
    start = BASE_TIME - timedelta(days=100)
    send(build_pix(payer, market, 10000, start))                 # primeiro Pix: aparelho fica confiável
    for day in range(1, 6):
        send(build_pix(payer, market, 80000, start + timedelta(days=day)))

    landlord = new_account()
    for month in (3, 2, 1):
        first_rents = send(build_pix(payer, landlord, 150000, BASE_TIME - timedelta(days=30 * month)))
        assert first_rents["status"] == "approved", first_rents

    rent = send(build_pix(payer, landlord, 150000, BASE_TIME))
    assert rent["status"] == "approved"
    assert "TR01" in rules_of(rent)
    assert rent["metadata"]["scores"] == {"identity": 0, "transaction": 0}


def test_aparelho_novo_pagando_quem_sempre_paga_pede_2fa():
    payer = new_payer()
    payee = warm_up_payer(payer)

    analysis = send(build_pix(payer, payee, 50000, BASE_TIME, device_id="dvc-celular-novo"))
    assert analysis["status"] == "two_factor_required"
    assert {"ID01", "ID02"} <= rules_of(analysis)
    assert analysis["metadata"]["scores"]["transaction"] == 0


def test_golpe_dono_da_conta_mandando_para_conta_nova_e_recusado():
    payer = new_payer()
    warm_up_payer(payer)
    mule = new_account(opening_date=(BASE_TIME - timedelta(days=2)).isoformat())

    analysis = send(build_pix(payer, mule, 300000, BASE_TIME))
    assert analysis["status"] == "rejected"
    assert analysis["metadata"]["scores"]["identity"] == 0
    assert {"TX01", "TX04", "TX08"} <= rules_of(analysis)


def test_conta_laranja_recebendo_de_muitos_pagadores():
    mule = new_account()
    statuses = []
    for minute in range(10):
        analysis = send(build_pix(new_payer(), mule, 9000, BASE_TIME + timedelta(minutes=minute)))
        statuses.append(analysis["status"])

    assert statuses[:4] == ["approved"] * 4
    assert statuses[4] == "two_factor_required"   # 5º pagador diferente na hora
    assert statuses[9] == "rejected"              # 10º: bloqueio


def test_rajada_do_mesmo_pagador():
    payer = new_payer()
    payee = warm_up_payer(payer)
    statuses = []
    for second in range(10):
        analysis = send(build_pix(payer, payee, 1500, BASE_TIME + timedelta(seconds=30 * second)))
        statuses.append(analysis["status"])

    assert statuses[:4] == ["approved"] * 4
    assert statuses[4] == "two_factor_required"
    assert statuses[9] == "rejected"


def test_viagem_impossivel_entre_dois_pix():
    payer = new_payer()
    payee = warm_up_payer(payer)
    send(build_pix(payer, payee, 5000, BASE_TIME, geolocation={"latitude": -23.55, "longitude": -46.63}))

    analysis = send(build_pix(payer, payee, 5000, BASE_TIME + timedelta(minutes=30),
                              geolocation={"latitude": -3.12, "longitude": -60.02}))
    assert analysis["status"] == "two_factor_required"
    assert "ID03" in rules_of(analysis)


def test_fracionamento_logo_abaixo_do_teto_de_aparelho_novo():
    payer = new_payer()
    warm_up_payer(payer)
    payee = new_account()   # recebedor novo: um recorrente descontaria a suspeita (TR01)
    for minute in (0, 10):
        send(build_pix(payer, payee, 19500, BASE_TIME + timedelta(minutes=minute)))

    analysis = send(build_pix(payer, payee, 19900, BASE_TIME + timedelta(minutes=20)))
    assert "TX06" in rules_of(analysis)
    assert analysis["status"] == "two_factor_required"


def test_destino_recusado_fica_marcado_para_os_proximos_pagadores():
    victim = new_payer()
    warm_up_payer(victim)
    mule = new_account(opening_date=(BASE_TIME - timedelta(days=2)).isoformat())
    assert send(build_pix(victim, mule, 300000, BASE_TIME))["status"] == "rejected"

    other = send(build_pix(new_payer(), mule, 5000, BASE_TIME + timedelta(hours=2)))
    assert "TX03" in rules_of(other)


def test_pix_noturno_acima_do_limite_pede_2fa():
    payer = new_payer()
    payee = warm_up_payer(payer)
    night = BASE_TIME.replace(hour=22, minute=15)

    analysis = send(build_pix(payer, payee, 150000, night))
    assert "TX07" in rules_of(analysis)
    assert analysis["status"] == "two_factor_required"
