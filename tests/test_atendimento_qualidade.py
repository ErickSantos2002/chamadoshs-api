"""
Atendimento de chamado da Qualidade: `PATCH /chamados/{id}/atendimento`.

Rota própria porque quem atende a Qualidade costuma ter perfil comum, e o PUT
é da equipe e vai continuar sendo — por ele dá para mexer em responsável,
prioridade e categoria. Aqui o corpo tem só `status` e `solucao`, e tudo o
mais é recusado.

A autorização não vem do perfil: vem do chamado e de quem pede, relidos do
banco a cada requisição. Atende quem é elegível para a Qualidade (mesma regra
da abertura) E é o responsável atual do chamado. Administrador e técnico não
têm passe livre: fora dessas condições, usam o PUT.

As transições são as das ações rápidas do frontend (`AcoesRapidas.tsx` e
`ChamadoDetalhes.tsx`), e o histórico é gravado no mesmo formato do PUT — é
dele que o SLA tira pausas, primeira resposta e resolução.

Concorrência: a rota lê o chamado com `SELECT ... FOR UPDATE`. O SQLite
ignora a cláusula, então aqui se prova só que a consulta pede o lock e que a
autorização usa o estado atual. A disputa real entre duas transações precisa
de ensaio em PostgreSQL.
"""

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

import main
from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado, Usuario
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig

SOLUCAO_OK = "Laudo reemitido com a assinatura do responsável"


def _atendente(autenticar, d):
    return autenticar(d["atendente_id"], "ana.qualidade", "Usuario")


def _patch(cliente, chamado_id, corpo, headers):
    return cliente.patch(f"/api/v1/chamados/{chamado_id}/atendimento", json=corpo, headers=headers)


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


def _altera(sessao, chamado_id, **campos):
    chamado = sessao.get(Chamado, chamado_id)
    for campo, valor in campos.items():
        setattr(chamado, campo, valor)
    sessao.commit()


@pytest.fixture
def webhook(monkeypatch):
    """Registra as chamadas ao webhook da TI em vez de enviá-las."""
    chamadas = []
    monkeypatch.setattr(
        chamados_endpoint, "enviar_webhook_tecnico", lambda **kwargs: chamadas.append(kwargs)
    )
    return chamadas


@pytest.fixture
def intacto(chamado_qualidade, sessao):
    """Confere, depois do teste, que o chamado e o histórico não mudaram."""
    d = chamado_qualidade
    yield
    chamado = _chamado(sessao, d["chamado_qualidade_id"])
    assert chamado.status == "Aberto"
    assert chamado.tecnico_responsavel_id == d["atendente_id"]
    assert chamado.solucao is None
    assert chamado.data_resolucao is None
    assert chamado.prioridade == "Média"
    assert chamado.categoria_id is None
    assert _historicos(sessao, d["chamado_qualidade_id"]) == []


INICIAR = {"status": "Em Andamento"}


class TestAutenticacao:
    def test_sem_token_e_401(self, cliente, chamado_qualidade, intacto):
        resposta = cliente.patch(
            f"/api/v1/chamados/{chamado_qualidade['chamado_qualidade_id']}/atendimento", json=INICIAR
        )
        assert resposta.status_code == 401

    def test_usuario_inativo_e_403(self, cliente, chamado_qualidade, sessao, autenticar, intacto):
        d = chamado_qualidade
        sessao.get(Usuario, d["atendente_id"]).ativo = False
        sessao.commit()

        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        assert resposta.status_code == 403
        assert resposta.json()["detail"] == "Usuário inativo"


class TestAutorizacao:
    def test_responsavel_elegivel_atende(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        assert resposta.status_code == 200
        assert _chamado(sessao, d["chamado_qualidade_id"]).status == "Em Andamento"

    @pytest.mark.parametrize(
        "chave, nome, role",
        [
            ("tecnico_da_qualidade_id", "bruno.qualidade", "Tecnico"),
            ("admin_da_qualidade_id", "aaron.qualidade", "Administrador"),
        ],
        ids=["tecnico", "administrador"],
    )
    def test_equipe_da_qualidade_atende_quando_responsavel(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, chave, nome, role
    ):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], tecnico_responsavel_id=d[chave])

        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, autenticar(d[chave], nome, role))

        assert resposta.status_code == 200

    def test_chamado_inexistente_e_404(self, cliente, chamado_qualidade, autenticar):
        resposta = _patch(cliente, 9999, INICIAR, _atendente(autenticar, chamado_qualidade))
        assert resposta.status_code == 404

    def test_chamado_da_ti_e_403_mesmo_atribuido_ao_atendente(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook
    ):
        d = chamado_qualidade
        _altera(sessao, d["chamado_id"], tecnico_responsavel_id=d["atendente_id"])

        resposta = _patch(cliente, d["chamado_id"], INICIAR, _atendente(autenticar, d))

        assert resposta.status_code == 403
        assert resposta.json()["detail"] == "Esta rota atende só chamados da Qualidade"
        assert _chamado(sessao, d["chamado_id"]).status == "Aberto"
        assert webhook == []

    @pytest.mark.parametrize(
        "chave, nome, role",
        [
            ("tecnico_id", "tecnico.teste", "Tecnico"),
            ("admin_id", "admin.teste", "Administrador"),
        ],
        ids=["tecnico-da-ti", "admin-da-ti"],
    )
    def test_equipe_da_ti_e_403_no_chamado_da_ti(self, cliente, chamado_qualidade, autenticar, chave, nome, role):
        # A rota não é um segundo PUT: nem a equipe atende a TI por ela.
        d = chamado_qualidade
        resposta = _patch(cliente, d["chamado_id"], INICIAR, autenticar(d[chave], nome, role))
        assert resposta.status_code == 403

    @pytest.mark.parametrize(
        "chave, nome, role",
        [
            ("tecnico_id", "tecnico.teste", "Tecnico"),
            ("admin_id", "admin.teste", "Administrador"),
            ("comum_id", "usuario.teste", "Usuario"),
        ],
        ids=["tecnico-da-ti", "admin-da-ti", "solicitante"],
    )
    def test_quem_nao_e_da_qualidade_e_403(
        self, cliente, chamado_qualidade, autenticar, intacto, chave, nome, role
    ):
        d = chamado_qualidade
        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, autenticar(d[chave], nome, role))

        assert resposta.status_code == 403
        assert resposta.json()["detail"] == "Você não atende a Qualidade"

    @pytest.mark.parametrize(
        "chave, nome, role",
        [
            ("tecnico_id", "tecnico.teste", "Tecnico"),
            ("admin_id", "admin.teste", "Administrador"),
        ],
        ids=["tecnico-da-ti", "admin-da-ti"],
    )
    def test_equipe_da_ti_nao_ganha_passe_nem_como_responsavel(
        self, cliente, chamado_qualidade, sessao, autenticar, chave, nome, role
    ):
        # Responsável gravado por SQL direto ou antes desta regra: a rota
        # confere a elegibilidade de quem pede, não confia no campo.
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], tecnico_responsavel_id=d[chave])

        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, autenticar(d[chave], nome, role))

        assert resposta.status_code == 403
        assert _chamado(sessao, d["chamado_qualidade_id"]).status == "Aberto"

    @pytest.mark.parametrize(
        "chave, nome, role",
        [
            ("tecnico_da_qualidade_id", "bruno.qualidade", "Tecnico"),
            ("admin_da_qualidade_id", "aaron.qualidade", "Administrador"),
        ],
        ids=["tecnico-da-qualidade", "admin-da-qualidade"],
    )
    def test_elegivel_que_nao_e_o_responsavel_e_403(
        self, cliente, chamado_qualidade, autenticar, intacto, chave, nome, role
    ):
        d = chamado_qualidade
        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, autenticar(d[chave], nome, role))

        assert resposta.status_code == 403
        assert resposta.json()["detail"] == "Só o responsável atual pode atender este chamado"

    def test_responsavel_que_mudou_de_setor_e_403(self, cliente, chamado_qualidade, sessao, autenticar, intacto):
        d = chamado_qualidade
        sessao.get(Usuario, d["atendente_id"]).setor_id = 1
        sessao.commit()

        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        assert resposta.status_code == 403
        assert resposta.json()["detail"] == "Você não atende a Qualidade"

    def test_responsavel_que_virou_conta_de_servico_e_403(
        self, cliente, chamado_qualidade, sessao, autenticar, intacto
    ):
        d = chamado_qualidade
        sessao.get(Usuario, d["atendente_id"]).conta_de_servico = True
        sessao.commit()

        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        assert resposta.status_code == 403

    def test_conta_de_servico_atribuida_e_403(self, cliente, chamado_qualidade, sessao, autenticar):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], tecnico_responsavel_id=d["conta_de_servico_id"])

        resposta = _patch(
            cliente, d["chamado_qualidade_id"], INICIAR,
            autenticar(d["conta_de_servico_id"], "painel.qualidade", "Usuario"),
        )

        assert resposta.status_code == 403
        assert _chamado(sessao, d["chamado_qualidade_id"]).status == "Aberto"

    @pytest.mark.parametrize("valor", [None, 3], ids=["sem-configuracao", "setor-inativo"])
    def test_qualidade_indisponivel_e_503(
        self, cliente, chamado_qualidade, autenticar, monkeypatch, intacto, valor
    ):
        d = chamado_qualidade
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", valor)

        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        assert resposta.status_code == 503

    def test_responsavel_nao_vem_do_corpo(self, cliente, chamado_qualidade, autenticar, intacto):
        # O cliente não justifica a própria autorização: o responsável é o
        # gravado no chamado, e mandar o campo é 422.
        d = chamado_qualidade
        resposta = _patch(
            cliente, d["chamado_qualidade_id"],
            {**INICIAR, "tecnico_responsavel_id": d["tecnico_da_qualidade_id"]},
            autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico"),
        )

        assert resposta.status_code == 422


class TestContrato:
    @pytest.mark.parametrize(
        "campo, valor",
        [
            ("tecnico_responsavel_id", 41),
            ("prioridade", "Alta"),
            ("categoria_id", 1),
            ("urgencia", "Urgente"),
            ("titulo", "Outro título qualquer"),
            ("observacoes", "anotação"),
            ("cancelado", True),
            ("avaliacao", 5),
        ],
    )
    def test_campo_extra_e_422(self, cliente, chamado_qualidade, autenticar, intacto, campo, valor):
        d = chamado_qualidade
        resposta = _patch(
            cliente, d["chamado_qualidade_id"], {**INICIAR, campo: valor}, _atendente(autenticar, d)
        )

        assert resposta.status_code == 422
        erros = resposta.json()["detail"]
        assert [(e["type"], e["loc"]) for e in erros] == [("extra_forbidden", ["body", campo])]

    @pytest.mark.parametrize("valor", ["Aberto", "Fechado", "Cancelado", "em andamento", "", None])
    def test_status_fora_dos_destinos_e_422(self, cliente, chamado_qualidade, autenticar, intacto, valor):
        d = chamado_qualidade
        resposta = _patch(cliente, d["chamado_qualidade_id"], {"status": valor}, _atendente(autenticar, d))

        assert resposta.status_code == 422
        assert resposta.json()["detail"][0]["loc"] == ["body", "status"]

    def test_status_ausente_e_422(self, cliente, chamado_qualidade, autenticar, intacto):
        d = chamado_qualidade
        resposta = _patch(cliente, d["chamado_qualidade_id"], {}, _atendente(autenticar, d))
        assert resposta.status_code == 422

    def test_corpo_ausente_e_422(self, cliente, chamado_qualidade, autenticar, intacto):
        d = chamado_qualidade
        resposta = cliente.patch(
            f"/api/v1/chamados/{d['chamado_qualidade_id']}/atendimento", headers=_atendente(autenticar, d)
        )
        assert resposta.status_code == 422

    @pytest.mark.parametrize(
        "corpo",
        [
            {"status": "Resolvido"},
            {"status": "Resolvido", "solucao": None},
        ],
        ids=["ausente", "null"],
    )
    def test_resolver_sem_solucao_e_422(self, cliente, chamado_qualidade, sessao, autenticar, corpo):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status="Em Andamento")

        resposta = _patch(cliente, d["chamado_qualidade_id"], corpo, _atendente(autenticar, d))

        assert resposta.status_code == 422
        assert resposta.json()["detail"][0]["type"] == "solucao_obrigatoria"
        assert _chamado(sessao, d["chamado_qualidade_id"]).status == "Em Andamento"

    @pytest.mark.parametrize("solucao", ["curta", "   ", " " * 20 + "123456789 "])
    def test_solucao_curta_ou_so_espacos_e_422(self, cliente, chamado_qualidade, sessao, autenticar, solucao):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status="Em Andamento")

        resposta = _patch(
            cliente, d["chamado_qualidade_id"], {"status": "Resolvido", "solucao": solucao}, _atendente(autenticar, d)
        )

        assert resposta.status_code == 422
        assert resposta.json()["detail"][0]["loc"] == ["body", "solucao"]
        assert _chamado(sessao, d["chamado_qualidade_id"]).solucao is None

    @pytest.mark.parametrize("status_", ["Em Andamento", "Aguardando"])
    @pytest.mark.parametrize("solucao", [SOLUCAO_OK, None], ids=["texto", "null"])
    def test_solucao_sem_resolver_e_422(self, cliente, chamado_qualidade, sessao, autenticar, status_, solucao):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status="Aguardando" if status_ == "Em Andamento" else "Em Andamento")

        resposta = _patch(
            cliente, d["chamado_qualidade_id"], {"status": status_, "solucao": solucao}, _atendente(autenticar, d)
        )

        assert resposta.status_code == 422
        assert resposta.json()["detail"][0]["type"] == "solucao_nao_se_aplica"
        assert _chamado(sessao, d["chamado_qualidade_id"]).solucao is None

    def test_solucao_e_gravada_sem_os_espacos_das_pontas(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status="Em Andamento")

        resposta = _patch(
            cliente, d["chamado_qualidade_id"],
            {"status": "Resolvido", "solucao": f"  {SOLUCAO_OK}  "},
            _atendente(autenticar, d),
        )

        assert resposta.status_code == 200
        assert _chamado(sessao, d["chamado_qualidade_id"]).solucao == SOLUCAO_OK


VALIDAS = [
    ("Aberto", "Em Andamento"),
    ("Em Andamento", "Aguardando"),
    ("Em Andamento", "Resolvido"),
    ("Aguardando", "Em Andamento"),
    ("Aguardando", "Resolvido"),
    ("Resolvido", "Em Andamento"),
    ("Fechado", "Em Andamento"),
]
DESTINOS = ["Em Andamento", "Aguardando", "Resolvido"]
INVALIDAS = [
    (de, para)
    for de in ["Aberto", "Em Andamento", "Aguardando", "Resolvido", "Fechado"]
    for para in DESTINOS
    if (de, para) not in VALIDAS
]


def _corpo(para):
    return {"status": para, "solucao": SOLUCAO_OK} if para == "Resolvido" else {"status": para}


class TestTransicoes:
    def test_tabela_e_a_das_acoes_rapidas(self):
        from app.services.chamado_service import TRANSICOES_DO_ATENDIMENTO, transicao_permitida

        assert {(de, para) for de, destinos in TRANSICOES_DO_ATENDIMENTO.items() for para in destinos} == set(VALIDAS)
        assert all(transicao_permitida(de, para) for de, para in VALIDAS)
        assert not any(transicao_permitida(de, para) for de, para in INVALIDAS)
        assert not transicao_permitida("Desconhecido", "Em Andamento")

    @pytest.mark.parametrize("de, para", VALIDAS)
    def test_valida_e_aplicada(self, cliente, chamado_qualidade, sessao, autenticar, webhook, de, para):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status=de)

        resposta = _patch(cliente, d["chamado_qualidade_id"], _corpo(para), _atendente(autenticar, d))

        assert resposta.status_code == 200
        assert resposta.json()["status"] == para
        assert _chamado(sessao, d["chamado_qualidade_id"]).status == para

    @pytest.mark.parametrize("de, para", INVALIDAS)
    def test_invalida_e_409_sem_gravar(self, cliente, chamado_qualidade, sessao, autenticar, webhook, de, para):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status=de)

        resposta = _patch(cliente, d["chamado_qualidade_id"], _corpo(para), _atendente(autenticar, d))

        assert resposta.status_code == 409
        assert resposta.json()["detail"] == f"Transição de {de} para {para} não permitida"
        chamado = _chamado(sessao, d["chamado_qualidade_id"])
        assert chamado.status == de
        assert chamado.solucao is None
        assert _historicos(sessao, d["chamado_qualidade_id"]) == []

    def test_mesmo_status_e_409(self, cliente, chamado_qualidade, sessao, autenticar):
        # Clique duplo: o segundo pedido encontra o status já aplicado.
        d = chamado_qualidade
        assert _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d)).status_code == 200

        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        assert resposta.status_code == 409
        assert len(_historicos(sessao, d["chamado_qualidade_id"])) == 1

    @pytest.mark.parametrize("marca", ["cancelado", "arquivado"])
    @pytest.mark.parametrize("de, para", [("Aberto", "Em Andamento"), ("Em Andamento", "Resolvido")])
    def test_cancelado_ou_arquivado_e_409(self, cliente, chamado_qualidade, sessao, autenticar, marca, de, para):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status=de, **{marca: True})

        resposta = _patch(cliente, d["chamado_qualidade_id"], _corpo(para), _atendente(autenticar, d))

        assert resposta.status_code == 409
        assert resposta.json()["detail"] == f"Chamado {marca} não pode ser atendido"
        chamado = _chamado(sessao, d["chamado_qualidade_id"])
        assert chamado.status == de
        assert chamado.solucao is None
        assert chamado.data_resolucao is None
        assert _historicos(sessao, d["chamado_qualidade_id"]) == []


class TestEfeitos:
    def test_historico_no_formato_do_put(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        historicos = _historicos(sessao, d["chamado_qualidade_id"])
        assert [
            (h.acao, h.descricao, h.status_anterior, h.status_novo, h.usuario_id) for h in historicos
        ] == [
            ("Alteração de status", "Status alterado de Aberto para Em Andamento", "Aberto", "Em Andamento",
             d["atendente_id"]),
        ]

    def test_resolver_grava_solucao_data_e_tempo(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status="Em Andamento")

        resposta = _patch(
            cliente, d["chamado_qualidade_id"], {"status": "Resolvido", "solucao": SOLUCAO_OK}, _atendente(autenticar, d)
        )

        assert resposta.status_code == 200
        chamado = _chamado(sessao, d["chamado_qualidade_id"])
        assert chamado.solucao == SOLUCAO_OK
        assert chamado.data_resolucao is not None
        assert chamado.tempo_resolucao_minutos is not None
        assert resposta.json()["solucao"] == SOLUCAO_OK

    def test_reabrir_e_resolver_de_novo_preserva_a_primeira_resolucao(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook
    ):
        # Mesma regra do PUT: data e tempo da primeira resolução ficam; o SLA
        # usa a última transição do histórico, não estes campos.
        d = chamado_qualidade
        _altera(sessao, d["chamado_qualidade_id"], status="Em Andamento")
        cabecalho = _atendente(autenticar, d)
        _patch(cliente, d["chamado_qualidade_id"], {"status": "Resolvido", "solucao": SOLUCAO_OK}, cabecalho)
        primeira = _chamado(sessao, d["chamado_qualidade_id"])
        data, tempo = primeira.data_resolucao, primeira.tempo_resolucao_minutos

        assert _patch(cliente, d["chamado_qualidade_id"], INICIAR, cabecalho).status_code == 200
        reaberto = _chamado(sessao, d["chamado_qualidade_id"])
        assert (reaberto.data_resolucao, reaberto.tempo_resolucao_minutos, reaberto.solucao) == (
            data, tempo, SOLUCAO_OK
        )

        nova = "Laudo reemitido de novo, agora com o carimbo"
        assert _patch(
            cliente, d["chamado_qualidade_id"], {"status": "Resolvido", "solucao": nova}, cabecalho
        ).status_code == 200
        final = _chamado(sessao, d["chamado_qualidade_id"])
        assert (final.data_resolucao, final.tempo_resolucao_minutos, final.solucao) == (data, tempo, nova)
        assert [h.status_novo for h in _historicos(sessao, d["chamado_qualidade_id"])] == [
            "Resolvido", "Em Andamento", "Resolvido"
        ]

    def test_so_status_e_solucao_mudam(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        antes = _chamado(sessao, d["chamado_qualidade_id"])
        fixos = ("titulo", "descricao", "prioridade", "urgencia", "categoria_id", "tecnico_responsavel_id",
                 "solicitante_id", "observacoes", "avaliacao", "cancelado", "arquivado", "setor_destino")
        valores = {campo: getattr(antes, campo) for campo in fixos}

        _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        depois = _chamado(sessao, d["chamado_qualidade_id"])
        assert {campo: getattr(depois, campo) for campo in fixos} == valores

    def test_nao_dispara_webhook(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        d = chamado_qualidade
        cabecalho = _atendente(autenticar, d)
        _patch(cliente, d["chamado_qualidade_id"], INICIAR, cabecalho)
        _patch(cliente, d["chamado_qualidade_id"], {"status": "Resolvido", "solucao": SOLUCAO_OK}, cabecalho)

        assert webhook == []

    def test_resposta_e_o_chamado_response(self, cliente, chamado_qualidade, autenticar, webhook):
        d = chamado_qualidade
        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))
        busca = cliente.get(f"/api/v1/chamados/{d['chamado_qualidade_id']}", headers=_atendente(autenticar, d))

        corpo = resposta.json()
        assert set(corpo) == set(busca.json())
        assert corpo["id"] == d["chamado_qualidade_id"]
        assert corpo["setor_destino"] == "QUALIDADE"
        assert corpo == busca.json()

    def test_sla_le_o_historico_gravado_pela_rota(self, cliente, chamado_qualidade, sessao, autenticar, webhook):
        # O SLA é calculado do histórico: pausa em Aguardando e primeira saída
        # de Aberto têm de aparecer no bloco devolvido.
        d = chamado_qualidade
        sessao.add(SLAConfig(prioridade="Média", minutos_resposta=60, minutos_resolucao=480))
        sessao.commit()
        cabecalho = _atendente(autenticar, d)

        _patch(cliente, d["chamado_qualidade_id"], INICIAR, cabecalho)
        resposta = _patch(cliente, d["chamado_qualidade_id"], {"status": "Aguardando"}, cabecalho)

        sla = resposta.json()["sla"]
        assert sla is not None
        busca = cliente.get(f"/api/v1/chamados/{d['chamado_qualidade_id']}", headers=cabecalho).json()["sla"]
        assert sla["prazo_resposta"] == busca["prazo_resposta"]
        assert sla["situacao"] == busca["situacao"]

        from app.services.sla_service import _fim_da_resposta, _periodos_pausados

        historicos = _historicos(sessao, d["chamado_qualidade_id"])
        assert _fim_da_resposta(historicos) == historicos[0].created_at
        assert _periodos_pausados(historicos, historicos[-1].created_at) == [
            (historicos[-1].created_at, historicos[-1].created_at)
        ]


class TestAtomicidade:
    """P-9: chamado e histórico no mesmo commit — ou nenhum dos dois."""

    def test_falha_ao_gravar_o_historico_desfaz_o_status(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, monkeypatch, intacto
    ):
        d = chamado_qualidade

        def falha_depois_de_preparar(db, **kwargs):
            db.add(HistoricoChamado(**kwargs))
            db.flush()
            raise RuntimeError("falha simulada antes do commit")

        monkeypatch.setattr(chamados_endpoint, "registrar_historico", falha_depois_de_preparar)

        with pytest.raises(RuntimeError, match="falha simulada"):
            _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

    def test_falha_no_commit_desfaz_tudo(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, monkeypatch, intacto
    ):
        d = chamado_qualidade

        def commit_que_falha():
            raise OperationalError("COMMIT", {}, Exception("conexão perdida"))

        monkeypatch.setattr(sessao, "commit", commit_que_falha)

        with pytest.raises(OperationalError):
            _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

    def test_sessao_continua_utilizavel_depois_da_falha(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook, monkeypatch
    ):
        d = chamado_qualidade

        original = chamados_endpoint.registrar_historico
        tentativas = []

        def falha_na_primeira(db, **kwargs):
            # Sem `monkeypatch.undo()`: ele desfaria também a configuração da
            # Qualidade feita pela fixture.
            tentativas.append(1)
            if len(tentativas) == 1:
                raise RuntimeError("falha simulada")
            return original(db, **kwargs)

        monkeypatch.setattr(chamados_endpoint, "registrar_historico", falha_na_primeira)
        with pytest.raises(RuntimeError):
            _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        resposta = _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d))

        assert resposta.status_code == 200
        assert len(_historicos(sessao, d["chamado_qualidade_id"])) == 1


class TestConcorrencia:
    """
    P-7. O SQLite descarta o FOR UPDATE, então a disputa entre duas transações
    não é reproduzível aqui — fica para o ensaio em PostgreSQL. O que se prova:
    a consulta pede o lock, e a autorização usa o estado atual do chamado.
    """

    def test_consulta_do_atendimento_pede_o_lock(self, sessao):
        consulta = chamados_endpoint._consulta_do_atendimento(sessao, 101)
        sql = str(consulta.statement.compile(dialect=postgresql.dialect()))

        assert sql.rstrip().endswith("FOR UPDATE")
        assert "WHERE chamados.id = " in sql

    def test_rota_carrega_o_chamado_pela_consulta_com_lock(
        self, cliente, chamado_qualidade, autenticar, webhook, monkeypatch
    ):
        d = chamado_qualidade
        original = chamados_endpoint._consulta_do_atendimento
        chamadas = []

        def espia(db, chamado_id):
            consulta = original(db, chamado_id)
            chamadas.append(str(consulta.statement.compile(dialect=postgresql.dialect())))
            return consulta

        monkeypatch.setattr(chamados_endpoint, "_consulta_do_atendimento", espia)

        assert _patch(cliente, d["chamado_qualidade_id"], INICIAR, _atendente(autenticar, d)).status_code == 200
        assert len(chamadas) == 1 and "FOR UPDATE" in chamadas[0]

    def test_responsavel_anterior_e_recusado_depois_da_reatribuicao(
        self, cliente, chamado_qualidade, sessao, autenticar, webhook
    ):
        d = chamado_qualidade
        cabecalho_anterior = _atendente(autenticar, d)
        assert _patch(cliente, d["chamado_qualidade_id"], INICIAR, cabecalho_anterior).status_code == 200

        reatribuicao = cliente.put(
            f"/api/v1/chamados/{d['chamado_qualidade_id']}",
            json={"tecnico_responsavel_id": d["tecnico_da_qualidade_id"]},
            headers=autenticar(d["tecnico_id"], "tecnico.teste", "Tecnico"),
        )
        assert reatribuicao.status_code == 200

        resposta = _patch(cliente, d["chamado_qualidade_id"], {"status": "Aguardando"}, cabecalho_anterior)

        assert resposta.status_code == 403
        assert resposta.json()["detail"] == "Só o responsável atual pode atender este chamado"
        chamado = _chamado(sessao, d["chamado_qualidade_id"])
        assert chamado.status == "Em Andamento"
        assert chamado.tecnico_responsavel_id == d["tecnico_da_qualidade_id"]
        assert len(_historicos(sessao, d["chamado_qualidade_id"])) == 1

        novo = _patch(
            cliente, d["chamado_qualidade_id"], {"status": "Aguardando"},
            autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico"),
        )
        assert novo.status_code == 200
