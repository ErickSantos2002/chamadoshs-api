"""
Testes do aviso `usuario_id depreciado`.

Este aviso não é um log qualquer: é o sinal que autoriza remover o suporte ao
parâmetro no backend. Se ele voltar a só disparar quando o id recebido difere
do id do token, o log zera com o frontend ainda enviando o parâmetro em todas
as chamadas — e a remoção quebra produção. Daí os testes abaixo.

Cobre também a opcionalidade dos schemas do Grupo B (corpo da requisição):
enquanto `usuario_id` for opcional, o frontend pode parar de enviar sem tomar
422. Tornar obrigatório de novo inverteria a ordem segura de deploy.
"""

from types import SimpleNamespace

import pytest

from app.api.endpoints.chamados import _avisar_usuario_id_depreciado
from app.schemas.comentario import ComentarioCreate
from app.schemas.tarefa_recorrente import RealizarTarefaRequest


@pytest.fixture
def usuario():
    return SimpleNamespace(id=7)


def test_sem_o_parametro_nao_avisa(caplog, usuario):
    """Ausência é o estado final desejado: nada no log."""
    with caplog.at_level("WARNING"):
        _avisar_usuario_id_depreciado("atualizar_chamado", None, usuario)

    assert caplog.text == ""


def test_id_diferente_do_token_avisa(caplog, usuario):
    with caplog.at_level("WARNING"):
        _avisar_usuario_id_depreciado("atualizar_chamado", 99, usuario)

    assert "param usuario_id depreciado" in caplog.text


def test_id_igual_ao_token_tambem_avisa(caplog, usuario):
    """
    O caso que a versão anterior deixava passar — e o mais comum de todos: a
    pessoa logada agindo em nome de si mesma. Sem este aviso, o log fica limpo
    enquanto o frontend continua mandando o parâmetro.
    """
    with caplog.at_level("WARNING"):
        _avisar_usuario_id_depreciado("atualizar_chamado", usuario.id, usuario)

    assert "param usuario_id depreciado" in caplog.text


def test_aviso_identifica_o_endpoint(caplog, usuario):
    """Sem o endpoint no texto não dá para saber qual chamada ainda envia."""
    with caplog.at_level("WARNING"):
        _avisar_usuario_id_depreciado("cancelar_chamado", 1, usuario)

    assert "cancelar_chamado" in caplog.text


def test_comentario_aceita_ausencia_de_usuario_id():
    """
    Grupo B: o campo vive no corpo. Enquanto for opcional, o frontend pode
    parar de enviar sem tomar 422.
    """
    assert ComentarioCreate(chamado_id=1, comentario="texto").usuario_id is None


def test_realizar_tarefa_aceita_ausencia_de_usuario_id():
    assert RealizarTarefaRequest(observacao="feito").usuario_id is None
