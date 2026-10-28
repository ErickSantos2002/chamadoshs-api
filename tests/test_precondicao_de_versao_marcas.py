"""
Pré-condição de versão em cancelar, arquivar e desarquivar (API-4b), em SQLite.

As três rotas não tinham corpo. Agora aceitam um, opcional, com
`versao_esperada`:

- Qualidade: versão obrigatória (428 sem corpo, com corpo vazio ou sem o
  campo) e conferida (409), inclusive para o solicitante que cancela o próprio
  chamado (P-4);
- TI: sem corpo, como sempre; com versão, conferida.

A contagem, o lock e a falha real no commit estão em
`test_precondicao_de_versao_postgres.py`.
"""

import pytest

from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado
from app.models.historico import HistoricoChamado
from app.services.versao_service import VERSAO_AUSENTE, VERSAO_DESATUALIZADA

DESATUALIZADA = {"detail": VERSAO_DESATUALIZADA, "codigo": "versao_desatualizada", "versao_atual": 1}
MARCAS = ["cancelar", "arquivar", "desarquivar"]
DEPOIS = {"cancelar": (True, False), "arquivar": (False, True), "desarquivar": (False, False)}


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _chamado(sessao, chamado_id):
    sessao.expire_all()
    return sessao.get(Chamado, chamado_id)


def _historicos(sessao, chamado_id):
    sessao.expire_all()
    return sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == chamado_id).count()


def _foto(sessao, chamado_id):
    c = _chamado(sessao, chamado_id)
    return (c.status, c.cancelado, c.arquivado, c.versao, _historicos(sessao, chamado_id))


def _preparar(sessao, chamado_id, rota):
    """Desarquivar só vale para chamado arquivado."""
    if rota == "desarquivar":
        sessao.get(Chamado, chamado_id).arquivado = True
        sessao.commit()


def _marca(cliente, chamado_id, rota, headers, corpo=None):
    url = f"/api/v1/chamados/{chamado_id}/{rota}"
    if corpo is None:
        return cliente.patch(url, headers=headers)
    return cliente.patch(url, json=corpo, headers=headers)


@pytest.fixture
def webhook(monkeypatch):
    chamadas = []
    monkeypatch.setattr(chamados_endpoint, "enviar_webhook_tecnico", lambda **kw: chamadas.append(kw))
    return chamadas


@pytest.fixture(params=MARCAS)
def rota(request):
    return request.param


@pytest.fixture
def marca_da_qualidade(chamado_qualidade, sessao, rota, webhook):
    """O chamado da Qualidade pronto para a marca, e a foto de antes."""
    _preparar(sessao, chamado_qualidade["chamado_qualidade_id"], rota)
    return {**chamado_qualidade, "antes": _foto(sessao, chamado_qualidade["chamado_qualidade_id"])}


class TestQualidade:
    @pytest.mark.parametrize(
        "corpo", [None, {}, {"outro": 1}], ids=["sem-corpo", "corpo-vazio", "so-campo-desconhecido"]
    )
    def test_sem_versao_e_428(self, cliente, marca_da_qualidade, sessao, autenticar, rota, webhook, corpo):
        d = marca_da_qualidade
        resposta = _marca(cliente, d["chamado_qualidade_id"], rota, _admin(autenticar, d), corpo)
        assert resposta.status_code == 428
        assert resposta.json() == {"detail": VERSAO_AUSENTE}
        assert _foto(sessao, d["chamado_qualidade_id"]) == d["antes"]
        assert webhook == []

    def test_versao_antiga_e_409(self, cliente, marca_da_qualidade, sessao, autenticar, rota):
        d = marca_da_qualidade
        resposta = _marca(cliente, d["chamado_qualidade_id"], rota, _admin(autenticar, d), {"versao_esperada": 2})
        assert resposta.status_code == 409
        assert resposta.json() == DESATUALIZADA
        assert _foto(sessao, d["chamado_qualidade_id"]) == d["antes"]

    @pytest.mark.parametrize("valor", [0, True, "1", None], ids=["zero", "true", "string", "null"])
    def test_valor_invalido_e_422(self, cliente, marca_da_qualidade, sessao, autenticar, rota, valor):
        d = marca_da_qualidade
        resposta = _marca(cliente, d["chamado_qualidade_id"], rota, _admin(autenticar, d), {"versao_esperada": valor})
        assert resposta.status_code == 422
        assert resposta.json()["detail"][0]["loc"] == ["body", "versao_esperada"]
        assert _foto(sessao, d["chamado_qualidade_id"]) == d["antes"]

    def test_versao_certa_grava_com_historico_e_sem_webhook(self, cliente, marca_da_qualidade, sessao, autenticar, rota, webhook):
        d = marca_da_qualidade
        resposta = _marca(cliente, d["chamado_qualidade_id"], rota, _admin(autenticar, d), {"versao_esperada": 1})
        assert resposta.status_code == 200, resposta.text
        chamado = _chamado(sessao, d["chamado_qualidade_id"])
        assert (chamado.cancelado, chamado.arquivado) == DEPOIS[rota]
        assert _historicos(sessao, d["chamado_qualidade_id"]) == 1
        assert webhook == []

    def test_campo_desconhecido_ao_lado_da_versao_e_ignorado(self, cliente, marca_da_qualidade, autenticar, rota):
        d = marca_da_qualidade
        resposta = _marca(
            cliente, d["chamado_qualidade_id"], rota, _admin(autenticar, d), {"versao_esperada": 1, "motivo": "x"}
        )
        assert resposta.status_code == 200

    def test_falha_ao_preparar_o_historico_desfaz_a_marca(self, cliente, marca_da_qualidade, sessao, autenticar, rota, monkeypatch):
        d = marca_da_qualidade

        def falha(db, **kwargs):
            raise RuntimeError("falha simulada antes do commit")

        monkeypatch.setattr(chamados_endpoint, "adicionar_historico", falha)
        with pytest.raises(RuntimeError, match="falha simulada"):
            _marca(cliente, d["chamado_qualidade_id"], rota, _admin(autenticar, d), {"versao_esperada": 1})
        assert _foto(sessao, d["chamado_qualidade_id"]) == d["antes"]


class TestQualidadeSoNoCancelar:
    def test_solicitante_cancelando_o_proprio_tambem_precisa(self, cliente, chamado_qualidade, sessao, autenticar):
        """P-4: a regra é do chamado, não de quem cancela."""
        d = chamado_qualidade
        resposta = _marca(
            cliente, d["chamado_qualidade_id"], "cancelar", autenticar(d["comum_id"], "usuario.teste", "Usuario")
        )
        assert resposta.status_code == 428
        assert _chamado(sessao, d["chamado_qualidade_id"]).cancelado is False

    def test_solicitante_com_a_versao_cancela(self, cliente, chamado_qualidade, sessao, autenticar):
        d = chamado_qualidade
        resposta = _marca(
            cliente, d["chamado_qualidade_id"], "cancelar",
            autenticar(d["comum_id"], "usuario.teste", "Usuario"), {"versao_esperada": 1},
        )
        assert resposta.status_code == 200
        assert _chamado(sessao, d["chamado_qualidade_id"]).cancelado is True

    @pytest.mark.parametrize("corpo", [None, {"versao_esperada": 9}], ids=["sem-versao", "versao-antiga"])
    def test_quem_nao_e_solicitante_nem_equipe_e_403_sem_revelar_a_versao(
        self, cliente, chamado_qualidade, sessao, autenticar, corpo
    ):
        d = chamado_qualidade
        resposta = _marca(
            cliente, d["chamado_qualidade_id"], "cancelar", autenticar(d["sem_setor_id"], "davi.sem.setor", "Usuario"), corpo
        )
        assert resposta.status_code == 403
        assert "versao_atual" not in resposta.json()

    def test_409_de_versao_vem_antes_do_ja_cancelado(self, cliente, chamado_qualidade, sessao, autenticar):
        d = chamado_qualidade
        sessao.get(Chamado, d["chamado_qualidade_id"]).cancelado = True
        sessao.commit()
        resposta = _marca(cliente, d["chamado_qualidade_id"], "cancelar", _admin(autenticar, d), {"versao_esperada": 4})
        assert resposta.json() == DESATUALIZADA


class TestPrecedencia:
    def test_sem_token_e_401(self, cliente, marca_da_qualidade, rota):
        assert cliente.patch(f"/api/v1/chamados/{marca_da_qualidade['chamado_qualidade_id']}/{rota}").status_code == 401

    def test_inexistente_e_404_e_nao_428(self, cliente, marca_da_qualidade, autenticar, rota):
        assert _marca(cliente, 9999, rota, _admin(autenticar, marca_da_qualidade)).status_code == 404

    @pytest.mark.parametrize("rota_da_equipe", ["arquivar", "desarquivar"])
    @pytest.mark.parametrize("corpo", [None, {"versao_esperada": 9}], ids=["sem-versao", "versao-antiga"])
    def test_perfil_comum_e_403_sem_revelar_a_versao(self, cliente, chamado_qualidade, autenticar, rota_da_equipe, corpo):
        d = chamado_qualidade
        resposta = _marca(
            cliente, d["chamado_qualidade_id"], rota_da_equipe, autenticar(d["comum_id"], "usuario.teste", "Usuario"), corpo
        )
        assert resposta.status_code == 403
        assert "versao_atual" not in resposta.json()


class TestTi:
    """Sem corpo, a TI segue como antes; com versão, ela é conferida."""

    @pytest.fixture
    def ti(self, dados, sessao, rota):
        _preparar(sessao, dados["chamado_id"], rota)
        return {**dados, "antes": _foto(sessao, dados["chamado_id"])}

    def test_sem_corpo_como_antes(self, cliente, ti, sessao, autenticar, rota):
        resposta = _marca(cliente, ti["chamado_id"], rota, _admin(autenticar, ti))
        assert resposta.status_code == 200
        assert (_chamado(sessao, ti["chamado_id"]).cancelado, _chamado(sessao, ti["chamado_id"]).arquivado) == DEPOIS[rota]
        assert _historicos(sessao, ti["chamado_id"]) == 1

    def test_corpo_vazio_como_sem_corpo(self, cliente, ti, autenticar, rota):
        assert _marca(cliente, ti["chamado_id"], rota, _admin(autenticar, ti), {}).status_code == 200

    def test_versao_certa(self, cliente, ti, autenticar, rota):
        assert _marca(cliente, ti["chamado_id"], rota, _admin(autenticar, ti), {"versao_esperada": 1}).status_code == 200

    def test_versao_antiga_e_409_sem_gravar(self, cliente, ti, sessao, autenticar, rota):
        resposta = _marca(cliente, ti["chamado_id"], rota, _admin(autenticar, ti), {"versao_esperada": 3})
        assert resposta.status_code == 409
        assert resposta.json() == DESATUALIZADA
        assert _foto(sessao, ti["chamado_id"]) == ti["antes"]

    def test_corpo_que_nao_e_objeto_e_422(self, cliente, ti, autenticar, rota):
        assert _marca(cliente, ti["chamado_id"], rota, _admin(autenticar, ti), [1]).status_code == 422

    def test_historico_da_ti_segue_com_commit_proprio(self, cliente, ti, sessao, autenticar, rota, monkeypatch):
        chamadas = []
        monkeypatch.setattr(chamados_endpoint, "adicionar_historico", lambda *a, **k: chamadas.append(1))
        assert _marca(cliente, ti["chamado_id"], rota, _admin(autenticar, ti)).status_code == 200
        assert chamadas == []
        assert _historicos(sessao, ti["chamado_id"]) == 1
