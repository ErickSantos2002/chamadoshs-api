"""
Pré-condição de versão no PUT e no atendimento (API-4b): o contrato, em SQLite.

`versao_esperada` é a versão em que o cliente baseou a escrita. Em chamado da
Qualidade é obrigatória: sem ela, 428; diferente da atual, 409 com `codigo` e
`versao_atual`. Na TI é opcional — sem ela, tudo como antes; com ela,
conferida. As três marcas estão em `test_precondicao_de_versao_marcas.py`.

No SQLite não há trigger, então a versão gravada é sempre 1: aqui "versão
antiga" é qualquer valor diferente de 1. Que a versão sobe, que a conferência
acontece com a linha travada e que nada sai pela metade está provado em
PostgreSQL em `test_precondicao_de_versao_postgres.py`.

Ordem das recusas, travada em `TestPrecedencia`:
401/403 do token e do perfil → 422 do corpo → 404 → 403/503 da autorização
pelo chamado → 428 → 409 de versão → recusas de estado (400 e os outros 409).
Quem não pode escrever no chamado nunca recebe `versao_atual`.
"""

import pytest

from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado, Usuario
from app.models.historico import HistoricoChamado
from app.services.versao_service import VERSAO_AUSENTE, VERSAO_DESATUALIZADA

DESATUALIZADA = {"detail": VERSAO_DESATUALIZADA, "codigo": "versao_desatualizada", "versao_atual": 1}


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _atendente(autenticar, d):
    # API-13: quem atende é o Técnico da Qualidade, e não mais a ana (comum).
    return autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico")


def _chamado(sessao, chamado_id):
    sessao.expire_all()
    return sessao.get(Chamado, chamado_id)


def _historicos(sessao, chamado_id):
    sessao.expire_all()
    return sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == chamado_id).count()


def _foto(sessao, chamado_id):
    """O que uma escrita recusada não pode ter mudado."""
    c = _chamado(sessao, chamado_id)
    return (
        c.status, c.prioridade, c.tecnico_responsavel_id, c.solucao, c.cancelado, c.arquivado,
        c.data_resolucao, c.versao, _historicos(sessao, chamado_id),
    )


def _put(cliente, chamado_id, corpo, headers):
    return cliente.put(f"/api/v1/chamados/{chamado_id}", json=corpo, headers=headers)


def _atender(cliente, chamado_id, corpo, headers):
    return cliente.patch(f"/api/v1/chamados/{chamado_id}/atendimento", json=corpo, headers=headers)


@pytest.fixture
def chamado_qualidade(chamado_qualidade_do_tecnico, sessao):
    """
    O chamado da Qualidade do Técnico dela, mais um segundo Técnico da
    Qualidade que não é o responsável.

    O `chamado_qualidade` do conftest fica com a atendente de perfil comum,
    estado anterior à API-13; desde a API-13 ela não atende.
    """
    d = chamado_qualidade_do_tecnico
    sessao.add(Usuario(id=46, nome="beto.qualidade", role_id=2, setor_id=d["setor_qualidade_id"], ativo=True))
    sessao.commit()
    return {**d, "outro_tecnico_da_qualidade_id": 46}


@pytest.fixture
def webhook(monkeypatch):
    chamadas = []
    monkeypatch.setattr(chamados_endpoint, "enviar_webhook_tecnico", lambda **kw: chamadas.append(kw))
    return chamadas


@pytest.fixture
def qualidade_intacta(chamado_qualidade, sessao, webhook):
    """Confere, depois do teste, que o chamado da Qualidade não mudou e nada foi avisado."""
    antes = _foto(sessao, chamado_qualidade["chamado_qualidade_id"])
    yield
    assert _foto(sessao, chamado_qualidade["chamado_qualidade_id"]) == antes
    assert webhook == []


INVALIDAS = pytest.mark.parametrize(
    "valor",
    [0, -1, True, False, "1", "abc", 1.0, None, [1], {"v": 1}],
    ids=["zero", "negativa", "true", "false", "string-numerica", "string", "float", "null", "lista", "objeto"],
)


class TestValorInvalidoE422:
    """
    Valor inválido é corpo errado: 422, antes de qualquer leitura do chamado.
    `null` explícito também — ausência é outra coisa (428 ou segue).
    """

    def _confere(self, resposta):
        assert resposta.status_code == 422, resposta.text
        assert resposta.json()["detail"][0]["loc"] == ["body", "versao_esperada"]

    @INVALIDAS
    def test_put_da_qualidade(self, cliente, chamado_qualidade, autenticar, qualidade_intacta, valor):
        d = chamado_qualidade
        self._confere(_put(
            cliente, d["chamado_qualidade_id"], {"prioridade": "Alta", "versao_esperada": valor}, _admin(autenticar, d)
        ))

    @INVALIDAS
    def test_put_da_ti(self, cliente, dados, sessao, autenticar, webhook, valor):
        antes = _foto(sessao, dados["chamado_id"])
        self._confere(_put(
            cliente, dados["chamado_id"], {"prioridade": "Alta", "versao_esperada": valor}, _admin(autenticar, dados)
        ))
        assert _foto(sessao, dados["chamado_id"]) == antes

    @INVALIDAS
    def test_atendimento(self, cliente, chamado_qualidade, autenticar, qualidade_intacta, valor):
        d = chamado_qualidade
        self._confere(_atender(
            cliente, d["chamado_qualidade_id"], {"status": "Em Andamento", "versao_esperada": valor},
            _atendente(autenticar, d),
        ))


class TestQualidadeSemVersaoE428:
    def _confere(self, resposta):
        assert resposta.status_code == 428, resposta.text
        assert resposta.json() == {"detail": VERSAO_AUSENTE}

    def test_put(self, cliente, chamado_qualidade, autenticar, qualidade_intacta):
        d = chamado_qualidade
        self._confere(_put(
            cliente, d["chamado_qualidade_id"], {"status": "Em Andamento", "prioridade": "Alta"}, _admin(autenticar, d)
        ))

    def test_put_de_corpo_vazio(self, cliente, chamado_qualidade, autenticar, qualidade_intacta):
        d = chamado_qualidade
        self._confere(_put(cliente, d["chamado_qualidade_id"], {}, _admin(autenticar, d)))

    def test_atendimento(self, cliente, chamado_qualidade, autenticar, qualidade_intacta):
        d = chamado_qualidade
        self._confere(_atender(cliente, d["chamado_qualidade_id"], {"status": "Em Andamento"}, _atendente(autenticar, d)))


class TestQualidadeComVersaoAntigaE409:
    def _confere(self, resposta):
        assert resposta.status_code == 409, resposta.text
        assert resposta.json() == DESATUALIZADA

    def test_put(self, cliente, chamado_qualidade, autenticar, qualidade_intacta):
        d = chamado_qualidade
        self._confere(_put(
            cliente, d["chamado_qualidade_id"], {"status": "Em Andamento", "versao_esperada": 2}, _admin(autenticar, d)
        ))

    def test_atendimento(self, cliente, chamado_qualidade, autenticar, qualidade_intacta):
        d = chamado_qualidade
        self._confere(_atender(
            cliente, d["chamado_qualidade_id"], {"status": "Em Andamento", "versao_esperada": 7},
            _atendente(autenticar, d),
        ))


class TestQualidadeComVersaoCertaSegue:
    def test_put_grava_e_nao_escreve_a_pre_condicao_no_objeto(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook
    ):
        d = chamado_qualidade
        # Referência forte: a sessão guarda os objetos por referência fraca, e
        # sem ela o objeto que o handler usou seria coletado antes da checagem.
        chamado = sessao.get(Chamado, d["chamado_qualidade_id"])
        resposta = _put(
            cliente, d["chamado_qualidade_id"], {"status": "Em Andamento", "versao_esperada": 1}, _admin(autenticar, d)
        )
        assert resposta.status_code == 200, resposta.text
        assert "versao_esperada" not in resposta.json()
        assert _chamado(sessao, d["chamado_qualidade_id"]) is chamado
        assert chamado.status == "Em Andamento"
        # `exclude={"versao_esperada"}` no PUT: sem ele o setattr pendurava o
        # atributo no objeto ORM.
        assert not hasattr(chamado, "versao_esperada")
        assert _historicos(sessao, d["chamado_qualidade_id"]) == 1
        assert webhook == []


class TestTi:
    """Sem versão, a TI segue como antes; com versão, ela é conferida."""

    CORPO = {"status": "Em Andamento", "tecnico_responsavel_id": 20}

    def test_put_sem_versao_como_antes(self, cliente, dados, sessao, autenticar, webhook):
        resposta = _put(cliente, dados["chamado_id"], self.CORPO, _admin(autenticar, dados))
        assert resposta.status_code == 200
        assert _historicos(sessao, dados["chamado_id"]) == 1
        assert [c["acao"] for c in webhook] == ["atribuido"]

    def test_put_com_versao_certa(self, cliente, dados, sessao, autenticar, webhook):
        resposta = _put(cliente, dados["chamado_id"], {**self.CORPO, "versao_esperada": 1}, _admin(autenticar, dados))
        assert resposta.status_code == 200
        assert _historicos(sessao, dados["chamado_id"]) == 1
        assert [c["acao"] for c in webhook] == ["atribuido"]

    def test_put_com_versao_antiga_e_409_sem_gravar_nem_avisar(self, cliente, dados, sessao, autenticar, webhook):
        antes = _foto(sessao, dados["chamado_id"])
        resposta = _put(cliente, dados["chamado_id"], {**self.CORPO, "versao_esperada": 5}, _admin(autenticar, dados))
        assert resposta.status_code == 409
        assert resposta.json() == DESATUALIZADA
        assert _foto(sessao, dados["chamado_id"]) == antes
        assert webhook == []


class TestPrecedencia:
    """Autorização antes da versão; versão antes das recusas de estado."""

    def test_sem_token_e_401_e_nao_428(self, cliente, chamado_qualidade, qualidade_intacta):
        d = chamado_qualidade
        assert cliente.put(f"/api/v1/chamados/{d['chamado_qualidade_id']}", json={}).status_code == 401
        assert cliente.patch(
            f"/api/v1/chamados/{d['chamado_qualidade_id']}/atendimento", json={"status": "Em Andamento"}
        ).status_code == 401

    @pytest.mark.parametrize("corpo", [{}, {"versao_esperada": 9}], ids=["sem-versao", "versao-antiga"])
    def test_put_de_perfil_comum_e_403_sem_revelar_a_versao(
        self, cliente, chamado_qualidade, autenticar, qualidade_intacta, corpo
    ):
        d = chamado_qualidade
        resposta = _put(cliente, d["chamado_qualidade_id"], corpo, autenticar(d["comum_id"], "usuario.teste", "Usuario"))
        assert resposta.status_code == 403
        assert "versao_atual" not in resposta.json()

    @pytest.mark.parametrize("versao", [None, 9], ids=["sem-versao", "versao-antiga"])
    @pytest.mark.parametrize(
        "quem",
        ["outro_tecnico_da_qualidade_id", "inativo_id", "admin_id"],
        ids=["outro-da-qualidade", "inativo", "admin-nao-responsavel"],
    )
    def test_atendimento_de_quem_nao_e_o_responsavel_e_403_sem_revelar_a_versao(
        self, cliente, chamado_qualidade, autenticar, qualidade_intacta, quem, versao
    ):
        d = chamado_qualidade
        corpo = {"status": "Em Andamento"}
        if versao is not None:
            corpo["versao_esperada"] = versao
        resposta = _atender(cliente, d["chamado_qualidade_id"], corpo, autenticar(d[quem], "quem", "Usuario"))
        assert resposta.status_code == 403
        assert "versao_atual" not in resposta.json()

    def test_responsavel_que_saiu_da_qualidade_e_403_e_nao_409(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook
    ):
        d = chamado_qualidade
        sessao.get(Usuario, d["tecnico_da_qualidade_id"]).setor_id = 1
        sessao.commit()
        resposta = _atender(
            cliente, d["chamado_qualidade_id"], {"status": "Em Andamento", "versao_esperada": 9}, _atendente(autenticar, d)
        )
        assert resposta.status_code == 403
        assert "versao_atual" not in resposta.json()

    def test_atendimento_de_chamado_da_ti_e_403_e_nao_428(self, cliente, dados, autenticar):
        resposta = _atender(cliente, dados["chamado_id"], {"status": "Em Andamento"}, _admin(autenticar, dados))
        assert resposta.status_code == 403

    def test_chamado_inexistente_e_404_e_nao_428(self, cliente, chamado_qualidade, autenticar):
        d = chamado_qualidade
        assert _put(cliente, 9999, {}, _admin(autenticar, d)).status_code == 404
        assert _atender(cliente, 9999, {"status": "Em Andamento"}, _atendente(autenticar, d)).status_code == 404

    def test_valor_invalido_e_422_mesmo_em_chamado_inexistente(self, cliente, dados, autenticar):
        assert _put(cliente, 9999, {"versao_esperada": 0}, _admin(autenticar, dados)).status_code == 422

    def test_put_428_vem_antes_da_validacao_do_responsavel(
        self, cliente, chamado_qualidade, autenticar, qualidade_intacta
    ):
        d = chamado_qualidade
        # Desatribuir é 400 na Qualidade — mas só depois da versão.
        resposta = _put(cliente, d["chamado_qualidade_id"], {"tecnico_responsavel_id": None}, _admin(autenticar, d))
        assert resposta.status_code == 428

    def test_atendimento_409_de_versao_vem_antes_da_transicao(
        self, cliente, chamado_qualidade, autenticar, qualidade_intacta
    ):
        d = chamado_qualidade
        # Aberto → Aguardando também é recusado, mas a versão vem antes.
        resposta = _atender(
            cliente, d["chamado_qualidade_id"], {"status": "Aguardando", "versao_esperada": 4}, _atendente(autenticar, d)
        )
        assert resposta.json() == DESATUALIZADA

    def test_atendimento_409_de_versao_vem_antes_do_arquivado(self, cliente, chamado_qualidade, sessao, autenticar):
        d = chamado_qualidade
        sessao.get(Chamado, d["chamado_qualidade_id"]).arquivado = True
        sessao.commit()
        resposta = _atender(
            cliente, d["chamado_qualidade_id"], {"status": "Em Andamento", "versao_esperada": 4}, _atendente(autenticar, d)
        )
        assert resposta.json() == DESATUALIZADA

    def test_os_outros_409_seguem_sem_codigo(self, cliente, chamado_qualidade, autenticar, qualidade_intacta):
        d = chamado_qualidade
        resposta = _atender(
            cliente, d["chamado_qualidade_id"], {"status": "Aguardando", "versao_esperada": 1}, _atendente(autenticar, d)
        )
        assert resposta.status_code == 409
        assert resposta.json() == {"detail": "Transição de Aberto para Aguardando não permitida"}


class TestAtomicidadeDoPutDaQualidade:
    """
    PUT da Qualidade: chamado e histórico num commit só. A falha real no
    commit — chave estrangeira — está em PostgreSQL; aqui, a falha no meio.
    """

    def test_falha_ao_preparar_o_historico_desfaz_o_status(
        self, cliente, chamado_qualidade, sessao, autenticar, monkeypatch, qualidade_intacta
    ):
        d = chamado_qualidade

        def falha(db, **kwargs):
            db.add(HistoricoChamado(**kwargs))
            db.flush()
            raise RuntimeError("falha simulada antes do commit")

        monkeypatch.setattr(chamados_endpoint, "adicionar_historico", falha)
        with pytest.raises(RuntimeError, match="falha simulada"):
            _put(
                cliente, d["chamado_qualidade_id"],
                {"status": "Em Andamento", "prioridade": "Alta", "versao_esperada": 1}, _admin(autenticar, d),
            )

    def test_sem_mudanca_de_status_nao_grava_historico(self, cliente, chamado_qualidade, sessao, autenticar):
        d = chamado_qualidade
        resposta = _put(cliente, d["chamado_qualidade_id"], {"prioridade": "Alta", "versao_esperada": 1}, _admin(autenticar, d))
        assert resposta.status_code == 200
        assert _historicos(sessao, d["chamado_qualidade_id"]) == 0

    def test_ti_continua_com_os_dois_commits(self, cliente, dados, sessao, autenticar, monkeypatch, webhook):
        """O PUT da TI não passa por `adicionar_historico` — o histórico da TI fica como era."""
        chamadas = []
        monkeypatch.setattr(chamados_endpoint, "adicionar_historico", lambda *a, **k: chamadas.append(1))
        resposta = _put(cliente, dados["chamado_id"], {"status": "Em Andamento"}, _admin(autenticar, dados))
        assert resposta.status_code == 200
        assert chamadas == []
        assert _historicos(sessao, dados["chamado_id"]) == 1
