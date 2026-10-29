"""
Responsável de chamado da TI (API-6, D9).

Até a API-5 o PUT aceitava como responsável da TI qualquer conta que não
fosse de serviço — e o técnico da Qualidade se atribuía um chamado da TI e
passava a lê-lo pelo vínculo. Agora só a equipe da TI: perfil de equipe num
setor de `SETORES_TI_IDS`, pela conta atribuída e não por quem atribui. A
autoatribuição de quem está fora do alcance já para no 404 da D8.

A regra vale na mudança de responsável. O chamado antigo com responsável de
fora fica com ele, e continua editável.
"""

import pytest

import main
from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado, Usuario
from app.models.historico import HistoricoChamado
from leitura_cenario import CHAMADOS, ROLE_DE, cenario_de_leitura  # noqa: F401

API = "/api/v1"
FORA_DA_TI = {"detail": "Técnico responsável não é da equipe da TI"}


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


def _atribuir(cliente, headers, cid, responsavel_id, **extra):
    return cliente.put(f"{API}/chamados/{cid}", headers=headers, json={"tecnico_responsavel_id": responsavel_id, **extra})


def _foto(sessao, cid):
    sessao.expire_all()
    chamado = sessao.get(Chamado, cid)
    historicos = sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == cid).count()
    return chamado.tecnico_responsavel_id, chamado.prioridade, chamado.versao, historicos


class TestQuemPodeSerResponsavel:
    @pytest.mark.parametrize(
        "conta,elegivel",
        [
            ("tecnico_ti", True),  # técnico no setor da TI
            ("admin", True),  # administrador no setor da TI
            ("tecnico_qualidade", False),
            ("tecnico_sem_setor", False),
            ("tecnico_outro_setor", False),
            ("admin_da_qualidade", False),  # administrador, mas de fora da TI
            ("solicitante", False),  # perfil comum, mesmo no setor da TI
            ("colega_do_solicitante", False),
            ("atendente", False),
        ],
    )
    def test_administrador_so_atribui_a_equipe_da_ti(
        self, cliente, sessao, como, cenario_de_leitura, webhook, conta, elegivel
    ):
        cid = CHAMADOS["ti_sem_responsavel"]
        antes = _foto(sessao, cid)
        resposta = _atribuir(cliente, como("admin"), cid, cenario_de_leitura[conta])
        if elegivel:
            assert resposta.status_code == 200, resposta.text
            assert resposta.json()["tecnico_responsavel_id"] == cenario_de_leitura[conta]
            assert [w["tecnico_id"] for w in webhook] == [cenario_de_leitura[conta]]
        else:
            assert (resposta.status_code, resposta.json()) == (400, FORA_DA_TI)
            assert _foto(sessao, cid) == antes
            assert webhook == []

    def test_conta_de_servico_e_inexistente_mantem_as_mensagens(self, cliente, como, cenario_de_leitura):
        cid = CHAMADOS["ti_sem_responsavel"]
        servico = _atribuir(cliente, como("admin"), cid, cenario_de_leitura["conta_de_servico"])
        assert servico.json() == {"detail": "Não é possível atribuir um chamado a uma conta de serviço"}
        inexistente = _atribuir(cliente, como("admin"), cid, 987654)
        assert inexistente.json() == {"detail": "Técnico responsável não encontrado"}

    def test_conta_de_servico_em_setor_da_ti_continua_recusada(self, cliente, sessao, como, cenario_de_leitura):
        conta = sessao.get(Usuario, cenario_de_leitura["conta_de_servico"])
        conta.role_id, conta.setor_id = 2, 1
        sessao.commit()
        resposta = _atribuir(cliente, como("admin"), CHAMADOS["ti_sem_responsavel"], conta.id)
        assert resposta.json() == {"detail": "Não é possível atribuir um chamado a uma conta de serviço"}

    def test_desatribuir_continua_permitido(self, cliente, sessao, como, cenario_de_leitura):
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        resposta = _atribuir(cliente, como("tecnico_ti"), cid, None)
        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] is None

    def test_sem_setores_ti_ninguem_e_elegivel(self, cliente, como, cenario_de_leitura, monkeypatch):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", None)
        resposta = _atribuir(cliente, como("admin"), CHAMADOS["ti_sem_responsavel"], cenario_de_leitura["tecnico_ti"])
        assert (resposta.status_code, resposta.json()) == (400, FORA_DA_TI)

    def test_setor_declarado_torna_o_tecnico_elegivel(self, cliente, como, cenario_de_leitura, monkeypatch):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", "1,4")
        resposta = _atribuir(cliente, como("admin"), CHAMADOS["ti_sem_responsavel"], cenario_de_leitura["tecnico_outro_setor"])
        assert resposta.status_code == 200


class TestAutoatribuicao:
    def test_tecnico_da_ti_se_atribui(self, cliente, como, cenario_de_leitura, webhook):
        cid = CHAMADOS["ti_sem_responsavel"]
        resposta = _atribuir(cliente, como("tecnico_ti"), cid, cenario_de_leitura["tecnico_ti"])
        assert resposta.status_code == 200
        assert len(webhook) == 1

    @pytest.mark.parametrize("quem", ["tecnico_qualidade", "tecnico_sem_setor", "tecnico_outro_setor"])
    def test_fora_do_alcance_nao_se_atribui_nem_passa_a_ler(self, cliente, sessao, como, cenario_de_leitura, quem, webhook):
        """O furo da auditoria: autoatribuir-se para ganhar a leitura pelo vínculo."""
        cid = CHAMADOS["ti_sem_responsavel"]
        antes = _foto(sessao, cid)
        resposta = _atribuir(cliente, como(quem), cid, cenario_de_leitura[quem], versao_esperada=1)
        assert (resposta.status_code, resposta.json()) == (404, {"detail": "Chamado não encontrado"})
        assert _foto(sessao, cid) == antes
        assert cliente.get(f"{API}/chamados/{cid}", headers=como(quem)).status_code == 404
        assert webhook == []

    def test_tecnico_da_qualidade_que_le_pelo_vinculo_nao_reatribui(self, cliente, sessao, como, cenario_de_leitura):
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        antes = _foto(sessao, cid)
        resposta = _atribuir(cliente, como("tecnico_qualidade"), cid, cenario_de_leitura["tecnico_ti"])
        assert (resposta.status_code, resposta.json()) == (403, {"detail": "Este chamado não é da sua equipe"})
        assert _foto(sessao, cid) == antes


class TestChamadoAntigo:
    """`ti_com_tecnico_da_q`: responsável de antes da regra, de fora da equipe."""

    def test_continua_editavel_sem_trocar_o_responsavel(self, cliente, como, cenario_de_leitura):
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        resposta = cliente.put(f"{API}/chamados/{cid}", headers=como("tecnico_ti"), json={"prioridade": "Alta"})
        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] == cenario_de_leitura["tecnico_qualidade"]

    def test_edicao_completa_que_reenvia_o_mesmo_responsavel_passa(self, cliente, como, cenario_de_leitura, webhook):
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        resposta = _atribuir(cliente, como("tecnico_ti"), cid, cenario_de_leitura["tecnico_qualidade"], prioridade="Alta")
        assert resposta.status_code == 200
        assert webhook == []  # o responsável não mudou

    def test_reatribuir_para_a_equipe_passa(self, cliente, como, cenario_de_leitura):
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        resposta = _atribuir(cliente, como("tecnico_ti"), cid, cenario_de_leitura["tecnico_ti"])
        assert resposta.status_code == 200

    def test_e_nao_volta_para_fora_depois(self, cliente, como, cenario_de_leitura):
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        assert _atribuir(cliente, como("tecnico_ti"), cid, cenario_de_leitura["tecnico_ti"]).status_code == 200
        de_volta = _atribuir(cliente, como("admin"), cid, cenario_de_leitura["tecnico_qualidade"])
        assert (de_volta.status_code, de_volta.json()) == (400, FORA_DA_TI)


class TestQualidadeInalterada:
    """A elegibilidade da Qualidade é a dela: setor da Qualidade, qualquer perfil."""

    def test_reatribuicao_da_qualidade_aceita_o_tecnico_da_qualidade(self, cliente, sessao, como, cenario_de_leitura):
        cid = CHAMADOS["q_reatribuido"]
        versao = sessao.get(Chamado, cid).versao
        resposta = _atribuir(cliente, como("tecnico_ti"), cid, cenario_de_leitura["tecnico_qualidade"], versao_esperada=versao)
        assert resposta.status_code == 200

    def test_e_recusa_o_tecnico_da_ti(self, cliente, sessao, como, cenario_de_leitura):
        cid = CHAMADOS["q_reatribuido"]
        versao = sessao.get(Chamado, cid).versao
        resposta = _atribuir(cliente, como("admin"), cid, cenario_de_leitura["tecnico_ti"], versao_esperada=versao)
        assert resposta.json() == {"detail": "Atendente não é elegível para a Qualidade"}


def test_abertura_da_ti_continua_ignorando_responsavel_no_corpo(cliente, como, cenario_de_leitura):
    resposta = cliente.post(
        f"{API}/chamados/",
        headers=como("solicitante"),
        json={
            "solicitante_id": cenario_de_leitura["solicitante"],
            "categoria_id": 1,
            "titulo": "Teclado falhando",
            "descricao": "Algumas teclas do teclado não respondem",
            "prioridade": "Baixa",
            "tecnico_responsavel_id": cenario_de_leitura["tecnico_qualidade"],
        },
    )
    assert resposta.status_code == 201
    assert resposta.json()["tecnico_responsavel_id"] is None
