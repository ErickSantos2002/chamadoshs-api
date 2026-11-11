"""
Conta de serviço administradora não administra (API-11, decisão S3).

A auditoria pós-API-10 achou o que a conta compartilhada de administração
fazia só pelo perfil: resetava a senha de qualquer conta, trocava perfil,
setor e a marca de conta de serviço, desativava pessoas, excluía chamado de
vez, lia o diagnóstico, administrava setores, categorias, SLA e tarefas, e
via e criava comentário interno — com a trilha dizendo "foi a conta", não
quem. Agora `require_admin` e `require_equipe_ti` querem o administrador
humano (`is_admin_humano`), e o mesmo vale para o interno, para mexer em
comentário alheio e para abrir chamado em nome de outro.

Ela continua autenticando, trocando a própria senha e lendo — o painel de
parede pode ser uma. Cada recusa sai sem efeito no banco.
"""

from datetime import date

import pytest
from sqlalchemy import text

from app.api.deps import CONTA_DE_SERVICO_SEM_ADMINISTRACAO, EQUIPE_TI_NEGADA
from app.core.security import gerar_hash_senha
from app.models import Categoria, Chamado, Setor, Usuario
from app.models.comentario import ComentarioChamado
from app.models.evento_conta import EventoDeConta
from app.models.evento_setor import EventoDeSetor
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.models.tarefa_recorrente import TarefaRecorrente, TarefaRecorrenteExecucao
from leitura_cenario import CHAMADOS, comentario_publico, cenario_de_leitura  # noqa: F401
from test_conta_de_servico_rotas import como, configurar, saidas, servicos  # noqa: F401

API = "/api/v1"
SERVICO_ADMIN = 75
COMUM = 30
INATIVO = 42  # conftest, fixture `qualidade`: conta desativada
TAREFA = 900
SETOR_VAZIO = 5  # sem ninguém: dá para desativar
CATEGORIA_SEM_USO = 9  # sem chamado: dá para excluir
SENHA_DO_SERVICO = "senha-ficticia-do-painel-123"
SO_ADMIN = {"detail": CONTA_DE_SERVICO_SEM_ADMINISTRACAO}
SO_EQUIPE = {"detail": EQUIPE_TI_NEGADA}

# As rotas só do administrador (`require_admin`), cada uma com um alvo que
# existe — a recusa não pode depender de 404.
SO_DO_ADMINISTRADOR = {
    "registro": ("POST", "/auth/registro", {"nome": "nova.pessoa", "senha": "x" * 12, "role_id": 3}),
    "criar_usuario": ("POST", "/usuarios/", {"nome": "nova.pessoa", "senha": "x" * 12, "role_id": 1}),
    "resetar_senha_alheia": ("PUT", f"/usuarios/{COMUM}", {"senha": "tomada-de-conta-123"}),
    "trocar_perfil": ("PUT", f"/usuarios/{COMUM}", {"role_id": 1}),
    "trocar_setor": ("PUT", f"/usuarios/{COMUM}", {"setor_id": 2}),
    "marcar_como_servico": ("PUT", f"/usuarios/{COMUM}", {"conta_de_servico": True}),
    "desmarcar_a_si_mesma": ("PUT", f"/usuarios/{SERVICO_ADMIN}", {"conta_de_servico": False}),
    "desativar_pelo_put": ("PUT", f"/usuarios/{COMUM}", {"ativo": False}),
    "desativar": ("PATCH", f"/usuarios/{COMUM}/desativar", None),
    "reativar": ("PATCH", f"/usuarios/{INATIVO}/reativar", None),
    "excluir_usuario": ("DELETE", f"/usuarios/{COMUM}", None),
    "eventos_de_usuario": ("GET", f"/usuarios/{COMUM}/eventos", None),
    "excluir_chamado": ("DELETE", f"/chamados/{CHAMADOS['ti_sem_responsavel']}", None),
    "excluir_setor": ("DELETE", "/setores/3", None),
    "diagnostico": ("GET", "/diagnostico/", None),
    "usuarios_sem_senha": ("GET", "/diagnostico/usuarios-sem-senha", None),
}

# As rotas da equipe (`require_equipe_ti`): o administrador passava pelo perfil.
DA_EQUIPE = {
    "listar_tarefas": ("GET", "/tarefas-recorrentes/", None),
    "buscar_tarefa": ("GET", f"/tarefas-recorrentes/{TAREFA}", None),
    "criar_tarefa": ("POST", "/tarefas-recorrentes/", {"titulo": "Rotina nova", "tipo_recorrencia": "diaria"}),
    "editar_tarefa": ("PUT", f"/tarefas-recorrentes/{TAREFA}", {"titulo": "Rotina renomeada"}),
    "excluir_tarefa": ("DELETE", f"/tarefas-recorrentes/{TAREFA}", None),
    "execucoes": ("GET", f"/tarefas-recorrentes/{TAREFA}/execucoes", None),
    "realizar_tarefa": ("POST", f"/tarefas-recorrentes/{TAREFA}/realizar", {}),
    "criar_setor": ("POST", "/setores/", {"nome": "Setor novo", "descricao": "não deve existir"}),
    "editar_setor": ("PUT", "/setores/4", {"nome": "Comercial renomeado"}),
    "desativar_setor": ("PATCH", f"/setores/{SETOR_VAZIO}/desativar", None),
    "reativar_setor": ("PATCH", "/setores/3/reativar", None),
    "criar_categoria": ("POST", "/categorias/", {"nome": "Categoria nova", "descricao": "não deve existir"}),
    "editar_categoria": ("PUT", "/categorias/1", {"nome": "Categoria renomeada"}),
    "excluir_categoria": ("DELETE", f"/categorias/{CATEGORIA_SEM_USO}", None),
    "sla": ("PUT", "/sla-configs/Alta", {"minutos_resposta": 1, "minutos_resolucao": 2}),
    "trilha": ("GET", "/eventos/", None),
    "trilha_de_usuario": ("GET", "/eventos/?alvo=usuario", None),
    "responsaveis_ti": ("GET", "/chamados/responsaveis-ti", None),
}


@pytest.fixture
def cenario(servicos, sessao):
    sessao.add(Setor(id=SETOR_VAZIO, nome="Setor vazio", descricao="Sem pessoas", ativo=True))
    sessao.add(Categoria(id=CATEGORIA_SEM_USO, nome="Categoria sem uso", descricao="Sem chamados"))
    sessao.add(TarefaRecorrente(
        id=TAREFA, titulo="Backup do servidor", descricao="Conferir o backup", tipo_recorrencia="diaria",
        intervalo=1, proxima_data=date(2026, 11, 3), ativo=True,
    ))
    sessao.get(Usuario, SERVICO_ADMIN).senha_hash = gerar_hash_senha(SENHA_DO_SERVICO)
    sessao.commit()
    if sessao.bind.dialect.name == "postgresql":
        # Os ids acima são explícitos e vêm depois do acerto de `servicos`.
        for tabela in ("setores", "categorias", "tarefas_recorrentes"):
            sessao.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), (SELECT MAX(id) FROM {tabela}))"
            ))
        sessao.commit()
    return servicos


def _foto(sessao):
    sessao.expire_all()
    return {
        "usuarios": sorted(
            (u.id, u.nome, u.senha_hash, u.role_id, u.setor_id, u.ativo, u.conta_de_servico)
            for u in sessao.query(Usuario)
        ),
        "eventos_de_conta": sessao.query(EventoDeConta).count(),
        "eventos_de_setor": sessao.query(EventoDeSetor).count(),
        "chamados": sorted((c.id, c.solicitante_id, c.versao) for c in sessao.query(Chamado)),
        "historico": sessao.query(HistoricoChamado).count(),
        "comentarios": sorted((c.id, c.comentario, c.is_interno) for c in sessao.query(ComentarioChamado)),
        "setores": sorted((s.id, s.nome, s.ativo) for s in sessao.query(Setor)),
        "categorias": sorted((c.id, c.nome) for c in sessao.query(Categoria)),
        "sla": sorted((c.prioridade, c.minutos_resposta, c.minutos_resolucao) for c in sessao.query(SLAConfig)),
        "tarefas": sorted((t.id, t.titulo, t.proxima_data, t.ativo) for t in sessao.query(TarefaRecorrente)),
        "execucoes": sessao.query(TarefaRecorrenteExecucao).count(),
    }


def _pedir(cliente, metodo, rota, corpo, headers):
    return cliente.request(metodo, f"{API}{rota}", headers=headers, json=corpo)


@pytest.mark.usefixtures("configurar", "saidas", "cenario")
class TestNaoAdministra:
    @pytest.mark.parametrize("chave", sorted(SO_DO_ADMINISTRADOR))
    def test_rotas_do_administrador(self, cliente, como, sessao, chave):
        metodo, rota, corpo = SO_DO_ADMINISTRADOR[chave]
        antes = _foto(sessao)
        resposta = _pedir(cliente, metodo, rota, corpo, como("servico_admin_ti"))
        assert (resposta.status_code, resposta.json()) == (403, SO_ADMIN)
        assert _foto(sessao) == antes

    @pytest.mark.parametrize("chave", sorted(DA_EQUIPE))
    def test_rotas_da_equipe(self, cliente, como, sessao, chave):
        metodo, rota, corpo = DA_EQUIPE[chave]
        antes = _foto(sessao)
        resposta = _pedir(cliente, metodo, rota, corpo, como("servico_admin_ti"))
        assert (resposta.status_code, resposta.json()) == (403, SO_EQUIPE)
        assert _foto(sessao) == antes

    def test_nao_mexe_em_comentario_alheio(self, cliente, como, sessao):
        cid = comentario_publico(CHAMADOS["ti_do_solicitante"])
        antes = _foto(sessao)
        h = como("servico_admin_ti")
        editar = cliente.put(f"{API}/comentarios/{cid}", headers=h, json={"comentario": "Reescrito pela conta"})
        excluir = cliente.delete(f"{API}/comentarios/{cid}", headers=h)
        assert (editar.status_code, excluir.status_code) == (403, 403)
        assert _foto(sessao) == antes

    def test_nao_abre_em_nome_de_outro(self, cliente, como):
        resposta = cliente.post(f"{API}/chamados/", headers=como("servico_admin_ti"), json={
            "titulo": "Aberto pela conta", "descricao": "Em nome de outra pessoa, de propósito",
            "solicitante_id": COMUM,
        })
        assert resposta.status_code == 201
        assert resposta.json()["solicitante_id"] == SERVICO_ADMIN

    def test_nao_ve_o_interno(self, cliente, como):
        lista = cliente.get(f"{API}/comentarios/chamado/{CHAMADOS['ti_do_solicitante']}",
                            headers=como("servico_admin_ti")).json()
        assert lista and not any(c["is_interno"] for c in lista)


@pytest.mark.usefixtures("configurar", "saidas", "cenario")
class TestOQueContinua:
    def test_autentica_pela_rota_de_sempre(self, cliente):
        resposta = cliente.post(f"{API}/auth/login", json={"nome": "servico.admin.ti", "senha": SENHA_DO_SERVICO})
        assert resposta.status_code == 200
        me = cliente.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {resposta.json()['access_token']}"})
        assert me.status_code == 200 and me.json()["integra_equipe_ti"] is False

    def test_le_todos_os_chamados_e_os_cadastros(self, cliente, como):
        h = como("servico_admin_ti")
        ids = {c["id"] for c in cliente.get(f"{API}/chamados/?incluir_arquivados=true&incluir_cancelados=true",
                                           headers=h).json()}
        assert set(CHAMADOS.values()) <= ids
        for rota in ("/usuarios/", "/setores/", "/categorias/", "/sla-configs/"):
            assert cliente.get(f"{API}{rota}", headers=h).status_code == 200, rota

    def test_troca_a_propria_senha(self, cliente, como, sessao):
        resposta = cliente.post(f"{API}/auth/alterar-senha", headers=como("servico_admin_ti"),
                                json={"senha_atual": SENHA_DO_SERVICO, "senha_nova": "outra-senha-ficticia-456"})
        assert resposta.status_code == 200
        login = cliente.post(f"{API}/auth/login", json={"nome": "servico.admin.ti",
                                                       "senha": "outra-senha-ficticia-456"})
        assert login.status_code == 200


@pytest.mark.usefixtures("configurar", "saidas", "cenario")
class TestAdministradorHumano:
    """O mesmo pedido, pelo administrador humano: passa."""

    @pytest.mark.parametrize("chave", sorted(set(SO_DO_ADMINISTRADOR) - {"desmarcar_a_si_mesma"}))
    def test_rotas_do_administrador(self, cliente, como, chave):
        metodo, rota, corpo = SO_DO_ADMINISTRADOR[chave]
        resposta = _pedir(cliente, metodo, rota, corpo, como("admin"))
        assert resposta.status_code in (200, 201, 204), (resposta.status_code, resposta.text)

    @pytest.mark.parametrize("chave", sorted(DA_EQUIPE))
    def test_rotas_da_equipe(self, cliente, como, chave):
        metodo, rota, corpo = DA_EQUIPE[chave]
        resposta = _pedir(cliente, metodo, rota, corpo, como("admin"))
        assert resposta.status_code in (200, 201, 204), (resposta.status_code, resposta.text)

    def test_ve_o_interno_e_abre_em_nome_de_outro(self, cliente, como):
        lista = cliente.get(f"{API}/comentarios/chamado/{CHAMADOS['ti_do_solicitante']}", headers=como("admin")).json()
        assert any(c["is_interno"] for c in lista)
        aberto = cliente.post(f"{API}/chamados/", headers=como("admin"), json={
            "titulo": "Aberto pelo administrador", "descricao": "Em nome da pessoa que ligou",
            "solicitante_id": COMUM,
        })
        assert aberto.status_code == 201 and aberto.json()["solicitante_id"] == COMUM
