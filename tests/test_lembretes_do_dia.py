"""
`GET /tarefas-recorrentes/lembretes-do-dia` (API-11, decisão S1, parte segura).

O lembrete "tarefas do dia" do quadro lia `GET /tarefas-recorrentes/` inteiro e
filtrava no navegador, com o dia do navegador. A rota nova devolve só o que o
lembrete mostra — id, título, próxima data, situação —, com o dia de Brasília.

Quem lê é quem já lia o módulo: administrador humano e técnico da TI. Nenhuma
conta de serviço passa, nem uma com cara de painel de parede: sem um jeito
seguro de identificar a TV, a rota não abre exceção para ela (ver
docs/contas-de-servico.md). E a rota não abre nenhuma das sete do módulo.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import text

from app.api.deps import EQUIPE_TI_NEGADA
from app.api.endpoints import tarefas_recorrentes as tarefas_endpoint
from app.models import Usuario
from app.models.tarefa_recorrente import TarefaRecorrente, TarefaRecorrenteExecucao
from leitura_cenario import cenario_de_leitura  # noqa: F401
from test_conta_de_servico_rotas import SERVICOS, como, configurar, saidas, servicos  # noqa: F401

API = "/api/v1"
ROTA = f"{API}/tarefas-recorrentes/lembretes-do-dia"
NEGADO = {"detail": EQUIPE_TI_NEGADA}
HOJE = date(2026, 11, 3)
# Contas de serviço fictícias com nome de painel: nome não é identidade.
DUAS_DO_PAINEL = {"painel_tv_admin": (76, 1), "painel_tv_tecnico": (77, 2)}

# id: (título, próxima data, ativa, execuções)
TAREFAS = {
    801: ("Atrasada", date(2026, 11, 1), True, []),
    802: ("Vence hoje", HOJE, True, []),
    803: ("Feita hoje no último segundo", date(2026, 11, 4), True, [datetime(2026, 11, 3, 23, 59, 59)]),
    804: ("Futura sem execução", date(2026, 11, 10), True, []),
    805: ("Inativa atrasada", date(2026, 11, 1), False, []),
    806: ("Feita ontem", date(2026, 11, 4), True, [datetime(2026, 11, 2, 23, 59, 59)]),
    807: ("Também vence hoje", HOJE, True, []),
    808: ("Feita amanhã à meia-noite", date(2026, 11, 5), True, [datetime(2026, 11, 4, 0, 0, 0)]),
    809: ("Atrasada e feita hoje", date(2026, 10, 30), True, [datetime(2026, 11, 3, 0, 0, 0)]),
    810: ("Inativa feita hoje", date(2026, 11, 4), False, [datetime(2026, 11, 3, 9, 0, 0)]),
}
ESPERADO = [
    # A do conftest (`dados`), atrasada desde agosto.
    {"id": 200, "titulo": "Backup semanal", "proxima_data": "2026-08-10", "situacao": "atrasada"},
    {"id": 809, "titulo": "Atrasada e feita hoje", "proxima_data": "2026-10-30", "situacao": "atrasada"},
    {"id": 801, "titulo": "Atrasada", "proxima_data": "2026-11-01", "situacao": "atrasada"},
    {"id": 802, "titulo": "Vence hoje", "proxima_data": "2026-11-03", "situacao": "hoje"},
    {"id": 807, "titulo": "Também vence hoje", "proxima_data": "2026-11-03", "situacao": "hoje"},
    {"id": 803, "titulo": "Feita hoje no último segundo", "proxima_data": "2026-11-04",
     "situacao": "realizada_hoje"},
]
HUMANOS = ["admin", "admin_da_qualidade", "tecnico_ti"]
FORA_DO_MODULO = ["tecnico_qualidade", "tecnico_sem_setor", "tecnico_outro_setor", "solicitante"]

# As sete rotas do módulo: a rota nova não pode destravar nenhuma.
SETE_ROTAS = [
    ("GET", "/tarefas-recorrentes/", None),
    ("GET", "/tarefas-recorrentes/801", None),
    ("POST", "/tarefas-recorrentes/", {"titulo": "Nova", "tipo_recorrencia": "diaria", "proxima_data": "2026-11-04"}),
    ("PUT", "/tarefas-recorrentes/801", {"titulo": "Mudou"}),
    ("DELETE", "/tarefas-recorrentes/801", None),
    ("GET", "/tarefas-recorrentes/801/execucoes", None),
    ("POST", "/tarefas-recorrentes/801/realizar", {"observacao": "pelo painel"}),
]


@pytest.fixture
def tarefas(servicos, configurar, sessao, monkeypatch):
    monkeypatch.setattr(tarefas_endpoint, "_hoje", lambda: HOJE)
    for nome, (uid, role) in DUAS_DO_PAINEL.items():
        sessao.add(Usuario(id=uid, nome=nome.replace("_", "."), role_id=role, setor_id=1, ativo=True,
                           conta_de_servico=True))
    for tid, (titulo, proxima, ativa, execucoes) in TAREFAS.items():
        sessao.add(TarefaRecorrente(
            id=tid, titulo=titulo, descricao="descrição interna", instrucoes="instruções internas",
            responsavel_id=servicos["admin"], tipo_recorrencia="diaria", intervalo=1,
            proxima_data=proxima, ativo=ativa,
        ))
    sessao.flush()
    for tid, (_t, _p, _a, execucoes) in TAREFAS.items():
        for quando in execucoes:
            sessao.add(TarefaRecorrenteExecucao(tarefa_id=tid, usuario_id=servicos["admin"], realizada_em=quando,
                                                observacao="observação interna"))
    sessao.commit()
    if sessao.bind.dialect.name == "postgresql":
        sessao.execute(text(
            "SELECT setval(pg_get_serial_sequence('tarefas_recorrentes', 'id'), (SELECT MAX(id) FROM tarefas_recorrentes))"
        ))
        sessao.commit()
    return servicos


def _foto(sessao):
    sessao.expire_all()
    return {
        "tarefas": sorted(
            (t.id, t.titulo, t.proxima_data, t.ativo, t.updated_at) for t in sessao.query(TarefaRecorrente)
        ),
        "execucoes": sorted(
            (e.id, e.tarefa_id, e.realizada_em) for e in sessao.query(TarefaRecorrenteExecucao)
        ),
    }


def _painel(autenticar, nome):
    uid, role = DUAS_DO_PAINEL[nome]
    return autenticar(uid, nome, {1: "Administrador", 2: "Tecnico"}[role])


class TestQuemLe:
    @pytest.mark.parametrize("quem", HUMANOS)
    def test_humanos_do_modulo_leem(self, cliente, tarefas, como, quem):
        resposta = cliente.get(ROTA, headers=como(quem))
        assert resposta.status_code == 200
        assert resposta.json() == {"data": "2026-11-03", "tarefas": ESPERADO}

    def test_sem_token_401(self, cliente, tarefas):
        assert cliente.get(ROTA).status_code == 401

    @pytest.mark.parametrize("quem", sorted(SERVICOS) + sorted(DUAS_DO_PAINEL) + ["conta_de_servico"])
    def test_nenhuma_conta_de_servico_le(self, cliente, tarefas, como, autenticar, sessao, saidas, quem):
        h = _painel(autenticar, quem) if quem in DUAS_DO_PAINEL else como(quem)
        antes = _foto(sessao)
        resposta = cliente.get(ROTA, headers=h)
        assert (resposta.status_code, resposta.json()) == (403, NEGADO)
        assert _foto(sessao) == antes

    @pytest.mark.parametrize("quem", FORA_DO_MODULO)
    def test_quem_nao_le_o_modulo_nao_le_o_lembrete(self, cliente, tarefas, como, quem):
        resposta = cliente.get(ROTA, headers=como(quem))
        assert resposta.status_code == 403

    @pytest.mark.parametrize("cabecalho", [
        {"User-Agent": "SmartTV painel.tv"}, {"X-Forwarded-For": "10.0.0.50"}, {"X-Painel": "1"},
    ])
    def test_cabecalho_nem_parametro_viram_identidade(self, cliente, tarefas, autenticar, cabecalho):
        h = {**_painel(autenticar, "painel_tv_admin"), **cabecalho}
        assert cliente.get(ROTA, headers=h).status_code == 403
        assert cliente.get(f"{ROTA}?painel=true&conta=painel.tv", headers=h).status_code == 403


class TestContrato:
    def test_so_os_campos_do_lembrete(self, cliente, tarefas, como):
        corpo = cliente.get(ROTA, headers=como("admin")).json()
        assert set(corpo) == {"data", "tarefas"}
        assert {frozenset(t) for t in corpo["tarefas"]} == {frozenset({"id", "titulo", "proxima_data", "situacao"})}
        assert "interna" not in str(corpo)

    def test_so_le(self, cliente, tarefas, como, sessao):
        antes = _foto(sessao)
        for _ in range(3):
            assert cliente.get(ROTA, headers=como("tecnico_ti")).status_code == 200
        assert _foto(sessao) == antes

    def test_o_dia_e_o_de_brasilia_e_nao_o_do_cliente(self, cliente, tarefas, como, monkeypatch):
        monkeypatch.setattr(tarefas_endpoint, "_hoje", lambda: date(2026, 11, 4))
        corpo = cliente.get(f"{ROTA}?data=2026-11-03", headers=como("admin")).json()
        assert corpo["data"] == "2026-11-04"
        situacoes = {t["id"]: t["situacao"] for t in corpo["tarefas"]}
        # 803 e 806 vencem no dia 4; 808 foi feita à meia-noite do dia 4.
        assert situacoes == {200: "atrasada", 809: "atrasada", 801: "atrasada", 802: "atrasada", 807: "atrasada",
                             803: "hoje", 806: "hoje", 808: "realizada_hoje"}

    def test_sem_tarefas_lista_vazia(self, cliente, servicos, configurar, como, sessao, monkeypatch):
        monkeypatch.setattr(tarefas_endpoint, "_hoje", lambda: HOJE)
        sessao.get(TarefaRecorrente, 200).ativo = False
        sessao.commit()
        assert cliente.get(ROTA, headers=como("admin")).json() == {"data": "2026-11-03", "tarefas": []}

    def test_nao_e_capturada_pelo_id(self, cliente, tarefas, como):
        """Declarada antes de `/{tarefa_id}`: "lembretes-do-dia" não vira 422 de id."""
        assert cliente.get(ROTA, headers=como("admin")).status_code == 200


class TestNaoAbreOModulo:
    @pytest.mark.parametrize("metodo,rota,corpo", SETE_ROTAS)
    @pytest.mark.parametrize("quem", sorted(DUAS_DO_PAINEL))
    def test_painel_continua_fora_das_sete(self, cliente, tarefas, autenticar, sessao, saidas, quem, metodo, rota, corpo):
        h = _painel(autenticar, quem)
        cliente.get(ROTA, headers=h)
        antes = _foto(sessao)
        resposta = cliente.request(metodo, f"{API}{rota}", headers=h, json=corpo)
        assert resposta.status_code == 403
        assert _foto(sessao) == antes
