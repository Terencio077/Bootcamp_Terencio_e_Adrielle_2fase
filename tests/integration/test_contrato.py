"""O contrato da API: formato, idempotência, gravação e erros."""

import requests

from utils.pix_utils import BASE_TIME, build_pix, get_pix, new_account, new_payer, post_pix, send
from utils.settings import ANTIFRAUD_URL

EXAMPLE = {
    "amount": 150000,
    "transaction_date": "2026-10-17T22:15:00-03:00",
    "source_account": {"branch": "0001", "account_number": "88213",
                       "opening_date": "2025-03-02T10:00:00-03:00",
                       "owner": {"document_number": "123.456.789-09"}},
    "destination_account": {"participant": "60701190", "branch": "3675", "account_number": "10442",
                            "opening_date": "2026-10-10T09:00:00-03:00",
                            "owner": {"document_number": "987.654.321-00"}},
    "source": {"device_id": "dvc-9f2c71a8", "channel": "app", "ip": "198.51.100.23",
               "geolocation": {"latitude": -23.56, "longitude": -46.65}},
}


def a_pix(**overrides) -> dict:
    payload = build_pix(new_payer(), new_account(), 5000, BASE_TIME)
    payload.update(overrides)
    return payload


def test_resposta_tem_key_status_e_metadata():
    analysis = send(a_pix())
    assert set(analysis) == {"key", "status", "metadata"}
    assert len(analysis["key"]) == 36
    assert analysis["status"] in ("approved", "rejected", "two_factor_required")


def test_metadata_explica_a_decisao():
    metadata = send(a_pix())["metadata"]
    assert set(metadata) >= {"pix_id", "decision_reason", "scores", "rules_triggered", "rules_version",
                             "decision_latency_ms"}
    assert set(metadata["scores"]) == {"identity", "transaction"}


def test_get_devolve_exatamente_a_analise_gravada():
    payload = a_pix()
    created = send(payload)
    found = get_pix(payload["id"])
    assert found.status_code == 200
    assert found.json() == created


def test_mesmo_pix_repetido_devolve_a_mesma_analise_sem_reanalisar():
    payload = a_pix()
    first = send(payload)
    again = post_pix(payload)
    assert again.status_code == 200
    assert again.json() == first


def test_mesmo_id_com_outro_corpo_e_conflito_e_mantem_a_original():
    payload = a_pix()
    original = send(payload)
    changed = dict(payload, amount=payload["amount"] + 1)
    response = post_pix(changed)
    assert response.status_code == 409
    assert response.json()["code"] == "QIT003009"
    assert get_pix(payload["id"]).json() == original


def test_pix_inexistente_e_404():
    response = get_pix("pix-que-nunca-chegou")
    assert response.status_code == 404
    assert response.json()["code"] == "QIT003004"


def test_campo_obrigatorio_faltando_e_400():
    payload = a_pix()
    del payload["amount"]
    response = post_pix(payload)
    assert response.status_code == 400
    assert response.json()["code"] == "QIT000001"


def test_valor_em_reais_com_virgula_e_400():
    response = post_pix(a_pix(amount=1500.50))
    assert response.status_code == 400


def test_campo_desconhecido_e_400():
    response = post_pix(a_pix(status="approved"))
    assert response.status_code == 400


def test_data_sem_fuso_e_422():
    response = post_pix(a_pix(transaction_date="2026-09-15T14:00:00"))
    assert response.status_code == 422
    assert response.json()["code"] == "QIT003022"


def test_data_de_abertura_sem_fuso_aponta_o_campo_certo():
    payload = a_pix()
    payload["destination_account"]["opening_date"] = "2020-01-10T10:00:00"
    response = post_pix(payload)
    assert response.status_code == 422
    assert "destination_account.opening_date" in response.json()["description"]


def test_horario_da_analise_sai_com_fuso():
    analysed_at = send(a_pix())["metadata"]["analysed_at"]
    assert analysed_at[-6] in "+-" and analysed_at[-3] == ":"


def test_geolocalizacao_e_opcional():
    payload = a_pix()
    payload["source"].pop("geolocation", None)
    assert post_pix(payload).status_code == 201


def test_documento_com_e_sem_pontuacao_e_a_mesma_pessoa():
    payer = new_payer()
    payee = new_account()
    send(build_pix(payer, payee, 5000, BASE_TIME))
    digits_only = dict(payer, owner={"document_number": payer["owner"]["document_number"]
                                     .replace(".", "").replace("-", "")})
    analysis = send(build_pix(digits_only, payee, 5000, BASE_TIME.replace(minute=30)))
    # Se fossem duas pessoas, o aparelho seria "novo" para o segundo pagador;
    # sendo a mesma, ele já foi observado no Pix anterior.
    device = next(hit for hit in analysis["metadata"]["rules_triggered"] if hit["rule"] == "ID01")
    assert device["evidence"]["device_state"] == "observed"


def test_sem_internal_token_e_403():
    response = requests.post(f"{ANTIFRAUD_URL}/pix/transaction", json=a_pix())
    assert response.status_code == 403


def test_exemplo_do_enunciado_pede_2fa():
    payload = dict(EXAMPLE, id=a_pix()["id"])
    # Documento do pagador próprio deste teste, para o histórico de outras
    # execuções não interferir.
    payload["source_account"] = dict(EXAMPLE["source_account"], owner={"document_number": new_payer()["owner"]
                                                                       ["document_number"]})
    payload["destination_account"] = dict(new_account(opening_date="2026-10-10T09:00:00-03:00"))
    analysis = send(payload)
    assert analysis["status"] == "two_factor_required"


def test_mesmo_pix_chegando_varias_vezes_ao_mesmo_tempo_gera_uma_analise_so():
    from concurrent.futures import ThreadPoolExecutor

    payload = a_pix()
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(post_pix, [payload] * 6))

    assert sorted(response.status_code for response in responses) == [200, 200, 200, 200, 200, 201]
    assert len({response.json()["key"] for response in responses}) == 1


def test_mesmo_id_com_corpos_diferentes_ao_mesmo_tempo_mantem_so_o_primeiro():
    # Pagadores diferentes no corpo: as chegadas NÃO dividem a trava do pagador,
    # e a duplicidade só aparece no UNIQUE(pix_id) do banco, durante o flush.
    from concurrent.futures import ThreadPoolExecutor

    pix_id = a_pix()["id"]
    payloads = [dict(a_pix(), id=pix_id) for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(post_pix, payloads))

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [201, 409, 409, 409, 409, 409]
    winner = next(response.json() for response in responses if response.status_code == 201)
    assert get_pix(pix_id).json() == winner
