from concurrent.futures import ThreadPoolExecutor

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
    payer = new_payer()
    market = new_account()
    start = BASE_TIME - timedelta(days=100)
    send(build_pix(payer, market, 10000, start))
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


def test_conta_de_cpf_nova_recebendo_de_muitos_pagadores():
    young = new_account(opening_date=(BASE_TIME - timedelta(days=3)).isoformat())
    statuses = []
    for minute in range(10):
        analysis = send(build_pix(new_payer(), young, 9000, BASE_TIME + timedelta(minutes=minute)))
        statuses.append(analysis["status"])

    assert statuses[:4] == ["approved"] * 4
    assert statuses[4] == "two_factor_required"
    assert statuses[9] == "rejected"


def test_legitimo_comercio_antigo_com_o_mesmo_movimento_aprova_todos():
    shop = new_account(document="12.345.678/0001-95")
    statuses = [send(build_pix(new_payer(), shop, 3500, BASE_TIME + timedelta(minutes=minute)))["status"]
                for minute in range(10)]
    assert statuses == ["approved"] * 10


def test_legitimo_marmita_no_cpf_que_lota_todo_almoco_aprova_todos():
    seller = new_account()
    for days_ago in (7, 3):
        for minute in range(12):
            send(build_pix(new_payer(), seller, 2500, BASE_TIME - timedelta(days=days_ago, minutes=-minute)))
    statuses = [send(build_pix(new_payer(), seller, 2500, BASE_TIME + timedelta(minutes=minute)))["status"]
                for minute in range(12)]
    assert statuses == ["approved"] * 12


def test_rajada_do_mesmo_pagador_pede_2fa_sem_recusar_sozinha():
    payer = new_payer()
    payee = warm_up_payer(payer)
    statuses = []
    for second in range(10):
        analysis = send(build_pix(payer, payee, 1500, BASE_TIME + timedelta(seconds=30 * second)))
        statuses.append(analysis["status"])

    assert statuses[:4] == ["approved"] * 4
    assert statuses[4] == "two_factor_required"
    assert statuses[9] == "two_factor_required"


def test_segundo_pix_do_celular_novo_logo_apos_o_2fa_continua_pedindo_2fa():
    payer = new_payer()
    payee = warm_up_payer(payer)
    first = send(build_pix(payer, payee, 15000, BASE_TIME, device_id="dvc-celular-novo"))
    second = send(build_pix(payer, payee, 15000, BASE_TIME + timedelta(minutes=11), device_id="dvc-celular-novo"))
    assert first["status"] == "two_factor_required"
    assert second["status"] == "two_factor_required"


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
    payee = new_account()
    for minute in (0, 10):
        send(build_pix(payer, payee, 19500, BASE_TIME + timedelta(minutes=minute)))

    analysis = send(build_pix(payer, payee, 19900, BASE_TIME + timedelta(minutes=20)))
    assert "TX06" in rules_of(analysis)
    assert analysis["status"] == "two_factor_required"


def reject_for_transaction_risk(destination: dict, when) -> None:
    victim = new_payer()
    warm_up_payer(victim, start=when)
    assert send(build_pix(victim, destination, 300000, when))["status"] == "rejected"


def reject_for_payer_risk(destination: dict, when) -> None:
    payer = new_payer()
    payee = warm_up_payer(payer, start=when)
    send(build_pix(payer, payee, 5000, when - timedelta(minutes=30), geolocation={"latitude": -23.55, "longitude": -46.63}))
    analysis = send(build_pix(payer, destination, 5000, when, device_id="dvc-estranho", channel="internet_banking",
                              geolocation={"latitude": -3.12, "longitude": -60.02}))
    assert analysis["status"] == "rejected"
    assert analysis["metadata"]["scores"]["transaction"] < 60


def test_destino_recusado_por_risco_da_transacao_fica_marcado():
    mule = new_account(opening_date=(BASE_TIME - timedelta(days=2)).isoformat())
    reject_for_transaction_risk(mule, BASE_TIME)
    reject_for_transaction_risk(mule, BASE_TIME + timedelta(hours=1))

    other = send(build_pix(new_payer(), mule, 5000, BASE_TIME + timedelta(hours=2)))
    assert "TX03" in rules_of(other)


def test_uma_vitima_so_nao_marca_o_destino():
    mule = new_account(opening_date=(BASE_TIME - timedelta(days=2)).isoformat())
    reject_for_transaction_risk(mule, BASE_TIME)

    other = send(build_pix(new_payer(), mule, 5000, BASE_TIME + timedelta(hours=2)))
    assert "TX03" not in rules_of(other)


def test_legitimo_recusa_causada_pelo_pagador_nao_mancha_o_recebedor():
    shop = new_account()
    reject_for_payer_risk(shop, BASE_TIME)
    reject_for_payer_risk(shop, BASE_TIME + timedelta(hours=1))

    other = send(build_pix(new_payer(), shop, 5000, BASE_TIME + timedelta(hours=2)))
    assert "TX03" not in rules_of(other)


def tenant_with_rent_history():
    payer = new_payer()
    warm_up_payer(payer)
    landlord = new_account()
    for days_ago in (33, 20, 2):
        rent = send(build_pix(payer, landlord, 150000, BASE_TIME - timedelta(days=days_ago)))
        assert rent["status"] == "approved", rent
    return payer, landlord


def test_pix_noturno_acima_do_limite_pede_2fa_mesmo_para_recebedor_recorrente():
    payer, landlord = tenant_with_rent_history()
    analysis = send(build_pix(payer, landlord, 150000, BASE_TIME.replace(hour=22, minute=15)))
    assert {"TX07", "TR01"} <= rules_of(analysis)
    assert analysis["status"] == "two_factor_required"


def test_legitimo_pix_noturno_dentro_do_limite_para_recebedor_recorrente_aprova():
    payer, landlord = tenant_with_rent_history()
    analysis = send(build_pix(payer, landlord, 90000, BASE_TIME.replace(hour=22, minute=15)))
    assert analysis["status"] == "approved"


def test_recorrencia_pequena_nao_avaliza_valor_muito_maior():
    payer = new_payer()
    warm_up_payer(payer)
    target = new_account()
    for days_ago in (40, 20, 5):
        send(build_pix(payer, target, 100, BASE_TIME - timedelta(days=days_ago)))
    analysis = send(build_pix(payer, target, 500000, BASE_TIME))
    recurring = next(hit for hit in analysis["metadata"]["rules_triggered"] if hit["rule"] == "TR01")
    assert recurring["points"] == 0
    assert analysis["status"] != "approved"


def test_aquecimento_em_dias_seguidos_nao_vira_recorrencia():
    payer = new_payer()
    warm_up_payer(payer)
    target = new_account(opening_date=(BASE_TIME - timedelta(days=25)).isoformat())
    for days_ago in (3, 2, 1):
        send(build_pix(payer, target, 60000, BASE_TIME - timedelta(days=days_ago)))
    analysis = send(build_pix(payer, target, 250000, BASE_TIME))
    assert "TR01" not in rules_of(analysis)
    assert analysis["status"] != "approved"


def test_pix_simultaneos_do_mesmo_pagador_enxergam_uns_aos_outros():
    payer = new_payer()
    payee = warm_up_payer(payer)
    payloads = [build_pix(payer, payee, 1500, BASE_TIME) for _ in range(12)]

    with ThreadPoolExecutor(max_workers=12) as pool:
        analyses = list(pool.map(send, payloads))

    counts = sorted(hit["evidence"]["pix_in_window"] for analysis in analyses
                    for hit in analysis["metadata"]["rules_triggered"] if hit["rule"] == "ID04")
    assert counts == list(range(5, 13))
