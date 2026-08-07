"""
Testes do envio de webhook para o n8n.

Nenhuma requisição real sai daqui: `requests.post` é substituído. O ponto
central é que o webhook é acessório — se ele falhar, a criação do chamado não
pode falhar junto.
"""

from types import SimpleNamespace

import pytest
import requests

from app.core.config import settings
from app.services import webhook_service


class _ConsultaFalsa:
    def __init__(self, resultado):
        self._resultado = resultado

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._resultado


class _BancoFalso:
    def __init__(self, usuario=None):
        self._usuario = usuario

    def query(self, *args, **kwargs):
        return _ConsultaFalsa(self._usuario)


@pytest.fixture
def capturar_post(monkeypatch):
    """Substitui requests.post e devolve a lista de chamadas registradas."""
    chamadas = []

    def falso_post(url, json=None, timeout=None):
        chamadas.append({"url": url, "json": json, "timeout": timeout})
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(webhook_service.requests, "post", falso_post)
    return chamadas


@pytest.fixture
def url_configurada(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_TECNICO_URL", "https://exemplo.invalido/webhook/abc")


def test_sem_url_configurada_nao_envia(monkeypatch, capturar_post):
    """
    Padrão desligado: desenvolvimento e testes não podem disparar notificação
    no fluxo de produção por descuido.
    """
    monkeypatch.setattr(settings, "WEBHOOK_TECNICO_URL", "")
    webhook_service.enviar_webhook_tecnico(_BancoFalso(), "CH-1", "Título")
    assert capturar_post == []


def test_usa_a_url_e_o_timeout_da_configuracao(capturar_post, url_configurada, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_TIMEOUT_SEGUNDOS", 9)
    webhook_service.enviar_webhook_tecnico(_BancoFalso(), "CH-1", "Título")

    assert len(capturar_post) == 1
    assert capturar_post[0]["url"] == "https://exemplo.invalido/webhook/abc"
    assert capturar_post[0]["timeout"] == 9


def test_sem_tecnico_envia_sem_atribuicao(capturar_post, url_configurada):
    webhook_service.enviar_webhook_tecnico(_BancoFalso(), "CH-1", "Título", tecnico_id=None)
    assert capturar_post[0]["json"]["tecnico"] == "Sem atribuição"


def test_com_tecnico_envia_o_nome(capturar_post, url_configurada):
    banco = _BancoFalso(usuario=SimpleNamespace(nome="joao.silva"))
    webhook_service.enviar_webhook_tecnico(banco, "CH-1", "Título", tecnico_id=7)
    assert capturar_post[0]["json"]["tecnico"] == "joao.silva"


def test_tecnico_inexistente_cai_no_padrao(capturar_post, url_configurada):
    webhook_service.enviar_webhook_tecnico(_BancoFalso(usuario=None), "CH-1", "Título", tecnico_id=99)
    assert capturar_post[0]["json"]["tecnico"] == "Sem atribuição"


def test_payload_tem_o_formato_esperado(capturar_post, url_configurada):
    webhook_service.enviar_webhook_tecnico(_BancoFalso(), "CH-42", "Impressora", acao="atribuido")
    assert capturar_post[0]["json"] == {
        "protocolo": "CH-42",
        "titulo": "Impressora",
        "tecnico": "Sem atribuição",
        "acao": "atribuido",
    }


@pytest.mark.parametrize(
    "excecao",
    [
        requests.exceptions.Timeout("estourou"),
        requests.exceptions.ConnectionError("sem rota"),
        ValueError("qualquer outra coisa"),
    ],
)
def test_falha_no_envio_nao_propaga(monkeypatch, url_configurada, excecao):
    """
    O webhook é acessório: se o n8n estiver fora do ar, a abertura do chamado
    tem de continuar funcionando.
    """
    def falso_post(*args, **kwargs):
        raise excecao

    monkeypatch.setattr(webhook_service.requests, "post", falso_post)
    webhook_service.enviar_webhook_tecnico(_BancoFalso(), "CH-1", "Título")


def test_status_de_erro_nao_propaga(monkeypatch, url_configurada):
    def falso_post(*args, **kwargs):
        return SimpleNamespace(status_code=500)

    monkeypatch.setattr(webhook_service.requests, "post", falso_post)
    webhook_service.enviar_webhook_tecnico(_BancoFalso(), "CH-1", "Título")


def test_url_nunca_aparece_no_log(caplog, capturar_post, url_configurada):
    """
    A URL contém o identificador do fluxo no n8n e vale como credencial —
    não pode acabar no log do container.
    """
    with caplog.at_level("DEBUG"):
        webhook_service.enviar_webhook_tecnico(_BancoFalso(), "CH-1", "Título")

    assert "exemplo.invalido" not in caplog.text
