"""
Distribuição interna dos chamados da Qualidade (API-14).

Quem abre um chamado para a Qualidade não escolhe mais quem atende: o chamado
nasce sem responsável — "aguardando atribuição" é a ausência dele, sem estado
novo no banco —, e a própria equipe o distribui pelo PUT. As regras:

- abertura sem responsável (campo ausente ou `null`) é aceita; com
  responsável, continua aceita e validada como antes, para o front 1.8.1;
- sem nenhum técnico elegível na Qualidade, a abertura sem responsável é
  recusada (409): ninguém da equipe veria o chamado;
- atribuem e redistribuem o Técnico da Qualidade e o administrador humano, e
  só para Técnico elegível — a regra que já valia na reatribuição;
- cada atribuição fica no histórico, com autor, responsável anterior e novo;
- sem responsável o atendimento não começa: mudar o status é 409, no PUT da
  equipe e na rota de atendimento, com a mesma mensagem;
- o atribuído não volta à fila: desatribuir segue 400;
- depois de atribuído, qualquer Técnico da Qualidade atende pelo PUT.

A TI não muda, e o fim do arquivo confere. A disputa entre duas atribuições
simultâneas está em `test_concorrencia_versao_postgres.py`.
"""

import pytest

import main
from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado, Usuario
from app.models.historico import HistoricoChamado
from versao_do_cliente import com_versao_lida

API = "/api/v1/chamados"
DESCRICAO_OK = "O laudo do lote 42 chegou sem a assinatura do responsável"
AGUARDANDO = "Chamado aguardando atribuição: defina o responsável antes de iniciar o atendimento"
OUTRO_TECNICO = 46


def _comum(autenticar, d):
    return autenticar(d["comum_id"], "usuario.teste", "Usuario")


def _tecnico_da_ti(autenticar, d):
    return autenticar(d["tecnico_id"], "tecnico.teste", "Tecnico")


def _bruno(autenticar, d):
    return autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico")


def _beto(autenticar, d):
    return autenticar(OUTRO_TECNICO, "beto.qualidade", "Tecnico")


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _corpo(d, **sobrescreve):
    """O corpo do formulário novo: sem título, sem categoria e sem responsável."""
    base = {"setor_destino": "QUALIDADE", "descricao": DESCRICAO_OK, "solicitante_id": d["comum_id"]}
    base.update(sobrescreve)
    return base


@pytest.fixture
def webhook(monkeypatch):
    """Registra as chamadas ao webhook da TI em vez de enviá-las."""
    chamadas = []
    monkeypatch.setattr(
        chamados_endpoint, "enviar_webhook_tecnico", lambda **kwargs: chamadas.append(kwargs)
    )
    return chamadas


@pytest.fixture
def equipe(qualidade, sessao):
    """A Qualidade com dois Técnicos elegíveis: o bruno e o beto."""
    sessao.add(Usuario(id=OUTRO_TECNICO, nome="beto.qualidade", role_id=2, setor_id=2, ativo=True))
    sessao.commit()
    return {**qualidade, "outro_tecnico_id": OUTRO_TECNICO}


@pytest.fixture
def na_fila(equipe, cliente, autenticar, webhook):
    """Um chamado aberto pela API como o formulário novo abre: sem responsável."""
    resposta = cliente.post(f"{API}/", json=_corpo(equipe), headers=_comum(autenticar, equipe))
    assert resposta.status_code == 201, resposta.text
    return {**equipe, "fila_id": resposta.json()["id"]}


def _chamado(sessao, chamado_id):
    sessao.expire_all()
    return sessao.get(Chamado, chamado_id)


def _historicos(sessao, chamado_id):
    sessao.expire_all()
    return (
        sessao.query(HistoricoChamado)
        .filter(HistoricoChamado.chamado_id == chamado_id)
        .order_by(HistoricoChamado.id)
        .all()
    )


def _put(cliente, chamado_id, corpo, headers):
    corpo = com_versao_lida(cliente, chamado_id, corpo, headers)
    return cliente.put(f"{API}/{chamado_id}", json=corpo, headers=headers)


def _atender(cliente, chamado_id, corpo, headers):
    corpo = com_versao_lida(cliente, chamado_id, corpo, headers)
    return cliente.patch(f"{API}/{chamado_id}/atendimento", json=corpo, headers=headers)


class TestAberturaSemResponsavel:
    @pytest.mark.parametrize("com_null", [False, True], ids=["campo-ausente", "null"])
    def test_nasce_sem_responsavel(self, cliente, equipe, sessao, autenticar, webhook, com_null):
        corpo = _corpo(equipe, prioridade="Alta")
        if com_null:
            corpo["tecnico_responsavel_id"] = None

        resposta = cliente.post(f"{API}/", json=corpo, headers=_comum(autenticar, equipe))

        assert resposta.status_code == 201, resposta.text
        criado = resposta.json()
        assert criado["setor_destino"] == "QUALIDADE"
        assert criado["tecnico_responsavel_id"] is None
        assert criado["status"] == "Aberto"
        assert criado["prioridade"] == "Alta"
        assert criado["categoria_id"] is None
        assert criado["solicitante_id"] == equipe["comum_id"]
        assert _chamado(sessao, criado["id"]).tecnico_responsavel_id is None
        assert webhook == []

    def test_historico_da_abertura_diz_que_aguarda_atribuicao(self, cliente, equipe, sessao, autenticar):
        criado = cliente.post(f"{API}/", json=_corpo(equipe), headers=_comum(autenticar, equipe)).json()

        (historico,) = _historicos(sessao, criado["id"])
        assert historico.acao == "Abertura de chamado"
        assert historico.usuario_id == equipe["comum_id"]
        assert historico.status_novo == "Aberto"
        assert historico.descricao == (
            f"Chamado aberto com protocolo {criado['protocolo']}"
            " | Setor de destino: Qualidade | Aguardando atribuição"
        )

    def test_com_responsavel_continua_aceito_como_o_front_1_8_1_manda(
        self, cliente, equipe, sessao, autenticar, webhook
    ):
        resposta = cliente.post(
            f"{API}/",
            json=_corpo(equipe, tecnico_responsavel_id=equipe["tecnico_da_qualidade_id"]),
            headers=_comum(autenticar, equipe),
        )

        assert resposta.status_code == 201
        assert resposta.json()["tecnico_responsavel_id"] == equipe["tecnico_da_qualidade_id"]
        (historico,) = _historicos(sessao, resposta.json()["id"])
        assert historico.descricao.endswith("| Setor de destino: Qualidade | Responsável: bruno.qualidade")

    @pytest.mark.parametrize("chave", ["tecnico_id", "atendente_id", "admin_da_qualidade_id", "inativo_id"])
    def test_responsavel_inelegivel_continua_400(self, cliente, equipe, sessao, autenticar, chave):
        antes = sessao.query(Chamado).count()

        resposta = cliente.post(
            f"{API}/",
            json=_corpo(equipe, tecnico_responsavel_id=equipe[chave]),
            headers=_comum(autenticar, equipe),
        )

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Atendente não é elegível para a Qualidade"
        assert sessao.query(Chamado).count() == antes

    def test_sem_nenhum_tecnico_elegivel_e_409_e_nada_e_gravado(self, cliente, qualidade, sessao, autenticar, webhook):
        # O único Técnico da Qualidade sai dela: o setor segue configurado e
        # ativo, mas ninguém da equipe veria o chamado.
        sessao.get(Usuario, qualidade["tecnico_da_qualidade_id"]).ativo = False
        sessao.commit()
        antes = (sessao.query(Chamado).count(), sessao.query(HistoricoChamado).count())

        resposta = cliente.post(f"{API}/", json=_corpo(qualidade), headers=_comum(autenticar, qualidade))

        assert resposta.status_code == 409
        assert resposta.json() == {
            "detail": "Não há técnico da Qualidade disponível para receber chamados no momento"
        }
        assert (sessao.query(Chamado).count(), sessao.query(HistoricoChamado).count()) == antes
        assert webhook == []

    @pytest.mark.parametrize("configuracao", [None, 999, 3], ids=["ausente", "inexistente", "setor-inativo"])
    def test_qualidade_nao_configurada_e_503(self, cliente, equipe, sessao, autenticar, monkeypatch, configuracao):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", configuracao)
        antes = sessao.query(Chamado).count()

        resposta = cliente.post(f"{API}/", json=_corpo(equipe), headers=_comum(autenticar, equipe))

        assert resposta.status_code == 503
        assert sessao.query(Chamado).count() == antes

    def test_titulo_e_categoria_continuam_recusados(self, cliente, equipe, autenticar):
        resposta = cliente.post(
            f"{API}/", json=_corpo(equipe, titulo="Título que não se aplica"), headers=_comum(autenticar, equipe)
        )

        assert resposta.status_code == 422


class TestFilaDaQualidade:
    def test_tecnico_da_qualidade_ve_o_chamado_sem_responsavel(self, cliente, na_fila, autenticar):
        d = na_fila
        for quem in (_bruno, _beto):
            lista = cliente.get(f"{API}/", params={"setor_destino": "QUALIDADE"}, headers=quem(autenticar, d)).json()
            assert [c["id"] for c in lista] == [d["fila_id"]]
            assert lista[0]["tecnico_responsavel_id"] is None
            assert cliente.get(f"{API}/{d['fila_id']}", headers=quem(autenticar, d)).status_code == 200

    def test_solicitante_ve_o_proprio_chamado(self, cliente, na_fila, autenticar):
        d = na_fila
        resposta = cliente.get(f"{API}/{d['fila_id']}", headers=_comum(autenticar, d))

        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] is None

    def test_tecnico_da_ti_sem_vinculo_nao_ve(self, cliente, na_fila, autenticar):
        d = na_fila
        h = _tecnico_da_ti(autenticar, d)

        assert cliente.get(f"{API}/{d['fila_id']}", headers=h).status_code == 404
        assert d["fila_id"] not in [c["id"] for c in cliente.get(f"{API}/", headers=h).json()]
        assert cliente.get(f"{API}/", params={"setor_destino": "QUALIDADE"}, headers=h).json() == []

    def test_comum_lotado_na_qualidade_nao_ve(self, cliente, na_fila, autenticar):
        # Lotação não é equipe: só o Técnico do setor lê a fila.
        d = na_fila
        h = autenticar(d["atendente_id"], "ana.qualidade", "Usuario")

        assert cliente.get(f"{API}/{d['fila_id']}", headers=h).status_code == 404


class TestAtribuicao:
    @pytest.mark.parametrize("quem", [_bruno, _admin], ids=["tecnico-da-qualidade", "administrador"])
    def test_equipe_atribui_a_outro_tecnico(self, cliente, na_fila, sessao, autenticar, webhook, quem):
        d = na_fila
        resposta = _put(cliente, d["fila_id"], {"tecnico_responsavel_id": OUTRO_TECNICO}, quem(autenticar, d))

        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["tecnico_responsavel_id"] == OUTRO_TECNICO
        assert resposta.json()["status"] == "Aberto"
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id == OUTRO_TECNICO
        assert webhook == []

    def test_tecnico_assume_o_chamado(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        resposta = _put(
            cliente, d["fila_id"], {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]}, _bruno(autenticar, d)
        )

        assert resposta.status_code == 200
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id == d["tecnico_da_qualidade_id"]

    def test_historico_da_atribuicao_tem_autor_e_destino(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        _put(cliente, d["fila_id"], {"tecnico_responsavel_id": OUTRO_TECNICO}, _bruno(autenticar, d))

        abertura, atribuicao = _historicos(sessao, d["fila_id"])
        assert abertura.acao == "Abertura de chamado"
        assert atribuicao.acao == "Atribuição de responsável"
        assert atribuicao.usuario_id == d["tecnico_da_qualidade_id"]
        assert atribuicao.descricao == "Responsável definido: beto.qualidade (antes: aguardando atribuição)"
        # Sem status: o SLA lê o histórico pelos status, e atribuir não é pausa
        # nem primeira resposta.
        assert (atribuicao.status_anterior, atribuicao.status_novo) == (None, None)

    def test_historico_da_redistribuicao_tem_anterior_e_novo(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        _put(cliente, d["fila_id"], {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]}, _bruno(autenticar, d))
        resposta = _put(cliente, d["fila_id"], {"tecnico_responsavel_id": OUTRO_TECNICO}, _admin(autenticar, d))

        assert resposta.status_code == 200
        redistribuicao = _historicos(sessao, d["fila_id"])[-1]
        assert redistribuicao.acao == "Atribuição de responsável"
        assert redistribuicao.usuario_id == d["admin_id"]
        assert redistribuicao.descricao == "Responsável alterado de bruno.qualidade para beto.qualidade"
        assert len(_historicos(sessao, d["fila_id"])) == 3

    def test_reenviar_o_mesmo_responsavel_nao_gera_historico(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        _put(cliente, d["fila_id"], {"tecnico_responsavel_id": OUTRO_TECNICO}, _bruno(autenticar, d))
        antes = len(_historicos(sessao, d["fila_id"]))

        resposta = _put(
            cliente, d["fila_id"], {"tecnico_responsavel_id": OUTRO_TECNICO, "prioridade": "Alta"}, _bruno(autenticar, d)
        )

        assert resposta.status_code == 200
        assert len(_historicos(sessao, d["fila_id"])) == antes

    def test_atribuir_e_iniciar_na_mesma_requisicao(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        resposta = _put(
            cliente, d["fila_id"],
            {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "status": "Em Andamento"},
            _bruno(autenticar, d),
        )

        assert resposta.status_code == 200
        assert [h.acao for h in _historicos(sessao, d["fila_id"])] == [
            "Abertura de chamado", "Atribuição de responsável", "Alteração de status",
        ]

    @pytest.mark.parametrize(
        "chave",
        ["tecnico_id", "atendente_id", "admin_da_qualidade_id", "inativo_id", "conta_de_servico_id", "admin_id"],
    )
    def test_inelegivel_e_400_e_o_chamado_segue_na_fila(self, cliente, na_fila, sessao, autenticar, chave):
        d = na_fila
        resposta = _put(cliente, d["fila_id"], {"tecnico_responsavel_id": d[chave]}, _bruno(autenticar, d))

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Atendente não é elegível para a Qualidade"
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id is None
        assert len(_historicos(sessao, d["fila_id"])) == 1

    def test_sem_versao_e_428(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        resposta = cliente.put(
            f"{API}/{d['fila_id']}", json={"tecnico_responsavel_id": OUTRO_TECNICO}, headers=_bruno(autenticar, d)
        )

        assert resposta.status_code == 428
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id is None


class TestQuemNaoAtribui:
    def test_solicitante_comum_e_403(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        resposta = _put(
            cliente, d["fila_id"], {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]}, _comum(autenticar, d)
        )

        assert resposta.status_code == 403
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id is None

    def test_comum_lotado_na_qualidade_e_403(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        resposta = _put(
            cliente, d["fila_id"], {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]},
            autenticar(d["atendente_id"], "ana.qualidade", "Usuario"),
        )

        assert resposta.status_code == 403
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id is None

    def test_tecnico_da_ti_e_404_e_nao_assume(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        for alvo in (d["tecnico_id"], d["tecnico_da_qualidade_id"]):
            resposta = cliente.put(
                f"{API}/{d['fila_id']}",
                json={"tecnico_responsavel_id": alvo, "versao_esperada": 1},
                headers=_tecnico_da_ti(autenticar, d),
            )
            assert resposta.status_code == 404
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id is None
        assert len(_historicos(sessao, d["fila_id"])) == 1

    def test_conta_de_servico_e_403(self, cliente, na_fila, sessao, autenticar):
        # Técnica, na Qualidade e de serviço: lê pelo perfil, não altera.
        d = na_fila
        conta = sessao.get(Usuario, d["conta_de_servico_id"])
        conta.role_id = 2
        sessao.commit()

        resposta = cliente.put(
            f"{API}/{d['fila_id']}",
            json={"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": 1},
            headers=autenticar(d["conta_de_servico_id"], "painel.qualidade", "Tecnico"),
        )

        assert resposta.status_code == 403
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id is None

    def test_sem_token_e_401(self, cliente, na_fila):
        resposta = cliente.put(f"{API}/{na_fila['fila_id']}", json={"tecnico_responsavel_id": OUTRO_TECNICO})
        assert resposta.status_code == 401


class TestSemResponsavelNaoAtende:
    @pytest.mark.parametrize("quem", [_bruno, _admin], ids=["tecnico-da-qualidade", "administrador"])
    @pytest.mark.parametrize("destino", ["Em Andamento", "Aguardando", "Resolvido", "Fechado"])
    def test_put_que_muda_o_status_e_409(self, cliente, na_fila, sessao, autenticar, quem, destino):
        d = na_fila
        corpo = {"status": destino}
        if destino == "Resolvido":
            corpo["solucao"] = "Laudo reemitido com a assinatura do responsável"

        resposta = _put(cliente, d["fila_id"], corpo, quem(autenticar, d))

        assert resposta.status_code == 409
        assert resposta.json() == {"detail": AGUARDANDO}
        chamado = _chamado(sessao, d["fila_id"])
        assert (chamado.status, chamado.solucao, chamado.data_resolucao) == ("Aberto", None, None)
        assert len(_historicos(sessao, d["fila_id"])) == 1

    def test_recusa_nao_grava_os_outros_campos_do_corpo(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        resposta = _put(
            cliente, d["fila_id"], {"status": "Em Andamento", "prioridade": "Crítica"}, _bruno(autenticar, d)
        )

        assert resposta.status_code == 409
        assert _chamado(sessao, d["fila_id"]).prioridade == "Média"

    def test_rota_de_atendimento_da_a_mesma_recusa(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        resposta = _atender(cliente, d["fila_id"], {"status": "Em Andamento"}, _bruno(autenticar, d))

        assert resposta.status_code == 409
        assert resposta.json() == {"detail": AGUARDANDO}
        assert _chamado(sessao, d["fila_id"]).status == "Aberto"
        assert len(_historicos(sessao, d["fila_id"])) == 1

    def test_rota_de_atendimento_continua_fechada_a_quem_nao_atende(self, cliente, na_fila, autenticar):
        # A recusa nova não abre a rota: quem não é da Qualidade segue ouvindo
        # o 403 de antes (o administrador lê o chamado) ou o 404 (a TI não lê).
        d = na_fila
        admin = _atender(cliente, d["fila_id"], {"status": "Em Andamento"}, _admin(autenticar, d))
        ti = cliente.patch(
            f"{API}/{d['fila_id']}/atendimento",
            json={"status": "Em Andamento", "versao_esperada": 1},
            headers=_tecnico_da_ti(autenticar, d),
        )

        assert (admin.status_code, admin.json()["detail"]) == (403, "Você não atende a Qualidade")
        assert ti.status_code == 404

    def test_rota_de_atendimento_confere_a_versao_antes(self, cliente, na_fila, autenticar):
        d = na_fila
        resposta = cliente.patch(
            f"{API}/{d['fila_id']}/atendimento", json={"status": "Em Andamento"}, headers=_bruno(autenticar, d)
        )

        assert resposta.status_code == 428

    def test_status_reenviado_sem_mudar_nao_e_atendimento(self, cliente, na_fila, sessao, autenticar):
        # A edição completa do frontend reenvia o status atual.
        d = na_fila
        resposta = _put(cliente, d["fila_id"], {"status": "Aberto", "prioridade": "Alta"}, _bruno(autenticar, d))

        assert resposta.status_code == 200
        assert _chamado(sessao, d["fila_id"]).prioridade == "Alta"

    @pytest.mark.parametrize(
        "corpo",
        [{"prioridade": "Alta"}, {"observacoes": "aguardando o laudo"}, {"tecnico_responsavel_id": None, "prioridade": "Alta"}],
        ids=["prioridade", "observacoes", "responsavel-null-reenviado"],
    )
    def test_outros_campos_seguem_editaveis_sem_mudar_o_responsavel(self, cliente, na_fila, sessao, autenticar, corpo):
        d = na_fila
        resposta = _put(cliente, d["fila_id"], corpo, _bruno(autenticar, d))

        assert resposta.status_code == 200, resposta.text
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id is None
        assert len(_historicos(sessao, d["fila_id"])) == 1

    def test_solicitante_ainda_cancela_o_chamado_na_fila(self, cliente, na_fila, sessao, autenticar):
        d = na_fila
        h = _comum(autenticar, d)
        versao = cliente.get(f"{API}/{d['fila_id']}", headers=h).json()["versao"]

        resposta = cliente.patch(f"{API}/{d['fila_id']}/cancelar", json={"versao_esperada": versao}, headers=h)

        assert resposta.status_code == 200
        assert _chamado(sessao, d["fila_id"]).cancelado is True


class TestAtribuidoNaoVoltaParaAFila:
    @pytest.mark.parametrize("quem", [_bruno, _admin], ids=["tecnico-da-qualidade", "administrador"])
    def test_desatribuir_segue_400(self, cliente, na_fila, sessao, autenticar, quem):
        d = na_fila
        _put(cliente, d["fila_id"], {"tecnico_responsavel_id": OUTRO_TECNICO}, _bruno(autenticar, d))
        antes = len(_historicos(sessao, d["fila_id"]))

        resposta = _put(cliente, d["fila_id"], {"tecnico_responsavel_id": None}, quem(autenticar, d))

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Chamado da Qualidade precisa de responsável"
        assert _chamado(sessao, d["fila_id"]).tecnico_responsavel_id == OUTRO_TECNICO
        assert len(_historicos(sessao, d["fila_id"])) == antes


class TestAtendimentoCompartilhadoDepoisDeAtribuido:
    @pytest.fixture
    def do_beto(self, na_fila, cliente, autenticar):
        d = na_fila
        resposta = _put(cliente, d["fila_id"], {"tecnico_responsavel_id": OUTRO_TECNICO}, _bruno(autenticar, d))
        assert resposta.status_code == 200
        return d

    def test_colega_inicia_e_resolve_pelo_put(self, cliente, do_beto, sessao, autenticar):
        d = do_beto
        inicio = _put(cliente, d["fila_id"], {"status": "Em Andamento"}, _bruno(autenticar, d))
        fim = _put(
            cliente, d["fila_id"],
            {"status": "Resolvido", "solucao": "Laudo reemitido com a assinatura do responsável"},
            _bruno(autenticar, d),
        )

        assert (inicio.status_code, fim.status_code) == (200, 200)
        chamado = _chamado(sessao, d["fila_id"])
        assert chamado.status == "Resolvido"
        # Atender não muda o responsável: ele fica para a organização.
        assert chamado.tecnico_responsavel_id == OUTRO_TECNICO
        status = [h for h in _historicos(sessao, d["fila_id"]) if h.acao == "Alteração de status"]
        assert [h.usuario_id for h in status] == [d["tecnico_da_qualidade_id"]] * 2

    def test_responsavel_atende_pela_rota_de_atendimento(self, cliente, do_beto, sessao, autenticar):
        d = do_beto
        resposta = _atender(cliente, d["fila_id"], {"status": "Em Andamento"}, _beto(autenticar, d))

        assert resposta.status_code == 200
        assert _chamado(sessao, d["fila_id"]).status == "Em Andamento"

    def test_rota_de_atendimento_segue_so_do_responsavel(self, cliente, do_beto, autenticar):
        # A regra desta rota não mudou: o colega atende pelo PUT.
        d = do_beto
        resposta = _atender(cliente, d["fila_id"], {"status": "Em Andamento"}, _bruno(autenticar, d))

        assert resposta.status_code == 403
        assert resposta.json()["detail"] == "Só o responsável atual pode atender este chamado"

    def test_tecnico_da_ti_continua_fora(self, cliente, do_beto, autenticar):
        d = do_beto
        resposta = cliente.put(
            f"{API}/{d['fila_id']}",
            json={"status": "Em Andamento", "versao_esperada": 2},
            headers=_tecnico_da_ti(autenticar, d),
        )

        assert resposta.status_code == 404


class TestTiInalterada:
    def test_abertura_da_ti_nasce_sem_responsavel_e_avisa_o_webhook(self, cliente, equipe, sessao, autenticar, webhook):
        resposta = cliente.post(
            f"{API}/",
            json={
                "setor_destino": "TI", "titulo": "Impressora do RH não liga", "descricao": DESCRICAO_OK,
                "categoria_id": 1, "solicitante_id": equipe["comum_id"],
            },
            headers=_comum(autenticar, equipe),
        )

        assert resposta.status_code == 201
        assert resposta.json()["tecnico_responsavel_id"] is None
        (historico,) = _historicos(sessao, resposta.json()["id"])
        assert historico.descricao.endswith("| Setor de destino: TI")
        assert [w["acao"] for w in webhook] == ["criado"]

    def test_ti_sem_responsavel_segue_podendo_ser_atendida(self, cliente, equipe, sessao, autenticar, webhook):
        # Na TI o responsável nunca foi condição do atendimento.
        resposta = _put(cliente, equipe["chamado_id"], {"status": "Em Andamento"}, _tecnico_da_ti(autenticar, equipe))

        assert resposta.status_code == 200
        chamado = _chamado(sessao, equipe["chamado_id"])
        assert (chamado.status, chamado.tecnico_responsavel_id) == ("Em Andamento", None)

    def test_atribuicao_na_ti_nao_ganha_historico(self, cliente, equipe, sessao, autenticar, webhook):
        resposta = _put(
            cliente, equipe["chamado_id"], {"tecnico_responsavel_id": equipe["tecnico_id"]},
            _tecnico_da_ti(autenticar, equipe),
        )

        assert resposta.status_code == 200
        assert _historicos(sessao, equipe["chamado_id"]) == []
        assert [w["acao"] for w in webhook] == ["atribuido"]

    def test_desatribuir_na_ti_segue_permitido(self, cliente, equipe, sessao, autenticar, webhook):
        _put(cliente, equipe["chamado_id"], {"tecnico_responsavel_id": equipe["tecnico_id"]}, _tecnico_da_ti(autenticar, equipe))

        resposta = _put(cliente, equipe["chamado_id"], {"tecnico_responsavel_id": None}, _tecnico_da_ti(autenticar, equipe))

        assert resposta.status_code == 200
        assert _chamado(sessao, equipe["chamado_id"]).tecnico_responsavel_id is None
