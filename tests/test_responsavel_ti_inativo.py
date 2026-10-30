"""
Responsável de chamado da TI inativo (API-9, F5-1).

Até a API-8 a validação do responsável da TI não olhava `ativo`: o técnico
desativado num setor da TI ainda recebia chamado novo — que ninguém atenderia,
porque a conta inativa nem entra. Agora a conta inativa é recusada como NOVO
responsável, com o mesmo 400 das outras recusas, e nada é gravado.

A regra vale na mudança, como toda a elegibilidade da TI (API-6, D9): o
chamado antigo que já está com alguém hoje inativo fica com essa pessoa, e
continua editável — nada é trocado sozinho.
"""

import pytest

from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado, Usuario
from app.models.historico import HistoricoChamado
from leitura_cenario import CHAMADOS, ROLE_DE, cenario_de_leitura  # noqa: F401

API = "/api/v1"
INATIVO = {"detail": "Técnico responsável está inativo"}
FORA_DA_TI = {"detail": "Técnico responsável não é da equipe da TI"}

TECNICO_TI_INATIVO = 56
ADMIN_TI_INATIVO = 57
CHAMADO_COM_INATIVO = 107  # TI, atribuído ao técnico que depois foi desativado


@pytest.fixture
def inativos(cenario_de_leitura, sessao):
    sessao.add_all([
        Usuario(id=TECNICO_TI_INATIVO, nome="tecnico.ti.inativo", role_id=2, setor_id=1, ativo=False),
        Usuario(id=ADMIN_TI_INATIVO, nome="admin.ti.inativo", role_id=1, setor_id=1, ativo=False),
    ])
    sessao.flush()
    sessao.add(Chamado(
        id=CHAMADO_COM_INATIVO,
        protocolo=f"CH-TESTE-{CHAMADO_COM_INATIVO}",
        solicitante_id=cenario_de_leitura["outro_solicitante"],
        categoria_id=1,
        titulo="Chamado com responsável desativado",
        descricao="Atribuído antes de a conta ser desativada",
        status="Em Andamento",
        prioridade="Média",
        setor_destino="TI",
        tecnico_responsavel_id=TECNICO_TI_INATIVO,
    ))
    sessao.commit()
    return cenario_de_leitura


@pytest.fixture
def como(autenticar, cenario_de_leitura):
    def _como(quem):
        return autenticar(cenario_de_leitura[quem], quem, ROLE_DE.get(quem, "Usuario"))

    return _como


@pytest.fixture
def webhook(monkeypatch):
    chamadas = []
    monkeypatch.setattr(chamados_endpoint, "enviar_webhook_tecnico", lambda **kwargs: chamadas.append(kwargs))
    return chamadas


def _put(cliente, headers, cid, **corpo):
    return cliente.put(f"{API}/chamados/{cid}", headers=headers, json=corpo)


def _foto(sessao, cid):
    sessao.expire_all()
    c = sessao.get(Chamado, cid)
    historicos = sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == cid).count()
    return c.tecnico_responsavel_id, c.status, c.prioridade, c.versao, historicos


class TestNovaAtribuicao:
    @pytest.mark.parametrize("quem", ["admin", "admin_da_qualidade", "tecnico_ti"])
    @pytest.mark.parametrize("inativo", [TECNICO_TI_INATIVO, ADMIN_TI_INATIVO], ids=["tecnico", "admin"])
    def test_inativo_da_ti_e_recusado_sem_escrita(self, cliente, sessao, como, inativos, webhook, quem, inativo):
        cid = CHAMADOS["ti_sem_responsavel"]
        antes = _foto(sessao, cid)
        resposta = _put(cliente, como(quem), cid, tecnico_responsavel_id=inativo, prioridade="Alta", status="Em Andamento")
        assert (resposta.status_code, resposta.json()) == (400, INATIVO)
        assert _foto(sessao, cid) == antes  # nem o responsável, nem os outros campos do corpo
        assert webhook == []

    def test_inativo_de_fora_da_ti_mantem_a_mensagem_de_antes(self, cliente, como, inativos):
        resposta = _put(cliente, como("admin"), CHAMADOS["ti_sem_responsavel"], tecnico_responsavel_id=inativos["inativo_id"])
        assert (resposta.status_code, resposta.json()) == (400, FORA_DA_TI)

    def test_ativo_da_ti_continua_aceito(self, cliente, como, inativos, webhook):
        resposta = _put(cliente, como("admin"), CHAMADOS["ti_sem_responsavel"], tecnico_responsavel_id=inativos["tecnico_ti"])
        assert resposta.status_code == 200
        assert [w["tecnico_id"] for w in webhook] == [inativos["tecnico_ti"]]

    def test_reativado_volta_a_ser_aceito(self, cliente, sessao, como, inativos):
        cid = CHAMADOS["ti_sem_responsavel"]
        assert _put(cliente, como("admin"), cid, tecnico_responsavel_id=TECNICO_TI_INATIVO).status_code == 400
        sessao.get(Usuario, TECNICO_TI_INATIVO).ativo = True
        sessao.commit()
        resposta = _put(cliente, como("admin"), cid, tecnico_responsavel_id=TECNICO_TI_INATIVO)
        assert resposta.status_code == 200

    def test_desativado_depois_deixa_de_ser_aceito(self, cliente, como, inativos):
        cid = CHAMADOS["ti_sem_responsavel"]
        alvo = inativos["tecnico_ti"]
        resposta = cliente.patch(f"{API}/usuarios/{alvo}/desativar", headers=como("admin"))
        assert resposta.status_code == 200
        assert (_put(cliente, como("admin"), cid, tecnico_responsavel_id=alvo).json()) == INATIVO

    def test_a_conta_inativa_nao_se_autoatribui(self, cliente, autenticar, inativos):
        """Nem chega à validação: a conta inativa não se autentica."""
        h = autenticar(TECNICO_TI_INATIVO, "tecnico.ti.inativo", "Tecnico")
        resposta = _put(cliente, h, CHAMADOS["ti_sem_responsavel"], tecnico_responsavel_id=TECNICO_TI_INATIVO)
        assert (resposta.status_code, resposta.json()) == (403, {"detail": "Usuário inativo"})


class TestOrdemDasRespostas:
    """A recusa do inativo é a mesma 400 de sempre, no mesmo lugar da ordem."""

    def test_quem_nao_le_o_chamado_recebe_404_antes(self, cliente, sessao, como, inativos):
        cid = CHAMADOS["ti_sem_responsavel"]
        antes = _foto(sessao, cid)
        resposta = _put(cliente, como("tecnico_outro_setor"), cid, tecnico_responsavel_id=TECNICO_TI_INATIVO)
        assert (resposta.status_code, resposta.json()) == (404, {"detail": "Chamado não encontrado"})
        assert _foto(sessao, cid) == antes

    def test_versao_desatualizada_vem_antes_e_nada_e_gravado(self, cliente, sessao, como, inativos):
        cid = CHAMADOS["ti_sem_responsavel"]
        antes = _foto(sessao, cid)
        resposta = _put(cliente, como("admin"), cid, tecnico_responsavel_id=TECNICO_TI_INATIVO, versao_esperada=antes[3] + 5)
        assert resposta.status_code == 409
        assert _foto(sessao, cid) == antes

    def test_com_a_versao_certa_a_recusa_e_a_do_inativo_e_a_versao_fica(self, cliente, sessao, como, inativos):
        cid = CHAMADOS["ti_sem_responsavel"]
        antes = _foto(sessao, cid)
        resposta = _put(cliente, como("admin"), cid, tecnico_responsavel_id=TECNICO_TI_INATIVO, versao_esperada=antes[3])
        assert (resposta.status_code, resposta.json()) == (400, INATIVO)
        assert _foto(sessao, cid) == antes


class TestChamadoAntigoComResponsavelInativo:
    def test_continua_editavel_sem_trocar_o_responsavel(self, cliente, sessao, como, inativos, webhook):
        resposta = _put(cliente, como("tecnico_ti"), CHAMADO_COM_INATIVO, prioridade="Alta")
        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] == TECNICO_TI_INATIVO
        assert webhook == []

    def test_edicao_completa_que_reenvia_o_mesmo_responsavel_passa(self, cliente, sessao, como, inativos, webhook):
        resposta = _put(
            cliente, como("tecnico_ti"), CHAMADO_COM_INATIVO,
            tecnico_responsavel_id=TECNICO_TI_INATIVO, prioridade="Alta", status="Resolvido",
            solucao="Trocado o cabo de rede da estação",
        )
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["tecnico_responsavel_id"] == TECNICO_TI_INATIVO
        assert resposta.json()["status"] == "Resolvido"
        assert webhook == []  # o responsável não mudou

    def test_reatribuir_para_um_ativo_passa_e_nao_volta_ao_inativo(self, cliente, como, inativos):
        assert _put(cliente, como("tecnico_ti"), CHAMADO_COM_INATIVO, tecnico_responsavel_id=inativos["tecnico_ti"]).status_code == 200
        de_volta = _put(cliente, como("admin"), CHAMADO_COM_INATIVO, tecnico_responsavel_id=TECNICO_TI_INATIVO)
        assert (de_volta.status_code, de_volta.json()) == (400, INATIVO)

    def test_desatribuir_continua_permitido(self, cliente, como, inativos):
        resposta = _put(cliente, como("tecnico_ti"), CHAMADO_COM_INATIVO, tecnico_responsavel_id=None)
        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] is None

    def test_nada_troca_o_responsavel_sozinho(self, cliente, sessao, como, inativos):
        """Ler, listar e desativar mais gente não mexe em atribuição gravada."""
        cliente.get(f"{API}/chamados/", headers=como("admin"))
        cliente.get(f"{API}/chamados/{CHAMADO_COM_INATIVO}", headers=como("tecnico_ti"))
        cliente.patch(f"{API}/usuarios/{inativos['tecnico_ti']}/desativar", headers=como("admin"))
        sessao.expire_all()
        assert sessao.get(Chamado, CHAMADO_COM_INATIVO).tecnico_responsavel_id == TECNICO_TI_INATIVO


def test_abertura_da_ti_continua_ignorando_o_responsavel_do_corpo(cliente, como, inativos):
    resposta = cliente.post(
        f"{API}/chamados/",
        headers=como("solicitante"),
        json={
            "solicitante_id": inativos["solicitante"],
            "categoria_id": 1,
            "titulo": "Monitor piscando",
            "descricao": "O monitor da recepção pisca sem parar",
            "prioridade": "Baixa",
            "tecnico_responsavel_id": TECNICO_TI_INATIVO,
        },
    )
    assert resposta.status_code == 201
    assert resposta.json()["tecnico_responsavel_id"] is None


def test_qualidade_continua_recusando_o_inativo_com_a_mensagem_dela(cliente, sessao, como, inativos):
    cid = CHAMADOS["q_reatribuido"]
    versao = sessao.get(Chamado, cid).versao
    resposta = _put(cliente, como("admin"), cid, tecnico_responsavel_id=inativos["inativo_id"], versao_esperada=versao)
    assert (resposta.status_code, resposta.json()) == (400, {"detail": "Atendente não é elegível para a Qualidade"})
