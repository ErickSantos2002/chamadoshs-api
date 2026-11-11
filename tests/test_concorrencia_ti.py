"""
Contrato da versão nas escritas da TI (API-12), em SQLite.

O SQLite descarta o `FOR UPDATE`, e a disputa entre duas transações não é
reproduzível aqui — ela está em `test_concorrencia_ti_postgres.py`. O que se
prova no SQLite, sem fingir equivalência:

- a TI que manda `versao_esperada` pede a trava (`refresh(..., with_for_update=True)`)
  e grava chamado e histórico num commit só;
- a TI sem versão segue o fluxo de antes: sem trava, dois commits;
- a versão velha é 409 antes de gravar qualquer coisa — nem campo, nem
  histórico, nem webhook;
- as marcas da TI (cancelar, arquivar, desarquivar) seguem a mesma regra.

O incremento da versão também não se prova aqui: é o trigger do PostgreSQL
(API-4a), que o SQLite não tem.
"""

import pytest
from sqlalchemy import event

from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado
from app.models.historico import HistoricoChamado
from app.services.versao_service import VERSAO_DESATUALIZADA

TI = 100


@pytest.fixture
def webhook(monkeypatch):
    chamadas = []
    monkeypatch.setattr(chamados_endpoint, "enviar_webhook_tecnico", lambda **kw: chamadas.append(kw))
    return chamadas


@pytest.fixture
def espia(sessao, monkeypatch):
    """Registra os refresh com trava e os commits da sessão (a do conftest é a mesma das requisições)."""
    registro = {"travas": 0, "commits": 0}
    original = sessao.refresh

    def refresh(instancia, *args, **kwargs):
        if kwargs.get("with_for_update"):
            registro["travas"] += 1
        return original(instancia, *args, **kwargs)

    monkeypatch.setattr(sessao, "refresh", refresh)

    def contar(_sessao):
        registro["commits"] += 1

    event.listen(sessao, "after_commit", contar)
    yield registro
    event.remove(sessao, "after_commit", contar)


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _versao(sessao):
    sessao.expire_all()
    return sessao.get(Chamado, TI).versao


def _historicos(sessao):
    sessao.expire_all()
    return sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == TI).count()


def _put(cliente, corpo, headers):
    return cliente.put(f"/api/v1/chamados/{TI}", json=corpo, headers=headers)


class TestPutDaTi:
    def test_com_versao_trava_e_grava_num_commit_so(self, cliente, dados, sessao, autenticar, espia, webhook):
        corpo = {"status": "Em Andamento", "tecnico_responsavel_id": dados["tecnico_id"], "versao_esperada": _versao(sessao)}
        espia.update(travas=0, commits=0)

        resposta = _put(cliente, corpo, _admin(autenticar, dados))

        assert resposta.status_code == 200, resposta.text
        assert (espia["travas"], espia["commits"]) == (1, 1)
        assert _historicos(sessao) == 1
        # O webhook sai depois do commit, com o responsável gravado.
        assert [(w["tecnico_id"], w["acao"]) for w in webhook] == [(dados["tecnico_id"], "atribuido")]

    def test_sem_versao_segue_sem_trava_e_com_dois_commits(self, cliente, dados, sessao, autenticar, espia):
        resposta = _put(cliente, {"status": "Em Andamento"}, _admin(autenticar, dados))
        assert resposta.status_code == 200
        assert (espia["travas"], espia["commits"]) == (0, 2)
        assert _historicos(sessao) == 1

    def test_versao_velha_e_409_e_nada_e_gravado(self, cliente, dados, sessao, autenticar, espia, webhook):
        v = _versao(sessao)
        corpo = {
            "status": "Em Andamento",
            "prioridade": "Alta",
            "tecnico_responsavel_id": dados["tecnico_id"],
            "versao_esperada": v + 1,
        }

        resposta = _put(cliente, corpo, _admin(autenticar, dados))

        assert resposta.status_code == 409
        assert resposta.json() == {"detail": VERSAO_DESATUALIZADA, "codigo": "versao_desatualizada", "versao_atual": v}
        assert espia["commits"] == 0
        sessao.expire_all()
        chamado = sessao.get(Chamado, TI)
        assert (chamado.status, chamado.prioridade, chamado.tecnico_responsavel_id) == ("Aberto", "Média", None)
        assert _historicos(sessao) == 0 and webhook == []


class TestMarcasDaTi:
    @pytest.mark.parametrize("rota", ["cancelar", "arquivar"])
    def test_com_versao_trava_e_grava_num_commit_so(self, cliente, dados, sessao, autenticar, espia, rota):
        corpo = {"versao_esperada": _versao(sessao)}
        espia.update(travas=0, commits=0)
        resposta = cliente.patch(f"/api/v1/chamados/{TI}/{rota}", json=corpo, headers=_admin(autenticar, dados))
        assert resposta.status_code == 200, resposta.text
        assert (espia["travas"], espia["commits"]) == (1, 1)
        assert _historicos(sessao) == 1

    @pytest.mark.parametrize("corpo", [None, {}], ids=["sem corpo", "corpo vazio"])
    def test_sem_versao_segue_como_antes(self, cliente, dados, sessao, autenticar, espia, corpo):
        url = f"/api/v1/chamados/{TI}/arquivar"
        headers = _admin(autenticar, dados)
        resposta = cliente.patch(url, headers=headers) if corpo is None else cliente.patch(url, json=corpo, headers=headers)
        assert resposta.status_code == 200
        assert (espia["travas"], espia["commits"]) == (0, 2)

    def test_versao_velha_e_409_e_nada_e_gravado(self, cliente, dados, sessao, autenticar, espia):
        v = _versao(sessao)
        resposta = cliente.patch(
            f"/api/v1/chamados/{TI}/cancelar", json={"versao_esperada": v + 3}, headers=_admin(autenticar, dados)
        )
        assert resposta.status_code == 409 and resposta.json()["versao_atual"] == v
        sessao.expire_all()
        assert sessao.get(Chamado, TI).cancelado is False
        assert _historicos(sessao) == 0 and espia["commits"] == 0
