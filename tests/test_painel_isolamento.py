"""
A conta do painel lê os lembretes e nada mais (API-11, S1).

Aqui todas as contas de serviço do cenário estão em `PAINEL_CONTAS_IDS` — a
administradora, as técnicas da TI, da Qualidade, de outro setor e sem setor,
a de perfil Usuário e as duas do painel. Cada uma lê os lembretes; e cada
rota que ela não podia usar continua recusada, sem escrita e sem webhook.

Duas partes. A primeira pede, para três contas listadas com perfis
diferentes, cada rota que a lista não pode abrir: as sete do módulo de
tarefas, a administração (usuários, setores, categorias, SLA, trilha,
diagnóstico), o interno, as escritas de equipe e os responsáveis da TI. A
segunda roda de novo, com a lista cheia, as matrizes de recusa que já
existiam (API-10, S2, S3 e a S1 sem lista): se a lista vazasse para outra
rota, uma delas cairia.
"""

import pytest

import main
from app.api.deps import CONTA_DE_SERVICO_SEM_ADMINISTRACAO, EQUIPE_TI_NEGADA
from app.api.endpoints.comentarios import CRIAR_INTERNO_NEGADO
from leitura_cenario import CHAMADOS, cenario_de_leitura  # noqa: F401
from test_conta_de_servico_administradora import (  # noqa: F401
    DA_EQUIPE,
    SO_DO_ADMINISTRADOR,
    TestNaoAdministra,
    _foto as _foto_da_administracao,
    cenario,
)
from test_conta_de_servico_escritas import (  # noqa: F401
    ESCRITAS_DE_EQUIPE,
    TestRecusaSemEfeito,
    _esperado as _recusa_da_escrita,
    _foto as _foto_dos_chamados,
    webhooks,
)
from test_conta_de_servico_rotas import (  # noqa: F401
    SERVICOS,
    TestAdministracao,
    TestAuthMe,
    TestComentariosInternos,
    TestContaDeServicoAdministradora,
    TestOCasoDaHomologacao,
    TestResponsaveisDaTI,
    como,
    configurar,
    saidas,
    servicos,
)
from test_lembretes_do_dia import DUAS_DO_PAINEL, ROTA, TestNaoAbreOModulo, tarefas  # noqa: F401

API = "/api/v1"
LISTA = "70,71,72,73,74,75,76,77"
SO_ADMIN = {"detail": CONTA_DE_SERVICO_SEM_ADMINISTRACAO}
SO_EQUIPE = {"detail": EQUIPE_TI_NEGADA}
PERFIL_ADMIN = {"detail": "Requer perfil: Administrador"}
# Uma administradora, uma técnica da TI e uma de perfil Usuário: os três jeitos
# de a lista ser confundida com um perfil.
TRES_DO_PAINEL = ["servico_admin_ti", "servico_tecnico_ti", "servico_usuario_ti"]
ADMINISTRADORAS = {n for n, (_id, role, _s) in SERVICOS.items() if role == 1}


@pytest.fixture(autouse=True)
def painel_listado(monkeypatch):
    """Toda conta de serviço do cenário é conta do painel, em todo teste deste módulo."""
    monkeypatch.setattr(main.settings, "PAINEL_CONTAS_IDS", LISTA)


@pytest.fixture
def listada(cenario, tarefas, cliente, como):
    """Confere, antes de cada recusa, que a conta está mesmo lendo como painel."""
    def _como(quem):
        h = como(quem)
        assert cliente.get(ROTA, headers=h).status_code == 200, quem
        return h

    return _como


def _pedir(cliente, metodo, rota, corpo, headers):
    return cliente.request(metodo, f"{API}{rota}", headers=headers, json=corpo)


@pytest.mark.usefixtures("configurar", "saidas")
class TestListadaNaoGanhaNadaAlemDoLembrete:
    @pytest.mark.parametrize("quem", TRES_DO_PAINEL)
    def test_tarefas_e_administracao_da_equipe(self, cliente, listada, sessao, quem):
        """As sete do módulo, setores, categorias, SLA, trilha e responsáveis da TI."""
        h = listada(quem)
        antes = _foto_da_administracao(sessao)
        obtido = {chave: _pedir(cliente, *DA_EQUIPE[chave], h) for chave in sorted(DA_EQUIPE)}
        assert {c: (r.status_code, r.json()) for c, r in obtido.items()} == {c: (403, SO_EQUIPE) for c in obtido}
        assert _foto_da_administracao(sessao) == antes

    @pytest.mark.parametrize("quem", TRES_DO_PAINEL)
    def test_administracao_de_usuarios_e_diagnostico(self, cliente, listada, sessao, quem):
        h = listada(quem)
        antes = _foto_da_administracao(sessao)
        recusa = SO_ADMIN if quem in ADMINISTRADORAS else PERFIL_ADMIN
        obtido = {chave: _pedir(cliente, *SO_DO_ADMINISTRADOR[chave], h) for chave in sorted(SO_DO_ADMINISTRADOR)}
        assert {c: (r.status_code, r.json()) for c, r in obtido.items()} == {c: (403, recusa) for c in obtido}
        assert _foto_da_administracao(sessao) == antes

    @pytest.mark.parametrize("quem", TRES_DO_PAINEL)
    def test_escritas_de_equipe(self, cliente, listada, sessao, webhooks, quem):
        """PUT, arquivar, desarquivar e cancelar o alheio: a recusa de antes, sem efeito."""
        h = listada(quem)
        antes = _foto_dos_chamados(sessao)
        obtido = {chave: _pedir(cliente, *ESCRITAS_DE_EQUIPE[chave], h) for chave in sorted(ESCRITAS_DE_EQUIPE)}
        esperado = {c: _recusa_da_escrita(quem, c) for c in obtido}
        assert {c: (r.status_code, r.json()["detail"]) for c, r in obtido.items()} == esperado
        assert _foto_dos_chamados(sessao) == antes
        assert webhooks == []

    @pytest.mark.parametrize("quem", TRES_DO_PAINEL)
    def test_comentario_interno(self, cliente, listada, sessao, quem):
        h = listada(quem)
        antes = _foto_da_administracao(sessao)
        criar = cliente.post(f"{API}/comentarios/", headers=h, json={
            "chamado_id": CHAMADOS["ti_do_solicitante"], "comentario": "Interno pelo painel", "is_interno": True,
        })
        if quem == "servico_usuario_ti":
            # Não lê o 100: a recusa vem antes, pela leitura.
            assert criar.status_code == 404
        else:
            assert (criar.status_code, criar.json()) == (403, {"detail": CRIAR_INTERNO_NEGADO})
        lidos = cliente.get(f"{API}/comentarios/chamado/{CHAMADOS['ti_do_solicitante']}", headers=h)
        assert lidos.status_code == 404 or not any(c["is_interno"] for c in lidos.json())
        assert _foto_da_administracao(sessao) == antes

    @pytest.mark.parametrize("quem", sorted(SERVICOS) + sorted(DUAS_DO_PAINEL))
    def test_auth_me_nao_vira_equipe(self, cliente, cenario, tarefas, como, autenticar, quem):
        if quem in DUAS_DO_PAINEL:
            uid, role = DUAS_DO_PAINEL[quem]
            h = autenticar(uid, quem, {1: "Administrador", 2: "Tecnico"}[role])
        else:
            h = como(quem)
        assert cliente.get(ROTA, headers=h).status_code == 200
        me = cliente.get(f"{API}/auth/me", headers=h).json()
        assert me["integra_equipe_ti"] is False
        assert set(me) == {"id", "nome", "setor_id", "role_id", "ativo", "integra_equipe_ti"}
