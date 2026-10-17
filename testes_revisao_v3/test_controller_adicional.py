"""Controller real + PixRepository.save real, com falhas de banco simuladas.

Estes casos reproduzem o ponto em que o banco reporta duplicidade;
não substituem duas requisições concorrentes contra PostgreSQL.
"""

from unittest.mock import Mock

import pytest
from sqlalchemy.exc import IntegrityError


# AJUSTE (time + Claudio, 17/10): o controller passou a reler a análise também
# DEPOIS de adquirir as travas, como a própria seção "Falha 1" do README deste
# pacote recomenda. São três consultas no caminho (início, após a trava, após o
# erro), então a simulação ganhou um None a mais. Nenhuma asserção mudou.


def duplicate_error():
    return IntegrityError("INSERT INTO pix_transactions ...", {}, RuntimeError("duplicate pix_id"))


def test_duplicidade_detectada_no_flush_devolve_analise_existente(controller, payload):
    saved = {"key": "original-key", "status": "approved", "metadata": {"pix_id": payload["id"]}}
    controller.previous_analysis.side_effect = [None, None, saved]
    # save() real chama flush(): a violação ocorre ANTES do commit.
    controller.session.flush.side_effect = duplicate_error()
    result, created = controller.create(payload)
    assert result == saved
    assert created is False
    controller.session.rollback.assert_called_once()
    controller.session.commit.assert_not_called()


def test_duplicidade_no_flush_com_corpo_diferente_gera_conflito(controller, payload, service_modules):
    controller.previous_analysis.side_effect = [None, None, service_modules.PixIdConflict(payload["id"])]
    controller.session.flush.side_effect = duplicate_error()
    with pytest.raises(service_modules.PixIdConflict) as caught:
        controller.create(payload)
    assert caught.value.http_status == 409
    controller.session.rollback.assert_called_once()


def test_duplicidade_detectada_no_commit_preserva_tratamento_existente(controller, payload):
    saved = {"key": "original-key", "status": "approved", "metadata": {"pix_id": payload["id"]}}
    controller.previous_analysis.side_effect = [None, None, saved]
    controller.session.commit.side_effect = duplicate_error()
    result, created = controller.create(payload)
    assert result == saved
    assert created is False
    controller.session.rollback.assert_called_once()


@pytest.mark.parametrize("field", [
    "transaction_date", "source_account.opening_date", "destination_account.opening_date",
])
def test_data_sem_fuso_aponta_exatamente_o_campo_invalido(payload, service_modules, field):
    parts = field.split(".")
    target = payload
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = "2026-10-15T14:00:00"
    with pytest.raises(service_modules.InvalidDateTime) as caught:
        service_modules.to_pix_request(payload)
    assert caught.value.http_status == 422
    assert f"The {field} " in caught.value.description


def test_falha_na_leitura_do_historico_nao_produz_decisao_falsa(controller, payload):
    controller.previous_analysis.return_value = None
    controller.history_repository.load.side_effect = RuntimeError("histórico indisponível")
    controller.engine = Mock()
    controller.pix_repository = Mock()
    with pytest.raises(RuntimeError, match="histórico indisponível"):
        controller.create(payload)
    controller.engine.evaluate.assert_not_called()
    controller.pix_repository.save.assert_not_called()
    controller.session.commit.assert_not_called()
