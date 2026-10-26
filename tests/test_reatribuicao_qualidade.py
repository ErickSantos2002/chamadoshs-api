"""
Reatribuição de chamado da Qualidade pelo PUT.

O PUT continua da equipe (administrador e técnico) e continua fazendo tudo o
que fazia. O que muda é só o responsável de um chamado da Qualidade: ele passa
pela mesma regra de elegibilidade da abertura (`qualidade_service`), e a troca
não dispara o webhook da TI.

Só a MUDANÇA de responsável é validada. A edição completa do frontend reenvia
o responsável atual em todo salvamento; validar esse reenvio deixaria
ineditável o chamado cujo responsável saiu da Qualidade depois de atribuído.

A TI não muda em nada, e os testes do fim do arquivo conferem isso — inclusive
o que hoje a TI aceita e a Qualidade recusa, como atribuir a conta inativa.
"""

import pytest

import main
from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado, Usuario
from app.models.historico import HistoricoChamado


def _tecnico(autenticar, dados):
    return autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico")


def _admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


@pytest.fixture
def webhook(monkeypatch):
    """Registra as chamadas ao webhook da TI em vez de enviá-las."""
    chamadas = []
    monkeypatch.setattr(
        chamados_endpoint, "enviar_webhook_tecnico", lambda **kwargs: chamadas.append(kwargs)
    )
    return chamadas


def _chamado(sessao, chamado_id):
    sessao.expire_all()
    return sessao.get(Chamado, chamado_id)


def _historicos(sessao, chamado_id):
    sessao.expire_all()
    return sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == chamado_id).count()


def _put(cliente, chamado_id, corpo, headers):
    return cliente.put(f"/api/v1/chamados/{chamado_id}", json=corpo, headers=headers)


class TestNovoResponsavel:
    @pytest.mark.parametrize("quem", [_tecnico, _admin])
    def test_elegivel_e_aceito_pela_equipe(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, quem
    ):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]},
            quem(autenticar, d),
        )

        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] == d["tecnico_da_qualidade_id"]
        assert _chamado(sessao, d["chamado_qualidade_id"]).tecnico_responsavel_id == (
            d["tecnico_da_qualidade_id"]
        )

    def test_qualquer_perfil_elegivel_serve(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"tecnico_responsavel_id": d["admin_da_qualidade_id"]},
            _tecnico(autenticar, d),
        )

        assert resposta.status_code == 200
        assert _chamado(sessao, d["chamado_qualidade_id"]).tecnico_responsavel_id == d["admin_da_qualidade_id"]

    def test_nao_dispara_o_webhook_da_ti(self, cliente, chamado_qualidade, autenticar, webhook):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]},
            _tecnico(autenticar, d),
        )

        assert resposta.status_code == 200
        assert webhook == []

    def test_nao_registra_historico_de_reatribuicao(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook
    ):
        # P-8: o PUT não registra reatribuição em nenhum setor, e o API-3 não
        # muda isso.
        d = chamado_qualidade
        antes = _historicos(sessao, d["chamado_qualidade_id"])

        _put(
            cliente, d["chamado_qualidade_id"],
            {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]},
            _tecnico(autenticar, d),
        )

        assert _historicos(sessao, d["chamado_qualidade_id"]) == antes


class TestResponsavelRecusado:
    @pytest.mark.parametrize(
        "chave",
        ["tecnico_id", "inativo_id", "conta_de_servico_id", "sem_setor_id", "admin_id"],
        ids=["tecnico-da-ti", "inativo", "conta-de-servico", "sem-setor", "admin-da-ti"],
    )
    def test_inelegivel_e_400(self, cliente, chamado_qualidade, sessao, autenticar, webhook, chave):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"tecnico_responsavel_id": d[chave]},
            _tecnico(autenticar, d),
        )

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Atendente não é elegível para a Qualidade"
        assert _chamado(sessao, d["chamado_qualidade_id"]).tecnico_responsavel_id == d["atendente_id"]
        assert webhook == []

    def test_inexistente_e_400(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_qualidade_id"], {"tecnico_responsavel_id": 999}, _tecnico(autenticar, d)
        )

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Atendente não encontrado"
        assert _chamado(sessao, d["chamado_qualidade_id"]).tecnico_responsavel_id == d["atendente_id"]

    def test_desatribuir_e_400(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_qualidade_id"], {"tecnico_responsavel_id": None}, _tecnico(autenticar, d)
        )

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Chamado da Qualidade precisa de responsável"
        assert _chamado(sessao, d["chamado_qualidade_id"]).tecnico_responsavel_id == d["atendente_id"]

    @pytest.mark.parametrize(
        "corpo_extra",
        [{"status": "Em Andamento"}, {"prioridade": "Alta"}, {"observacoes": "anotação"}],
        ids=["status", "prioridade", "observacoes"],
    )
    @pytest.mark.parametrize("responsavel", [None, 999, "tecnico_id"], ids=["null", "inexistente", "inelegivel"])
    def test_recusa_nao_grava_nenhum_campo(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, corpo_extra, responsavel
    ):
        # A validação vem antes de qualquer escrita: o resto do corpo não pode
        # ser gravado quando o responsável é recusado.
        d = chamado_qualidade
        valor = d[responsavel] if isinstance(responsavel, str) else responsavel
        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {**corpo_extra, "tecnico_responsavel_id": valor},
            _tecnico(autenticar, d),
        )

        assert resposta.status_code == 400
        chamado = _chamado(sessao, d["chamado_qualidade_id"])
        assert chamado.status == "Aberto"
        assert chamado.prioridade == "Média"
        assert chamado.observacoes is None
        assert _historicos(sessao, d["chamado_qualidade_id"]) == 0

    @pytest.mark.parametrize("valor", [None, 3], ids=["sem-configuracao", "setor-inativo"])
    def test_qualidade_indisponivel_e_503(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, monkeypatch, valor
    ):
        d = chamado_qualidade
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", valor)

        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]},
            _tecnico(autenticar, d),
        )

        assert resposta.status_code == 503
        assert _chamado(sessao, d["chamado_qualidade_id"]).tecnico_responsavel_id == d["atendente_id"]


class TestMesmoResponsavel:
    """P-6: reenviar o responsável atual não é reatribuição."""

    def test_reenvio_com_outros_campos_e_aceito(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"status": "Em Andamento", "tecnico_responsavel_id": d["atendente_id"]},
            _tecnico(autenticar, d),
        )

        assert resposta.status_code == 200
        assert _chamado(sessao, d["chamado_qualidade_id"]).status == "Em Andamento"
        assert webhook == []

    @pytest.mark.parametrize(
        "torna_inelegivel",
        [
            lambda u: setattr(u, "ativo", False),
            lambda u: setattr(u, "conta_de_servico", True),
            lambda u: setattr(u, "setor_id", 1),
        ],
        ids=["desativado", "virou-conta-de-servico", "mudou-de-setor"],
    )
    def test_responsavel_que_ficou_inelegivel_nao_trava_a_edicao(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, torna_inelegivel
    ):
        d = chamado_qualidade
        torna_inelegivel(sessao.get(Usuario, d["atendente_id"]))
        sessao.commit()

        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"prioridade": "Alta", "tecnico_responsavel_id": d["atendente_id"]},
            _tecnico(autenticar, d),
        )

        assert resposta.status_code == 200
        assert _chamado(sessao, d["chamado_qualidade_id"]).prioridade == "Alta"

    def test_reenvio_nao_consulta_a_configuracao(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, monkeypatch
    ):
        d = chamado_qualidade
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)

        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"prioridade": "Alta", "tecnico_responsavel_id": d["atendente_id"]},
            _tecnico(autenticar, d),
        )

        assert resposta.status_code == 200

    def test_campo_ausente_preserva_o_responsavel(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, monkeypatch
    ):
        d = chamado_qualidade
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)

        resposta = _put(
            cliente, d["chamado_qualidade_id"], {"status": "Em Andamento"}, _tecnico(autenticar, d)
        )

        assert resposta.status_code == 200
        assert _chamado(sessao, d["chamado_qualidade_id"]).tecnico_responsavel_id == d["atendente_id"]


class TestQuemPodeReatribuir:
    """O PUT continua só da equipe: a Qualidade não ganha acesso a ele."""

    @pytest.mark.parametrize(
        "usuario_id, nome",
        [("comum_id", "usuario.teste"), ("atendente_id", "ana.qualidade")],
        ids=["usuario-comum", "atendente-da-qualidade"],
    )
    def test_perfil_comum_e_403(self, cliente, chamado_qualidade, sessao, autenticar, webhook, usuario_id, nome):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_qualidade_id"],
            {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]},
            autenticar(d[usuario_id], nome, "Usuario"),
        )

        assert resposta.status_code == 403
        assert _chamado(sessao, d["chamado_qualidade_id"]).tecnico_responsavel_id == d["atendente_id"]

    def test_sem_token_e_401(self, cliente, chamado_qualidade):
        resposta = cliente.put(
            f"/api/v1/chamados/{chamado_qualidade['chamado_qualidade_id']}",
            json={"tecnico_responsavel_id": chamado_qualidade["tecnico_da_qualidade_id"]},
        )
        assert resposta.status_code == 401

    def test_chamado_inexistente_continua_404(self, cliente, chamado_qualidade, autenticar, webhook):
        resposta = _put(cliente, 9999, {"tecnico_responsavel_id": 999}, _tecnico(autenticar, chamado_qualidade))
        assert resposta.status_code == 404


class TestTiInalterada:
    """O ramo da TI fica como era, inclusive no que a Qualidade passou a recusar."""

    def test_atribuicao_dispara_o_webhook(self, cliente, dados, autenticar, webhook):
        resposta = _put(
            cliente, dados["chamado_id"], {"tecnico_responsavel_id": dados["tecnico_id"]}, _tecnico(autenticar, dados)
        )

        assert resposta.status_code == 200
        assert webhook == [
            {
                "db": webhook[0]["db"],
                "protocolo": "CH-TESTE-100",
                "titulo": "Impressora não liga",
                "tecnico_id": dados["tecnico_id"],
                "acao": "atribuido",
            }
        ]

    def test_reenvio_do_mesmo_tecnico_nao_dispara(self, cliente, dados, sessao, autenticar, webhook):
        sessao.get(Chamado, dados["chamado_id"]).tecnico_responsavel_id = dados["tecnico_id"]
        sessao.commit()

        resposta = _put(
            cliente, dados["chamado_id"], {"tecnico_responsavel_id": dados["tecnico_id"]}, _tecnico(autenticar, dados)
        )

        assert resposta.status_code == 200
        assert webhook == []

    def test_desatribuir_continua_permitido(self, cliente, dados, sessao, autenticar, webhook):
        sessao.get(Chamado, dados["chamado_id"]).tecnico_responsavel_id = dados["tecnico_id"]
        sessao.commit()

        resposta = _put(cliente, dados["chamado_id"], {"tecnico_responsavel_id": None}, _tecnico(autenticar, dados))

        assert resposta.status_code == 200
        assert _chamado(sessao, dados["chamado_id"]).tecnico_responsavel_id is None
        assert webhook == []

    def test_atendente_da_qualidade_continua_atribuivel_na_ti(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook
    ):
        # A regra da Qualidade não vaza para a TI: lá vale só a regra de antes.
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_id"], {"tecnico_responsavel_id": d["atendente_id"]}, _tecnico(autenticar, d)
        )

        assert resposta.status_code == 200
        assert len(webhook) == 1

    def test_conta_inativa_continua_aceita_na_ti(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        # Comportamento de antes, preservado de propósito: corrigir a TI não é
        # escopo desta etapa.
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_id"], {"tecnico_responsavel_id": d["inativo_id"]}, _tecnico(autenticar, d)
        )

        assert resposta.status_code == 200
        assert _chamado(sessao, d["chamado_id"]).tecnico_responsavel_id == d["inativo_id"]

    def test_conta_de_servico_continua_com_a_mensagem_da_ti(self, cliente, chamado_qualidade, autenticar, webhook):
        d = chamado_qualidade
        resposta = _put(
            cliente, d["chamado_id"], {"tecnico_responsavel_id": d["conta_de_servico_id"]}, _tecnico(autenticar, d)
        )

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Não é possível atribuir um chamado a uma conta de serviço"
        assert webhook == []

    def test_inexistente_continua_com_a_mensagem_da_ti(self, cliente, dados, autenticar, webhook):
        resposta = _put(cliente, dados["chamado_id"], {"tecnico_responsavel_id": 999}, _tecnico(autenticar, dados))

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Técnico responsável não encontrado"

    def test_ti_nao_depende_da_configuracao_da_qualidade(
        self, cliente, dados, sessao, autenticar, webhook, monkeypatch
    ):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)

        resposta = _put(
            cliente, dados["chamado_id"], {"tecnico_responsavel_id": dados["tecnico_id"]}, _tecnico(autenticar, dados)
        )

        assert resposta.status_code == 200
        assert len(webhook) == 1

    def test_status_e_historico_iguais_aos_de_antes(self, cliente, dados, sessao, autenticar, webhook):
        resposta = _put(cliente, dados["chamado_id"], {"status": "Resolvido"}, _tecnico(autenticar, dados))

        assert resposta.status_code == 200
        chamado = _chamado(sessao, dados["chamado_id"])
        assert chamado.data_resolucao is not None
        assert chamado.tempo_resolucao_minutos is not None
        historico = (
            sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == dados["chamado_id"]).one()
        )
        assert (historico.acao, historico.descricao, historico.status_anterior, historico.status_novo) == (
            "Alteração de status", "Status alterado de Aberto para Resolvido", "Aberto", "Resolvido"
        )
        assert historico.usuario_id == dados["tecnico_id"]
