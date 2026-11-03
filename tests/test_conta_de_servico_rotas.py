"""
Contas de serviço nas rotas da equipe da TI (API-10, decisão C1).

O cenário que motivou a API-10, refeito pelas rotas: na homologação FE-5 ×
API-9, uma conta de serviço técnica no setor da TI recebeu
`integra_equipe_ti: true`, administrou como TI e criou comentário interno
(201). Aqui, com token de verdade, cada rota que dependia dessa
classificação — e, para cada recusa, o banco sem escrita.

Duas classes descrevem, de propósito, o que a C1 NÃO muda e fica registrado
como pendência (AUTH.md, API-10): a conta de serviço administradora passa pelo
perfil, e a técnica da TI ainda lê e altera chamados pelo alcance de perfil
(API-5/API-6), que não passa por `integra_equipe_ti`.
"""

import pytest
import requests

import main
from app.api.deps import EQUIPE_TI_NEGADA
from app.api.endpoints.comentarios import COMENTARIO_NAO_ENCONTRADO, CRIAR_INTERNO_NEGADO
from app.models import Categoria, Chamado, Setor, Usuario
from app.models.comentario import ComentarioChamado
from app.models.evento_setor import EventoDeSetor
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.models.tarefa_recorrente import TarefaRecorrente
from app.services.responsavel_ti_service import CONTA_DE_SERVICO
from leitura_cenario import CHAMADOS, ROLE_DE, comentario_interno, cenario_de_leitura  # noqa: F401

API = "/api/v1"
NEGADO = {"detail": EQUIPE_TI_NEGADA}
SETOR_COMERCIAL = 4

# nome: (id, role_id, setor_id) — todas com conta_de_servico=True.
SERVICOS = {
    "servico_tecnico_ti": (70, 2, 1),
    "servico_tecnico_qualidade": (71, 2, 2),
    "servico_tecnico_outro": (72, 2, SETOR_COMERCIAL),
    "servico_tecnico_sem_setor": (73, 2, None),
    "servico_usuario_ti": (74, 3, 1),
    "servico_admin_ti": (75, 1, 1),
}
PERFIL_DE = {1: "Administrador", 2: "Tecnico", 3: "Usuario"}
SERVICOS_NAO_ADMIN = sorted(n for n, (_, role, _s) in SERVICOS.items() if role != 1)

# O comentário interno escrito pela própria conta de serviço técnica da TI,
# no chamado da TI que ela lê pelo perfil.
INTERNO_DO_SERVICO = 7000
CHAMADO_TI = CHAMADOS["ti_sem_responsavel"]

ROTAS_DA_EQUIPE = [
    ("GET", "/tarefas-recorrentes/", None),
    ("GET", "/eventos/?alvo=setor", None),
    ("GET", "/eventos/", None),
    ("GET", "/chamados/responsaveis-ti", None),
    ("POST", "/setores/", {"nome": "Setor do serviço", "descricao": "não deve existir"}),
    ("POST", "/categorias/", {"nome": "Categoria do serviço", "descricao": "não deve existir"}),
    ("PUT", "/sla-configs/Alta", {"minutos_resposta": 1, "minutos_resolucao": 2}),
]


@pytest.fixture
def servicos(cenario_de_leitura, sessao):
    sessao.add(Usuario(id=56, nome="tecnico.ti.dois", role_id=2, setor_id=1, ativo=True))
    for nome, (uid, role, setor) in SERVICOS.items():
        sessao.add(Usuario(id=uid, nome=nome.replace("_", "."), role_id=role, setor_id=setor,
                           ativo=True, conta_de_servico=True))
    sessao.merge(SLAConfig(prioridade="Alta", minutos_resposta=30, minutos_resolucao=240))
    sessao.flush()
    sessao.add(ComentarioChamado(
        id=INTERNO_DO_SERVICO, chamado_id=CHAMADO_TI, usuario_id=70,
        comentario="Interno escrito pela conta de serviço", is_interno=True,
    ))
    # Vínculos: a técnica de outro setor é a responsável atual de um chamado da
    # TI, e a de perfil Usuário é a solicitante de outro.
    sessao.get(Chamado, CHAMADOS["ti_arquivado"]).tecnico_responsavel_id = 72
    sessao.get(Chamado, CHAMADOS["ti_cancelado"]).solicitante_id = 74
    sessao.commit()
    return {**cenario_de_leitura, **{n: v[0] for n, v in SERVICOS.items()}, "tecnico_ti_dois": 56}


@pytest.fixture
def como(autenticar, servicos):
    def _como(quem):
        if quem in SERVICOS:
            return autenticar(SERVICOS[quem][0], quem, PERFIL_DE[SERVICOS[quem][1]])
        return autenticar(servicos[quem], quem, ROLE_DE.get(quem, "Usuario"))

    return _como


@pytest.fixture
def configurar(monkeypatch):
    monkeypatch.setattr(main.settings, "SETORES_TI_IDS", "1")
    monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", 2)


@pytest.fixture
def saidas(monkeypatch):
    """Nenhuma recusa chama ninguém fora."""
    def _bloquear(*args, **kwargs):
        raise AssertionError("requisição externa num teste de permissão")

    monkeypatch.setattr(requests, "post", _bloquear)
    monkeypatch.setattr(requests.Session, "request", _bloquear)


def _foto(sessao):
    sessao.expire_all()
    return {
        "setores": sessao.query(Setor).count(),
        "categorias": sessao.query(Categoria).count(),
        "sla": sorted((c.prioridade, c.minutos_resposta, c.minutos_resolucao) for c in sessao.query(SLAConfig)),
        "tarefas": sessao.query(TarefaRecorrente).count(),
        "eventos_de_setor": sessao.query(EventoDeSetor).count(),
        "comentarios": sorted((c.id, c.comentario, c.is_interno) for c in sessao.query(ComentarioChamado)),
        "historico": sessao.query(HistoricoChamado).count(),
        "chamados": sorted(
            (c.id, c.tecnico_responsavel_id, c.prioridade, c.status, c.versao) for c in sessao.query(Chamado)
        ),
    }


def _pedir(cliente, metodo, rota, corpo, headers):
    return cliente.request(metodo, f"{API}{rota}", headers=headers, json=corpo)


@pytest.mark.usefixtures("configurar", "saidas")
class TestOCasoDaHomologacao:
    """O que a FE-5 reproduziu contra a API-9, agora recusado."""

    def test_auth_me_diz_que_nao_integra(self, cliente, como):
        resposta = cliente.get(f"{API}/auth/me", headers=como("servico_tecnico_ti"))
        assert resposta.status_code == 200
        assert resposta.json()["integra_equipe_ti"] is False

    def test_rota_da_equipe_recusa(self, cliente, como, sessao):
        antes = _foto(sessao)
        resposta = cliente.get(f"{API}/tarefas-recorrentes/", headers=como("servico_tecnico_ti"))
        assert (resposta.status_code, resposta.json()) == (403, NEGADO)
        assert _foto(sessao) == antes

    def test_interno_nao_e_criado(self, cliente, como, sessao):
        antes = _foto(sessao)
        resposta = cliente.post(f"{API}/comentarios/", headers=como("servico_tecnico_ti"), json={
            "chamado_id": CHAMADOS["ti_do_solicitante"], "comentario": "Interno indevido", "is_interno": True,
        })
        assert (resposta.status_code, resposta.json()) == (403, {"detail": CRIAR_INTERNO_NEGADO})
        assert _foto(sessao) == antes


@pytest.mark.usefixtures("configurar")
class TestAuthMe:
    @pytest.mark.parametrize("quem", sorted(SERVICOS))
    def test_toda_conta_de_servico_recebe_false(self, cliente, como, quem):
        resposta = cliente.get(f"{API}/auth/me", headers=como(quem))
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["integra_equipe_ti"] is False
        assert set(corpo) == {"id", "nome", "setor_id", "role_id", "ativo", "integra_equipe_ti"}

    @pytest.mark.parametrize("quem,esperado", [("tecnico_ti", True), ("admin", True), ("tecnico_qualidade", False)])
    def test_pessoas_nao_mudam(self, cliente, como, quem, esperado):
        assert cliente.get(f"{API}/auth/me", headers=como(quem)).json()["integra_equipe_ti"] is esperado


@pytest.mark.usefixtures("configurar", "saidas")
class TestAdministracao:
    @pytest.mark.parametrize("metodo,rota,corpo", ROTAS_DA_EQUIPE)
    @pytest.mark.parametrize("quem", SERVICOS_NAO_ADMIN)
    def test_conta_de_servico_nao_administra(self, cliente, como, sessao, quem, metodo, rota, corpo):
        antes = _foto(sessao)
        resposta = _pedir(cliente, metodo, rota, corpo, como(quem))
        assert (resposta.status_code, resposta.json()) == (403, NEGADO)
        assert _foto(sessao) == antes

    @pytest.mark.parametrize("metodo,rota,corpo", ROTAS_DA_EQUIPE)
    @pytest.mark.parametrize("quem", ["admin", "tecnico_ti"])
    def test_pessoas_continuam_administrando(self, cliente, como, quem, metodo, rota, corpo):
        resposta = _pedir(cliente, metodo, rota, corpo, como(quem))
        assert resposta.status_code in (200, 201), (resposta.status_code, resposta.text)

    def test_sem_autenticacao_continua_401(self, cliente):
        assert cliente.get(f"{API}/tarefas-recorrentes/").status_code == 401


@pytest.mark.usefixtures("configurar", "saidas")
class TestComentariosInternos:
    def _lista(self, cliente, como, quem, cid):
        return cliente.get(f"{API}/comentarios/chamado/{cid}", headers=como(quem))

    @pytest.mark.parametrize("quem,cid", [
        ("servico_tecnico_ti", CHAMADO_TI),  # lê pelo perfil da TI
        ("servico_tecnico_qualidade", CHAMADOS["q_atribuido"]),  # lê pelo perfil da Qualidade
        ("servico_tecnico_outro", CHAMADOS["ti_arquivado"]),  # responsável atual
        ("servico_usuario_ti", CHAMADOS["ti_cancelado"]),  # solicitante
    ])
    def test_le_o_chamado_mas_so_o_publico(self, cliente, como, sessao, quem, cid):
        assert cliente.get(f"{API}/chamados/{cid}", headers=como(quem)).status_code == 200
        lista = self._lista(cliente, como, quem, cid)
        assert lista.status_code == 200
        assert lista.json() and not any(c["is_interno"] for c in lista.json())
        inexistente = cliente.get(f"{API}/comentarios/999999", headers=como(quem))
        interno = cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=como(quem))
        assert (interno.status_code, interno.json()) == (404, inexistente.json())
        antes = _foto(sessao)
        criar = cliente.post(f"{API}/comentarios/", headers=como(quem), json={
            "chamado_id": cid, "comentario": "Interno indevido", "is_interno": True,
        })
        assert (criar.status_code, criar.json()) == (403, {"detail": CRIAR_INTERNO_NEGADO})
        assert _foto(sessao) == antes

    def test_o_publico_continua(self, cliente, como):
        resposta = cliente.post(f"{API}/comentarios/", headers=como("servico_tecnico_ti"), json={
            "chamado_id": CHAMADO_TI, "comentario": "Público do painel",
        })
        assert resposta.status_code == 201
        assert resposta.json()["is_interno"] is False

    @pytest.mark.parametrize("metodo,corpo", [
        ("GET", None), ("PUT", {"comentario": "Editado"}), ("PUT", {"is_interno": False}), ("DELETE", None),
    ])
    def test_o_proprio_interno_fica_fora_de_alcance(self, cliente, como, sessao, metodo, corpo):
        """Autora ou não: sem a permissão do interno, 404 — e o interno não vira público."""
        antes = _foto(sessao)
        resposta = _pedir(cliente, metodo, f"/comentarios/{INTERNO_DO_SERVICO}", corpo, como("servico_tecnico_ti"))
        assert (resposta.status_code, resposta.json()) == (404, {"detail": COMENTARIO_NAO_ENCONTRADO})
        assert _foto(sessao) == antes

    def test_chamado_fora_de_alcance_e_404_antes_do_interno(self, cliente, como, sessao):
        antes = _foto(sessao)
        h = como("servico_tecnico_sem_setor")
        cid = CHAMADOS["ti_do_solicitante"]
        assert self._lista(cliente, como, "servico_tecnico_sem_setor", cid).status_code == 404
        criar = cliente.post(f"{API}/comentarios/", headers=h, json={
            "chamado_id": cid, "comentario": "x", "is_interno": True,
        })
        assert criar.status_code == 404
        assert _foto(sessao) == antes

    def test_pessoas_da_ti_continuam(self, cliente, como):
        for quem in ("admin", "tecnico_ti"):
            lista = self._lista(cliente, como, quem, CHAMADO_TI).json()
            assert any(c["id"] == INTERNO_DO_SERVICO for c in lista)
            criar = cliente.post(f"{API}/comentarios/", headers=como(quem), json={
                "chamado_id": CHAMADO_TI, "comentario": f"Interno de {quem}", "is_interno": True,
            })
            assert criar.status_code == 201


@pytest.mark.usefixtures("configurar", "saidas")
class TestResponsaveisDaTI:
    def test_a_lista_nao_traz_conta_de_servico(self, cliente, como):
        for quem in ("admin", "tecnico_ti", "servico_admin_ti"):
            resposta = cliente.get(f"{API}/chamados/responsaveis-ti", headers=como(quem))
            assert resposta.status_code == 200
            ids = [x["id"] for x in resposta.json()]
            assert not set(ids) & {v[0] for v in SERVICOS.values()}
            assert {20, 56} <= set(ids)
            assert all(set(x) == {"id", "nome"} for x in resposta.json())

    @pytest.mark.parametrize("alvo", sorted(SERVICOS))
    def test_put_recusa_conta_de_servico(self, cliente, como, sessao, alvo):
        antes = _foto(sessao)
        resposta = cliente.put(f"{API}/chamados/{CHAMADO_TI}", headers=como("tecnico_ti"),
                               json={"tecnico_responsavel_id": SERVICOS[alvo][0]})
        assert (resposta.status_code, resposta.json()) == (400, {"detail": CONTA_DE_SERVICO})
        assert _foto(sessao) == antes

    def test_conta_de_servico_nao_se_autoatribui(self, cliente, como, sessao):
        antes = _foto(sessao)
        resposta = cliente.put(f"{API}/chamados/{CHAMADO_TI}", headers=como("servico_tecnico_ti"),
                               json={"tecnico_responsavel_id": 70})
        assert (resposta.status_code, resposta.json()) == (400, {"detail": CONTA_DE_SERVICO})
        assert _foto(sessao) == antes

    def test_pessoa_elegivel_continua_aceita(self, cliente, como):
        resposta = cliente.put(f"{API}/chamados/{CHAMADO_TI}", headers=como("tecnico_ti"),
                               json={"tecnico_responsavel_id": 56})
        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] == 56


@pytest.mark.usefixtures("configurar", "saidas")
class TestPendenciaContaDeServicoAdministradora:
    """
    Registro, não aprovação: a C1 não muda o perfil de administrador. A conta
    de serviço administradora não integra a equipe (`/auth/me` false), mas
    tudo que as rotas dão ao administrador pelo perfil ela mantém.
    """

    def test_auth_me_false(self, cliente, como):
        assert cliente.get(f"{API}/auth/me", headers=como("servico_admin_ti")).json()["integra_equipe_ti"] is False

    @pytest.mark.parametrize("metodo,rota,corpo", ROTAS_DA_EQUIPE + [("GET", "/eventos/?alvo=usuario", None)])
    def test_mantem_a_administracao_pelo_perfil(self, cliente, como, metodo, rota, corpo):
        assert _pedir(cliente, metodo, rota, corpo, como("servico_admin_ti")).status_code in (200, 201)

    def test_mantem_o_interno_pelo_perfil(self, cliente, como):
        lista = cliente.get(f"{API}/comentarios/chamado/{CHAMADO_TI}", headers=como("servico_admin_ti")).json()
        assert any(c["is_interno"] for c in lista)
        criar = cliente.post(f"{API}/comentarios/", headers=como("servico_admin_ti"), json={
            "chamado_id": CHAMADO_TI, "comentario": "Interno da conta administradora", "is_interno": True,
        })
        assert criar.status_code == 201

    def test_mantem_a_gestao_de_usuarios(self, cliente, como):
        assert cliente.get(f"{API}/usuarios/{20}/eventos", headers=como("servico_admin_ti")).status_code == 200


@pytest.mark.usefixtures("configurar", "saidas")
class TestPendenciaAlcanceDePerfil:
    """
    Registro, não aprovação: a leitura (API-5) e a escrita de equipe (API-6)
    por alcance de perfil usam `setores_lidos_pelo_perfil`, que não passa por
    `integra_equipe_ti`. A leitura é a do painel de parede (migration de
    `conta_de_servico`); a escrita não tem uso documentado.
    """

    def test_tecnica_da_ti_le_os_chamados_da_ti(self, cliente, como):
        ids = {c["id"] for c in cliente.get(f"{API}/chamados/", headers=como("servico_tecnico_ti")).json()}
        assert {CHAMADOS["ti_do_solicitante"], CHAMADO_TI} <= ids

    def test_tecnica_da_ti_ainda_altera_como_equipe(self, cliente, como, sessao):
        resposta = cliente.put(f"{API}/chamados/{CHAMADO_TI}", headers=como("servico_tecnico_ti"),
                               json={"prioridade": "Alta"})
        assert resposta.status_code == 200
        assert resposta.json()["prioridade"] == "Alta"
