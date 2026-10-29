"""
A administração global por perfil e configuração (API-7, D13).

Até a API-6, setores, categorias, SLA, tarefas e eventos usavam `require_staff`: técnico de
qualquer setor os administrava — o da Qualidade, o de outro setor, o sem
setor. Agora é `require_equipe_ti` (administrador ou técnico da TI), e a
exclusão de setor é só do administrador (A7-1).

Tarefas recorrentes (as sete rotas) e a trilha de setor seguem a mesma
regra (A7-4): também a leitura.

A matriz é perfil × configuração × rota. Em cada caso, quem pode recebe o
status de sempre e a escrita acontece; quem não pode recebe o 403 de sempre
e o banco fica como estava — nenhuma linha muda, nenhum evento é gravado e
nenhuma requisição sai para fora.

As leituras (GET de setores, categorias e SLA) seguem abertas a qualquer
conta autenticada: o formulário de abertura de chamado depende delas.
"""

import pytest
import requests
from sqlalchemy import text

import main
from app.api.deps import EQUIPE_TI_NEGADA
from app.models import Categoria, Role, Setor, Usuario
from app.models.evento_setor import EventoDeSetor
from app.models.sla_config import SLAConfig
from app.models.tarefa_recorrente import TarefaRecorrente, TarefaRecorrenteExecucao
from leitura_cenario import ROLE_DE, cenario_de_leitura  # noqa: F401

API = "/api/v1"
NEGADO = {"detail": EQUIPE_TI_NEGADA}
# O 403 de `require_admin`, o mesmo das rotas de usuário.
SO_ADMINISTRADOR = {"detail": "Requer perfil: Administrador"}

PERFIL_DESCONHECIDO = 60
CONTA_DE_SERVICO_TI = 61
SETOR_VAZIO = 5
SETOR_PARA_EXCLUIR = 6
CATEGORIA_SEM_USO = 2

# Quem pode, com `SETORES_TI_IDS` válida ("1"). Administrador passa pelo
# perfil, em qualquer setor; técnico, só no setor da TI.
ADMINISTRADORES = {"admin", "admin_da_qualidade"}
TECNICOS_DA_TI = {"tecnico_ti", "conta_de_servico_ti"}
PERFIS = [
    "admin",
    "admin_da_qualidade",
    "tecnico_ti",
    "conta_de_servico_ti",
    "tecnico_qualidade",
    "tecnico_outro_setor",
    "tecnico_sem_setor",
    "solicitante",
    "atendente",
    "perfil_desconhecido",
]

# (nome, método, rota, corpo, status de quem pode, quem pode)
#   quem pode: "ti" = administrador ou técnico da TI; "admin" = só administrador.
OPERACOES = [
    ("setor_criar", "POST", "/setores/", {"nome": "Logística"}, 201, "ti"),
    ("setor_editar", "PUT", "/setores/4", {"nome": "Comercial e Vendas"}, 200, "ti"),
    ("setor_desativar", "PATCH", f"/setores/{SETOR_VAZIO}/desativar", None, 200, "ti"),
    ("setor_reativar", "PATCH", "/setores/3/reativar", None, 200, "ti"),
    ("setor_excluir", "DELETE", f"/setores/{SETOR_PARA_EXCLUIR}", None, 204, "admin"),
    ("categoria_criar", "POST", "/categorias/", {"nome": "Rede"}, 201, "ti"),
    ("categoria_editar", "PUT", "/categorias/1", {"nome": "Hardware e periféricos"}, 200, "ti"),
    ("categoria_excluir", "DELETE", f"/categorias/{CATEGORIA_SEM_USO}", None, 204, "ti"),
    ("sla_editar", "PUT", "/sla-configs/Alta", {"minutos_resposta": 15, "minutos_resolucao": 120}, 200, "ti"),
    # As sete de tarefas recorrentes, leitura incluída (A7-4).
    ("tarefa_listar", "GET", "/tarefas-recorrentes/", None, 200, "ti"),
    ("tarefa_detalhe", "GET", "/tarefas-recorrentes/200", None, 200, "ti"),
    ("tarefa_criar", "POST", "/tarefas-recorrentes/", {
        "titulo": "Conferir nobreak", "tipo_recorrencia": "mensal", "dia_mes": 5, "proxima_data": "2026-11-05",
    }, 201, "ti"),
    ("tarefa_editar", "PUT", "/tarefas-recorrentes/200", {"titulo": "Backup semanal completo"}, 200, "ti"),
    ("tarefa_excluir", "DELETE", "/tarefas-recorrentes/200", None, 204, "ti"),
    ("tarefa_execucoes", "GET", "/tarefas-recorrentes/200/execucoes", None, 200, "ti"),
    ("tarefa_realizar", "POST", "/tarefas-recorrentes/200/realizar", {"observacao": "Feito no teste"}, 200, "ti"),
    # A trilha de setor (A7-4).
    ("eventos_listar", "GET", "/eventos/", None, 200, "ti"),
]
LEITURAS = {nome for nome, metodo, *_ in OPERACOES if metodo == "GET"}

# SETORES_TI_IDS → se o técnico do setor 1 é da TI.
CONFIGURACOES = {
    "valida": ("1", True),
    "ausente": (None, False),
    "vazia": ("", False),
    "invalida": ("1,x", False),
    "com_duplicidade": ("1,1", True),
    "conflitante_com_qualidade": ("1,2", True),
}


@pytest.fixture
def administracao(cenario_de_leitura, sessao):
    """O cenário de leitura, mais as contas e os alvos que a matriz usa."""
    sessao.add(Role(id=4, nome="Auditor"))
    sessao.add_all([
        Setor(id=SETOR_VAZIO, nome="Almoxarifado", ativo=True),
        Setor(id=SETOR_PARA_EXCLUIR, nome="Projeto Encerrado", ativo=True),
        Categoria(id=CATEGORIA_SEM_USO, nome="Sem uso"),
    ])
    # merge: o schema do PostgreSQL já semeia os prazos; o SQLite não.
    sessao.merge(SLAConfig(prioridade="Alta", minutos_resposta=30, minutos_resolucao=240))
    sessao.flush()
    sessao.add_all([
        Usuario(id=PERFIL_DESCONHECIDO, nome="auditor.ti", role_id=4, setor_id=1, ativo=True),
        Usuario(
            id=CONTA_DE_SERVICO_TI, nome="painel.ti", role_id=2, setor_id=1, ativo=True, conta_de_servico=True,
        ),
    ])
    sessao.commit()
    if sessao.bind.dialect.name == "postgresql":
        # Os ids acima são explícitos; sem isto o POST seguinte pegaria o 1.
        for tabela in ("setores", "categorias", "tarefas_recorrentes"):
            sessao.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), (SELECT MAX(id) FROM {tabela}))"
            ))
        sessao.commit()
    return {
        **cenario_de_leitura,
        "perfil_desconhecido": PERFIL_DESCONHECIDO,
        "conta_de_servico_ti": CONTA_DE_SERVICO_TI,
    }


@pytest.fixture
def como(autenticar, administracao):
    def _como(quem):
        return autenticar(administracao[quem], quem, ROLE_DE.get(quem, "Usuario"))

    return _como


@pytest.fixture
def saidas(monkeypatch):
    """Toda requisição para fora vira registro: a recusa não pode chamar ninguém."""
    chamadas = []

    def _registrar(*args, **kwargs):
        chamadas.append((args, kwargs))
        raise AssertionError("requisição externa num teste de permissão")

    monkeypatch.setattr(requests, "post", _registrar)
    monkeypatch.setattr(requests.Session, "request", _registrar)
    return chamadas


@pytest.fixture
def configurar(monkeypatch):
    def _configurar(configuracao):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", CONFIGURACOES[configuracao][0])

    return _configurar


def _foto(sessao):
    """Tudo que as rotas administrativas escrevem."""
    sessao.expire_all()
    return {
        "setores": sorted((s.id, s.nome, s.descricao, s.ativo) for s in sessao.query(Setor)),
        "categorias": sorted((c.id, c.nome, c.descricao, c.ativo) for c in sessao.query(Categoria)),
        "sla": sorted((c.prioridade, c.minutos_resposta, c.minutos_resolucao) for c in sessao.query(SLAConfig)),
        "tarefas": sorted(
            (t.id, t.titulo, t.proxima_data, t.ativo, t.prioridade) for t in sessao.query(TarefaRecorrente)
        ),
        "execucoes": sessao.query(TarefaRecorrenteExecucao).count(),
        "eventos_de_setor": sessao.query(EventoDeSetor).count(),
    }


def _pedir(cliente, metodo, rota, corpo, headers):
    return cliente.request(metodo, f"{API}{rota}", headers=headers, json=corpo)


def _pode(quem, nivel, configuracao):
    if quem in ADMINISTRADORES:
        return True
    return nivel == "ti" and quem in TECNICOS_DA_TI and CONFIGURACOES[configuracao][1]


def _conferir(cliente, sessao, como, quem, operacao, configuracao):
    nome, metodo, rota, corpo, sucesso, nivel = operacao
    antes = _foto(sessao)
    resposta = _pedir(cliente, metodo, rota, corpo, como(quem))
    depois = _foto(sessao)
    if _pode(quem, nivel, configuracao):
        assert resposta.status_code == sucesso, resposta.text
        if nome in LEITURAS:
            assert depois == antes
        else:
            assert depois != antes, "a operação permitida não escreveu nada"
    else:
        assert resposta.status_code == 403, resposta.text
        assert resposta.json() == (NEGADO if nivel == "ti" else SO_ADMINISTRADOR)
        assert depois == antes


IDS = [o[0] for o in OPERACOES]


@pytest.mark.parametrize("operacao", OPERACOES, ids=IDS)
@pytest.mark.parametrize("quem", PERFIS)
def test_matriz_com_configuracao_valida(cliente, sessao, como, configurar, saidas, quem, operacao):
    configurar("valida")
    _conferir(cliente, sessao, como, quem, operacao, "valida")
    assert saidas == []


@pytest.mark.parametrize("operacao", OPERACOES, ids=IDS)
@pytest.mark.parametrize("quem", ["admin", "tecnico_ti", "tecnico_qualidade", "tecnico_outro_setor", "tecnico_sem_setor"])
@pytest.mark.parametrize("configuracao", [c for c in CONFIGURACOES if c != "valida"])
def test_matriz_por_configuracao(cliente, sessao, como, configurar, saidas, configuracao, quem, operacao):
    """Configuração ausente, vazia ou inválida não dá acesso a técnico nenhum; a do administrador fica."""
    configurar(configuracao)
    _conferir(cliente, sessao, como, quem, operacao, configuracao)
    assert saidas == []


@pytest.mark.parametrize("operacao", OPERACOES, ids=IDS)
def test_sem_token_continua_401(cliente, sessao, administracao, operacao):
    _, metodo, rota, corpo, _, _ = operacao
    antes = _foto(sessao)
    resposta = _pedir(cliente, metodo, rota, corpo, {})
    assert resposta.status_code == 401
    assert _foto(sessao) == antes


@pytest.mark.parametrize("operacao", OPERACOES, ids=IDS)
def test_token_invalido_continua_401(cliente, sessao, administracao, operacao):
    _, metodo, rota, corpo, _, _ = operacao
    resposta = _pedir(cliente, metodo, rota, corpo, {"Authorization": "Bearer nao-e-um-token"})
    assert resposta.status_code == 401


@pytest.mark.parametrize("rota", ["/setores/", "/setores/1", "/categorias/", "/categorias/1", "/sla-configs/"])
@pytest.mark.parametrize("quem", PERFIS)
def test_leituras_de_cadastro_seguem_abertas(cliente, como, configurar, quem, rota):
    """Mesmo sem lista da TI: o formulário de abertura de chamado lê daqui."""
    configurar("ausente")
    assert cliente.get(f"{API}{rota}", headers=como(quem)).status_code == 200


class TestRegrasDeSempre:
    """A troca de dependência não mexe no que a rota já recusava por outro motivo."""

    def test_setor_com_usuarios_ativos_nao_desativa(self, cliente, como, configurar):
        configurar("valida")
        resposta = cliente.patch(f"{API}/setores/4/desativar", headers=como("tecnico_ti"))
        assert resposta.status_code == 400

    def test_setor_com_vinculo_nao_e_excluido_nem_pelo_administrador(self, cliente, sessao, como, configurar):
        configurar("valida")
        antes = _foto(sessao)
        resposta = cliente.delete(f"{API}/setores/4", headers=como("admin"))
        assert resposta.status_code == 400
        assert _foto(sessao) == antes

    def test_categoria_com_chamado_nao_e_excluida(self, cliente, como, configurar):
        configurar("valida")
        assert cliente.delete(f"{API}/categorias/1", headers=como("tecnico_ti")).status_code == 400

    def test_prioridade_inexistente_continua_404(self, cliente, como, configurar):
        configurar("valida")
        resposta = cliente.put(
            f"{API}/sla-configs/Inexistente", headers=como("tecnico_ti"),
            json={"minutos_resposta": 15, "minutos_resolucao": 120},
        )
        assert resposta.status_code == 404

    def test_prazo_invalido_continua_422(self, cliente, como, configurar):
        configurar("valida")
        resposta = cliente.put(
            f"{API}/sla-configs/Alta", headers=como("tecnico_ti"),
            json={"minutos_resposta": 0, "minutos_resolucao": 120},
        )
        assert resposta.status_code == 422

    def test_criacao_de_setor_segue_gravando_o_evento(self, cliente, sessao, como, configurar):
        configurar("valida")
        antes = _foto(sessao)["eventos_de_setor"]
        assert cliente.post(f"{API}/setores/", headers=como("tecnico_ti"), json={"nome": "Logística"}).status_code == 201
        assert _foto(sessao)["eventos_de_setor"] == antes + 1

    def test_tecnico_da_qualidade_nao_administra_o_proprio_setor(self, cliente, sessao, como, configurar, administracao):
        configurar("valida")
        setor = administracao["setor_qualidade_id"]
        antes = _foto(sessao)
        for metodo, rota, corpo in [
            ("PUT", f"/setores/{setor}", {"nome": "Qualidade renomeada"}),
            ("PATCH", f"/setores/{setor}/desativar", None),
            ("PATCH", f"/setores/{setor}/reativar", None),
        ]:
            resposta = _pedir(cliente, metodo, rota, corpo, como("tecnico_qualidade"))
            assert (resposta.status_code, resposta.json()) == (403, NEGADO), rota
        resposta = cliente.delete(f"{API}/setores/{setor}", headers=como("tecnico_qualidade"))
        assert (resposta.status_code, resposta.json()) == (403, SO_ADMINISTRADOR)
        assert _foto(sessao) == antes


class TestTarefas:
    def test_quem_realizou_continua_vindo_do_token(self, cliente, sessao, como, configurar, administracao):
        configurar("valida")
        resposta = cliente.post(
            f"{API}/tarefas-recorrentes/200/realizar", headers=como("tecnico_ti"),
            json={"usuario_id": administracao["admin"], "observacao": "Feito"},
        )
        assert resposta.status_code == 200, resposta.text
        sessao.expire_all()
        execucao = sessao.query(TarefaRecorrenteExecucao).one()
        assert execucao.usuario_id == administracao["tecnico_ti"]

    def test_recusa_nao_avanca_a_proxima_data(self, cliente, sessao, como, configurar):
        configurar("valida")
        sessao.expire_all()
        antes = sessao.get(TarefaRecorrente, 200).proxima_data
        assert cliente.post(
            f"{API}/tarefas-recorrentes/200/realizar", headers=como("tecnico_qualidade"), json={},
        ).status_code == 403
        sessao.expire_all()
        assert sessao.get(TarefaRecorrente, 200).proxima_data == antes
        assert sessao.query(TarefaRecorrenteExecucao).count() == 0

    def test_tarefa_inexistente_continua_404_para_a_ti(self, cliente, como, configurar):
        configurar("valida")
        assert cliente.get(f"{API}/tarefas-recorrentes/999", headers=como("tecnico_ti")).status_code == 404

    def test_tarefa_inexistente_e_403_para_quem_nao_e_da_ti(self, cliente, como, configurar):
        """A trava vem antes da busca: o 403 não diz se a tarefa existe."""
        configurar("valida")
        for tarefa in (200, 999):
            resposta = cliente.get(f"{API}/tarefas-recorrentes/{tarefa}", headers=como("tecnico_qualidade"))
            assert (resposta.status_code, resposta.json()) == (403, NEGADO)


class TestEventos:
    """A trava nova é de entrada; o recorte por alvo continua o de antes."""

    @pytest.fixture
    def trilha(self, cliente, como, configurar, administracao):
        """Um evento de setor e um de conta, gravados pelas rotas de verdade."""
        configurar("valida")
        assert cliente.post(f"{API}/setores/", headers=como("admin"), json={"nome": "Logística"}).status_code == 201
        assert cliente.put(
            f"{API}/usuarios/{administracao['solicitante']}", headers=como("admin"), json={"nome": "usuario.renomeado"},
        ).status_code == 200

    def _tipos(self, resposta):
        assert resposta.status_code == 200, resposta.text
        return {e["alvo_tipo"] for e in resposta.json()}

    def test_administrador_ve_os_dois(self, cliente, como, trilha):
        assert self._tipos(cliente.get(f"{API}/eventos/", headers=como("admin"))) == {"usuario", "setor"}

    def test_tecnico_da_ti_ve_so_setor(self, cliente, como, trilha):
        assert self._tipos(cliente.get(f"{API}/eventos/", headers=como("tecnico_ti"))) == {"setor"}

    def test_tecnico_da_ti_continua_sem_eventos_de_conta(self, cliente, como, trilha):
        resposta = cliente.get(f"{API}/eventos/?alvo=usuario", headers=como("tecnico_ti"))
        assert resposta.status_code == 403
        assert resposta.json() == {"detail": "Requer perfil: Administrador para ver eventos de conta"}

    @pytest.mark.parametrize("alvo", ["", "?alvo=setor", "?alvo=usuario"])
    @pytest.mark.parametrize("quem", ["tecnico_qualidade", "tecnico_outro_setor", "tecnico_sem_setor", "solicitante"])
    def test_fora_da_ti_nenhum_alvo(self, cliente, como, trilha, quem, alvo):
        resposta = cliente.get(f"{API}/eventos/{alvo}", headers=como(quem))
        assert (resposta.status_code, resposta.json()) == (403, NEGADO)
