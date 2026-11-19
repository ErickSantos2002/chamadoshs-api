"""
Quem abriu o chamado, no histórico (AUD-01).

O chamado tem dois papéis que podem ser de pessoas diferentes: o SOLICITANTE
(`chamados.solicitante_id`, para quem o chamado é) e o AUTOR da abertura
(`historico_chamados.usuario_id`, quem a registrou). O administrador humano
pode abrir em nome de outra pessoa, e era nesse caso que os dois se
confundiam: o histórico "Abertura de chamado" saía com o id do solicitante, e
a trilha dizia que a pessoa abriu um chamado que ela não abriu.

O autor é sempre o dono do token. Vale para a TI e para a Qualidade, que
passam pelo mesmo registro.

A regra de quem pode escolher o solicitante não muda, e é conferida aqui só
para mostrar que os dois campos continuam coerentes: o usuário comum e a
conta de serviço administradora seguem abrindo como eles mesmos, e nesses
casos autor e solicitante coincidem, como antes.

As notificações também não mudam: o aviso da Qualidade já levava o dono do
token como autor, e o da TI nunca levou autor nenhum.
"""

from app.models import Chamado
from app.models.historico import HistoricoChamado
from leitura_cenario import cenario_de_leitura  # noqa: F401
from test_conta_de_servico_rotas import como, configurar, saidas, servicos  # noqa: F401
from test_criacao_qualidade import TITULO_OK, corpo_qualidade, corpo_ti, webhook  # noqa: F401
from test_notificacao_qualidade import BETO, BRUNO, equipe, ligado, posts, ti  # noqa: F401

API = "/api/v1/chamados/"
SERVICO_ADMIN = 75  # test_conta_de_servico_rotas: administradora, conta de serviço
COMUM_DO_CENARIO = 30


def _comum(autenticar, d):
    return autenticar(d["comum_id"], "usuario.teste", "Usuario")


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _abertura(sessao, chamado_id):
    """O único histórico de um chamado recém-criado."""
    historico = sessao.query(HistoricoChamado).filter_by(chamado_id=chamado_id).one()
    assert historico.acao == "Abertura de chamado"
    return historico


def _solicitante(sessao, chamado_id):
    return sessao.query(Chamado).filter_by(id=chamado_id).one().solicitante_id


class TestAdministradorAbreParaOutraPessoa:
    def test_ti_o_autor_e_o_administrador(self, cliente, dados, sessao, autenticar, webhook):
        resposta = cliente.post(
            API, json=corpo_ti(dados, solicitante_id=dados["comum_id"]), headers=_admin(autenticar, dados)
        )

        assert resposta.status_code == 201
        criado = resposta.json()
        assert criado["solicitante_id"] == dados["comum_id"]
        assert _solicitante(sessao, criado["id"]) == dados["comum_id"]
        assert _abertura(sessao, criado["id"]).usuario_id == dados["admin_id"]

    def test_qualidade_o_autor_e_o_administrador(self, cliente, qualidade, sessao, autenticar):
        resposta = cliente.post(
            API,
            json=corpo_qualidade(qualidade, solicitante_id=qualidade["comum_id"]),
            headers=_admin(autenticar, qualidade),
        )

        assert resposta.status_code == 201
        criado = resposta.json()
        assert criado["solicitante_id"] == qualidade["comum_id"]
        assert _solicitante(sessao, criado["id"]) == qualidade["comum_id"]
        assert _abertura(sessao, criado["id"]).usuario_id == qualidade["admin_id"]

    def test_qualidade_sem_responsavel_o_autor_e_o_administrador(
        self, cliente, equipe, sessao, autenticar
    ):
        corpo = corpo_qualidade(equipe, solicitante_id=equipe["comum_id"])
        del corpo["tecnico_responsavel_id"]
        resposta = cliente.post(API, json=corpo, headers=_admin(autenticar, equipe))

        assert resposta.status_code == 201
        criado = resposta.json()
        assert criado["solicitante_id"] == equipe["comum_id"]
        assert _abertura(sessao, criado["id"]).usuario_id == equipe["admin_id"]

    def test_o_resto_do_registro_nao_muda(self, cliente, dados, sessao, autenticar, webhook):
        criado = cliente.post(
            API, json=corpo_ti(dados, solicitante_id=dados["comum_id"]), headers=_admin(autenticar, dados)
        ).json()

        historico = _abertura(sessao, criado["id"])
        assert historico.status_anterior is None
        assert historico.status_novo == "Aberto"
        assert historico.descricao == (
            f"Chamado aberto com protocolo {criado['protocolo']} | Setor de destino: TI"
        )

    def test_administrador_abre_para_si_mesmo(self, cliente, dados, sessao, autenticar, webhook):
        criado = cliente.post(
            API, json=corpo_ti(dados, solicitante_id=dados["admin_id"]), headers=_admin(autenticar, dados)
        ).json()

        assert criado["solicitante_id"] == dados["admin_id"]
        assert _abertura(sessao, criado["id"]).usuario_id == dados["admin_id"]


class TestQuemAbreParaSi:
    def test_usuario_comum_na_ti(self, cliente, dados, sessao, autenticar, webhook):
        criado = cliente.post(API, json=corpo_ti(dados), headers=_comum(autenticar, dados)).json()

        assert criado["solicitante_id"] == dados["comum_id"]
        assert _abertura(sessao, criado["id"]).usuario_id == dados["comum_id"]

    def test_usuario_comum_na_qualidade(self, cliente, qualidade, sessao, autenticar):
        criado = cliente.post(
            API, json=corpo_qualidade(qualidade), headers=_comum(autenticar, qualidade)
        ).json()

        assert criado["solicitante_id"] == qualidade["comum_id"]
        assert _abertura(sessao, criado["id"]).usuario_id == qualidade["comum_id"]


class TestQuemNaoEscolheOSolicitante:
    """A regra não muda: o `solicitante_id` do corpo é ignorado para estes."""

    def test_usuario_comum_informa_outra_pessoa(self, cliente, dados, sessao, autenticar, webhook):
        resposta = cliente.post(
            API, json=corpo_ti(dados, solicitante_id=dados["tecnico_id"]), headers=_comum(autenticar, dados)
        )

        assert resposta.status_code == 201
        criado = resposta.json()
        assert criado["solicitante_id"] == dados["comum_id"]
        assert _abertura(sessao, criado["id"]).usuario_id == dados["comum_id"]

    def test_usuario_comum_informa_outra_pessoa_na_qualidade(
        self, cliente, qualidade, sessao, autenticar
    ):
        resposta = cliente.post(
            API,
            json=corpo_qualidade(qualidade, solicitante_id=qualidade["admin_id"]),
            headers=_comum(autenticar, qualidade),
        )

        assert resposta.status_code == 201
        criado = resposta.json()
        assert criado["solicitante_id"] == qualidade["comum_id"]
        assert _abertura(sessao, criado["id"]).usuario_id == qualidade["comum_id"]

    def test_conta_de_servico_administradora_informa_outra_pessoa(self, cliente, como, sessao):
        resposta = cliente.post(API, headers=como("servico_admin_ti"), json={
            "titulo": "Aberto pela conta", "descricao": "Em nome de outra pessoa, de propósito",
            "solicitante_id": COMUM_DO_CENARIO,
        })

        assert resposta.status_code == 201
        criado = resposta.json()
        assert criado["solicitante_id"] == SERVICO_ADMIN
        assert _abertura(sessao, criado["id"]).usuario_id == SERVICO_ADMIN


class TestNotificacoesNaoMudam:
    def test_qualidade_autor_e_destinatarios(
        self, cliente, equipe, sessao, autenticar, ligado, posts
    ):
        corpo = {
            "setor_destino": "QUALIDADE",
            "descricao": "Não dá sinal de vida desde ontem à tarde",
            "solicitante_id": equipe["comum_id"],
        }
        resposta = cliente.post(API, json=corpo, headers=_admin(autenticar, equipe))

        assert resposta.status_code == 201
        criado = resposta.json()
        (post,) = posts
        assert post["json"]["autor_id"] == equipe["admin_id"]
        assert post["json"]["destinatarios_ids"] == [BRUNO, BETO]
        # O histórico e o aviso passam a dizer a mesma coisa sobre quem abriu.
        assert _abertura(sessao, criado["id"]).usuario_id == post["json"]["autor_id"]

    def test_qualidade_nao_dispara_o_aviso_da_ti(self, cliente, equipe, autenticar, ligado, posts, ti):
        cliente.post(
            API,
            json={
                "setor_destino": "QUALIDADE",
                "descricao": "Não dá sinal de vida desde ontem à tarde",
                "solicitante_id": equipe["comum_id"],
            },
            headers=_admin(autenticar, equipe),
        )

        assert ti == []

    def test_ti_o_aviso_e_o_de_sempre(self, cliente, dados, autenticar, webhook):
        criado = cliente.post(
            API, json=corpo_ti(dados, solicitante_id=dados["comum_id"]), headers=_admin(autenticar, dados)
        ).json()

        assert webhook == [
            {
                "db": webhook[0]["db"],
                "protocolo": criado["protocolo"],
                "titulo": TITULO_OK,
                "tecnico_id": None,
                "acao": "criado",
            }
        ]
