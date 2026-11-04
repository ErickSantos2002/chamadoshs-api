"""
A conta do painel lê os lembretes do dia (API-11, S1, `PAINEL_CONTAS_IDS`).

A TV da sala mostra o lembrete "tarefas do dia" e é uma conta de serviço — e
conta de serviço não lê o módulo de tarefas (API-10/API-11). A exceção é
estreita: conta de serviço, ativa, com o id em `PAINEL_CONTAS_IDS`, e só em
`GET /tarefas-recorrentes/lembretes-do-dia`. Tudo o mais que ela recebe é o
que já recebia; o isolamento está em `test_painel_isolamento.py`.

Os ids da configuração aqui são os do banco de teste (contas 70 a 79), nunca
de produção: o da TV real sai do inventário.

Quatro partes: a leitura da variável, a matriz de configuração × conta, os
casos que não podem virar identidade (nome, perfil, setor, marca sozinha,
query, cabeçalho, claim do token) e a resposta — só leitura, mínima, com o
dia de Brasília e o contrato que o quadro da TV vai consumir.
"""

import logging
from datetime import date, datetime

import pytest

import main
from app.api.deps import EQUIPE_TI_NEGADA, is_conta_do_painel
from app.api.endpoints import tarefas_recorrentes as tarefas_endpoint
from app.core.config import Settings, interpretar_painel_contas
from app.core.security import criar_token_acesso
from app.models import Role, Usuario
from app.models.evento_conta import EventoDeConta
from app.models.historico import HistoricoChamado
from app.models.tarefa_recorrente import TarefaRecorrente, TarefaRecorrenteExecucao
from app.utils.timezone import BRASILIA_TZ
from leitura_cenario import cenario_de_leitura  # noqa: F401
from test_conta_de_servico_rotas import SERVICOS, como, configurar, saidas, servicos  # noqa: F401
from test_lembretes_do_dia import DUAS_DO_PAINEL, ESPERADO, ROTA, tarefas  # noqa: F401

API = "/api/v1"
NEGADO = {"detail": EQUIPE_TI_NEGADA}
INATIVO = {"detail": "Usuário inativo"}
# Antes de qualquer fixture trocá-lo: o `_hoje` de verdade, de agora_brasilia().
_HOJE_REAL = tarefas_endpoint._hoje

ROLE_DESCONHECIDA = 9
# nome: (id, role_id, conta_de_servico, ativo) — além das de `servicos` e do painel.
EXTRAS = {
    "servico_perfil_desconhecido": (78, ROLE_DESCONHECIDA, True, True),
    "servico_inativa": (79, 2, True, False),
    "humano_perfil_desconhecido": (80, ROLE_DESCONHECIDA, False, True),
}
# Pessoas: o que já valia antes, e continua valendo com qualquer configuração.
PESSOAS_QUE_LEEM = ["admin", "admin_da_qualidade", "tecnico_ti", "tecnico_ti_dois"]
PESSOAS_QUE_NAO_LEEM = ["tecnico_qualidade", "tecnico_sem_setor", "tecnico_outro_setor", "solicitante",
                        "humano_perfil_desconhecido"]
PESSOA_INATIVA = "pessoa_inativa"  # conftest, 42
CONTAS_DE_SERVICO = sorted(SERVICOS) + sorted(DUAS_DO_PAINEL) + ["servico_perfil_desconhecido", "servico_inativa"]
TODAS_DE_SERVICO = "70,71,72,73,74,75,76,77,78,79"
SO_PESSOAS = "__pessoas__"  # trocado pelos ids das pessoas do cenário

# nome: (valor de PAINEL_CONTAS_IDS, ids que leem como painel)
CONFIGURACOES = {
    "ausente": (None, set()),
    "vazia": ("", set()),
    "so_espacos": ("   ", set()),
    "um_id": ("76", {76}),
    "varios_ids": ("76,77,74", {74, 76, 77}),
    "com_espacos": (" 76 ,  77 ", {76, 77}),
    "repetidos": ("76,77,76", {76, 77}),
    "texto": ("painel.tv", set()),
    "valido_e_invalido": ("76,painel", set()),
    "zero": ("0", set()),
    "zero_e_valido": ("76,0", set()),
    "negativo": ("-76", set()),
    "negativo_e_valido": ("76,-77", set()),
    "separador_vazio": ("76,,77", set()),
    "virgula_no_fim": ("76,", set()),
    "muito_grande": ("9" * 5000, set()),
    "acima_do_integer": ("76,2147483648", set()),
    # A inativa (79) está na lista e não lê.
    "todas_as_de_servico": (TODAS_DE_SERVICO, {70, 71, 72, 73, 74, 75, 76, 77, 78}),
    "so_pessoas": (SO_PESSOAS, set()),
}


def _painel(monkeypatch, valor):
    """Depois das fixtures: nenhuma delas pode trocar a configuração por trás do teste."""
    monkeypatch.setattr(main.settings, "PAINEL_CONTAS_IDS", valor)


@pytest.fixture
def contas(tarefas, sessao, autenticar, como):
    """Todas as contas da matriz, cada uma com o header do próprio token."""
    sessao.merge(Role(id=ROLE_DESCONHECIDA, nome="Auditor"))
    sessao.flush()
    for nome, (uid, role, servico, ativo) in EXTRAS.items():
        sessao.add(Usuario(id=uid, nome=nome.replace("_", "."), role_id=role, setor_id=1, ativo=ativo,
                           conta_de_servico=servico))
    sessao.commit()
    ids = {**{n: v[0] for n, v in EXTRAS.items()}, **{n: v[0] for n, v in DUAS_DO_PAINEL.items()},
           **{n: v[0] for n, v in SERVICOS.items()}, PESSOA_INATIVA: 42}
    ids.update({n: tarefas[n] for n in PESSOAS_QUE_LEEM + PESSOAS_QUE_NAO_LEEM if n in tarefas})

    def _header(nome):
        if nome in SERVICOS or nome in PESSOAS_QUE_LEEM + PESSOAS_QUE_NAO_LEEM and nome in tarefas:
            return como(nome)
        return autenticar(ids[nome], nome, "Tecnico")

    return {"ids": ids, "header": _header}


def _foto(sessao):
    sessao.expire_all()
    return {
        "tarefas": sorted(
            (t.id, t.titulo, t.proxima_data, t.ativo, t.updated_at) for t in sessao.query(TarefaRecorrente)
        ),
        "execucoes": sorted(
            (e.id, e.tarefa_id, e.realizada_em, e.observacao) for e in sessao.query(TarefaRecorrenteExecucao)
        ),
        "usuarios": sorted((u.id, u.ativo, u.conta_de_servico, u.role_id) for u in sessao.query(Usuario)),
        "eventos_de_conta": sessao.query(EventoDeConta).count(),
        "historico": sessao.query(HistoricoChamado).count(),
    }


class TestInterpretacao:
    @pytest.mark.parametrize("valor,ids", [
        ("101", {101}),
        (" 101 , 102 ", {101, 102}),
        ("102,101", {101, 102}),
        ("2147483647", {2147483647}),
    ])
    def test_lista_valida(self, valor, ids):
        lidos = interpretar_painel_contas(valor)
        assert (lidos.estado, lidos.ids, lidos.duplicados) == ("valida", ids, False)

    def test_repetidos_valem_uma_vez(self):
        assert interpretar_painel_contas("101,102,101") == ("valida", {101, 102}, True)

    @pytest.mark.parametrize("valor,estado", [(None, "ausente"), ("", "vazia"), ("  \t ", "vazia")])
    def test_sem_valor_ninguem(self, valor, estado):
        assert interpretar_painel_contas(valor) == (estado, frozenset(), False)

    @pytest.mark.parametrize("valor", [
        "painel", "101,abc", "0", "101,0", "-1", "101,-102", "101,,102", "101,", ",101", " , ",
        "+101", "1.0", "0x65", "1e3", "1 01", "101;102", "0101", "١٠١", "１０１",
        "2147483648", "99999999999", "9" * 5000, "101," + "9" * 5000,
    ])
    def test_um_item_invalido_descarta_a_lista_inteira(self, valor):
        """Nunca meio aplicada: "101,abc" não deixa o 101 passar."""
        assert interpretar_painel_contas(valor) == ("invalida", frozenset(), False)

    def _settings(self, monkeypatch, valor):
        if valor is None:
            monkeypatch.delenv("PAINEL_CONTAS_IDS", raising=False)
        else:
            monkeypatch.setenv("PAINEL_CONTAS_IDS", valor)
        return Settings(_env_file=None)

    @pytest.mark.parametrize("valor,trecho", [
        (None, "não definida"), ("", "vazia"), ("101,x", "não é uma lista"), ("9" * 5000, "não é uma lista"),
        ("101,101", "repetidos"),
    ])
    def test_a_subida_avisa_sem_mostrar_os_ids(self, monkeypatch, caplog, valor, trecho):
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            config = self._settings(monkeypatch, valor)
        mensagens = [r.getMessage() for r in caplog.records if "PAINEL_CONTAS_IDS" in r.getMessage()]
        assert any(trecho in m for m in mensagens)
        assert not any("101" in m or "999" in m for m in mensagens)
        assert config.painel_contas_ids == (frozenset({101}) if trecho == "repetidos" else frozenset())

    def test_lista_valida_nao_avisa(self, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            config = self._settings(monkeypatch, "101,102")
        assert config.painel_contas_ids == {101, 102}
        assert not any("PAINEL_CONTAS_IDS" in r.getMessage() for r in caplog.records)

    def test_o_padrao_e_nenhuma_conta(self, monkeypatch):
        assert self._settings(monkeypatch, None).painel_contas_ids == frozenset()


@pytest.mark.usefixtures("saidas")
class TestMatriz:
    @pytest.mark.parametrize("configuracao", sorted(CONFIGURACOES))
    def test_configuracao_por_conta(self, cliente, contas, sessao, monkeypatch, configuracao):
        """Cada conta, sob cada configuração: quem lê, quem recebe 403 e com que corpo."""
        valor, leem = CONFIGURACOES[configuracao]
        if valor == SO_PESSOAS:
            valor = ",".join(str(contas["ids"][n]) for n in PESSOAS_QUE_LEEM + PESSOAS_QUE_NAO_LEEM + [PESSOA_INATIVA])
        _painel(monkeypatch, valor)
        antes = _foto(sessao)

        obtido, esperado = {}, {}
        for nome in PESSOAS_QUE_LEEM + PESSOAS_QUE_NAO_LEEM + [PESSOA_INATIVA] + CONTAS_DE_SERVICO:
            resposta = cliente.get(ROTA, headers=contas["header"](nome))
            obtido[nome] = (resposta.status_code, resposta.json())
            if nome in ("servico_inativa", PESSOA_INATIVA):
                esperado[nome] = (403, INATIVO)
            elif nome in PESSOAS_QUE_LEEM or contas["ids"][nome] in leem and nome in CONTAS_DE_SERVICO:
                esperado[nome] = (200, {"data": "2026-11-03", "tarefas": ESPERADO})
            else:
                esperado[nome] = (403, NEGADO)
        assert obtido == esperado
        assert _foto(sessao) == antes


@pytest.mark.usefixtures("saidas")
class TestQuemLe:
    @pytest.mark.parametrize("nome", ["painel_tv_admin", "painel_tv_tecnico", "servico_tecnico_ti",
                                      "servico_usuario_ti", "servico_admin_ti", "servico_tecnico_sem_setor",
                                      "servico_perfil_desconhecido"])
    def test_a_conta_listada_le_o_mesmo_que_as_pessoas(self, cliente, contas, monkeypatch, nome):
        """Qualquer perfil — a lista identifica a TV; o perfil não entra."""
        _painel(monkeypatch, str(contas["ids"][nome]))
        painel = cliente.get(ROTA, headers=contas["header"](nome))
        pessoa = cliente.get(ROTA, headers=contas["header"]("tecnico_ti"))
        assert (painel.status_code, pessoa.status_code) == (200, 200)
        assert painel.json() == pessoa.json() == {"data": "2026-11-03", "tarefas": ESPERADO}

    @pytest.mark.parametrize("nome", PESSOAS_QUE_LEEM)
    def test_as_pessoas_continuam_lendo_sem_lista(self, cliente, contas, monkeypatch, nome):
        _painel(monkeypatch, None)
        assert cliente.get(ROTA, headers=contas["header"](nome)).status_code == 200

    @pytest.mark.parametrize("nome", ["solicitante", "tecnico_outro_setor", "tecnico_qualidade",
                                      "humano_perfil_desconhecido"])
    def test_pessoa_listada_nao_ganha_nada(self, cliente, contas, monkeypatch, nome):
        _painel(monkeypatch, str(contas["ids"][nome]))
        assert (cliente.get(ROTA, headers=contas["header"](nome)).json()) == NEGADO

    def test_nem_perfil_nem_setor_nem_marca_sozinhos(self, cliente, contas, monkeypatch):
        """A 70 é técnica, do setor da TI e de serviço: sem estar na lista, não lê."""
        _painel(monkeypatch, "76")
        for nome in ("servico_tecnico_ti", "servico_admin_ti", "painel_tv_tecnico"):
            assert cliente.get(ROTA, headers=contas["header"](nome)).json() == NEGADO, nome

    @pytest.mark.parametrize("consulta", ["usuario_id=76", "id=76", "conta=76", "painel=true", "conta_de_servico=true",
                                          "usuario_id=76&painel=true"])
    def test_id_pela_query_nao_vale(self, cliente, contas, monkeypatch, consulta):
        _painel(monkeypatch, "76")
        resposta = cliente.get(f"{ROTA}?{consulta}", headers=contas["header"]("servico_tecnico_ti"))
        assert (resposta.status_code, resposta.json()) == (403, NEGADO)

    @pytest.mark.parametrize("cabecalho", [
        {"X-Usuario-Id": "76"}, {"X-Painel-Conta-Id": "76"}, {"X-Forwarded-User": "painel.tv.admin"},
        {"X-Conta-De-Servico": "true"}, {"User-Agent": "SmartTV painel.tv.admin"}, {"X-Forwarded-For": "10.0.0.76"},
    ])
    def test_id_pelo_cabecalho_nao_vale(self, cliente, contas, monkeypatch, cabecalho):
        _painel(monkeypatch, "76")
        resposta = cliente.get(ROTA, headers={**contas["header"]("servico_tecnico_ti"), **cabecalho})
        assert (resposta.status_code, resposta.json()) == (403, NEGADO)

    def test_claim_do_token_nao_vale(self, cliente, contas, monkeypatch):
        """O token só diz quem é (`sub`); marca, ativo e perfil vêm do banco."""
        pessoa = contas["ids"]["solicitante"]
        _painel(monkeypatch, str(pessoa))
        token = criar_token_acesso(data={"sub": str(pessoa), "nome": "painel.tv", "role": "Administrador",
                                         "conta_de_servico": True, "ativo": True, "painel": True})
        resposta = cliente.get(ROTA, headers={"Authorization": f"Bearer {token}"})
        assert (resposta.status_code, resposta.json()) == (403, NEGADO)

    def test_inativa_listada_nao_le(self, cliente, contas, monkeypatch):
        _painel(monkeypatch, "79")
        assert cliente.get(ROTA, headers=contas["header"]("servico_inativa")).json() == INATIVO

    def test_desativada_depois_do_token_perde_na_hora(self, cliente, contas, sessao, monkeypatch):
        _painel(monkeypatch, "76")
        h = contas["header"]("painel_tv_admin")
        assert cliente.get(ROTA, headers=h).status_code == 200
        sessao.get(Usuario, 76).ativo = False
        sessao.commit()
        assert cliente.get(ROTA, headers=h).json() == INATIVO

    def test_a_marca_vem_do_banco_a_cada_pedido(self, cliente, contas, sessao, monkeypatch):
        """A 74 (perfil Usuário) deixa de ser de serviço: na lista ou não, vira pessoa comum."""
        _painel(monkeypatch, "74")
        h = contas["header"]("servico_usuario_ti")
        assert cliente.get(ROTA, headers=h).status_code == 200
        sessao.get(Usuario, 74).conta_de_servico = False
        sessao.commit()
        assert cliente.get(ROTA, headers=h).json() == NEGADO

    def test_tirar_da_lista_tira_o_acesso(self, cliente, contas, monkeypatch):
        h = contas["header"]("painel_tv_tecnico")
        _painel(monkeypatch, "76,77")
        assert cliente.get(ROTA, headers=h).status_code == 200
        _painel(monkeypatch, "76")
        assert cliente.get(ROTA, headers=h).json() == NEGADO

    def test_a_recusa_nao_diz_por_que(self, cliente, contas, monkeypatch):
        """Fora da lista, pessoa na lista, lista inválida: o mesmo corpo, sem citar a configuração."""
        corpos = []
        for valor, nome in (("76", "servico_tecnico_ti"), (str(contas["ids"]["solicitante"]), "solicitante"),
                            ("76,x", "painel_tv_admin"), (None, "painel_tv_admin")):
            _painel(monkeypatch, valor)
            corpos.append(cliente.get(ROTA, headers=contas["header"](nome)).text)
        assert len(set(corpos)) == 1
        assert "PAINEL" not in corpos[0].upper() and "76" not in corpos[0]

    def test_sem_token_401(self, cliente, contas, monkeypatch):
        _painel(monkeypatch, TODAS_DE_SERVICO)
        assert cliente.get(ROTA).status_code == 401
        assert cliente.get(ROTA, headers={"Authorization": "Bearer nao-e-um-token"}).status_code == 401

    @pytest.mark.parametrize("conta_de_servico,ativo,esperado", [
        (True, True, True), (True, False, False), (True, None, False),
        (False, True, False), (None, True, False),
    ])
    def test_a_regra_sozinha(self, monkeypatch, conta_de_servico, ativo, esperado):
        """Sem depender de `get_current_user`: inativa e marca indefinida não passam aqui também."""
        _painel(monkeypatch, "76")
        conta = Usuario(id=76, nome="x", role_id=1, conta_de_servico=conta_de_servico, ativo=ativo)
        assert is_conta_do_painel(conta) is esperado
        assert is_conta_do_painel(Usuario(id=77, nome="y", role_id=1, conta_de_servico=True, ativo=True)) is False


@pytest.mark.usefixtures("saidas")
class TestResposta:
    def test_ler_nao_escreve(self, cliente, contas, sessao, monkeypatch):
        """Nem próxima data, nem execução, nem evento, nem histórico; `saidas` barra webhook."""
        _painel(monkeypatch, "76")
        antes = _foto(sessao)
        for _ in range(3):
            assert cliente.get(ROTA, headers=contas["header"]("painel_tv_admin")).status_code == 200
        assert _foto(sessao) == antes

    def test_so_os_campos_do_lembrete(self, cliente, contas, monkeypatch):
        _painel(monkeypatch, "77")
        corpo = cliente.get(ROTA, headers=contas["header"]("painel_tv_tecnico")).json()
        assert set(corpo) == {"data", "tarefas"}
        assert {frozenset(t) for t in corpo["tarefas"]} == {frozenset({"id", "titulo", "proxima_data", "situacao"})}
        assert "interna" not in str(corpo) and "descri" not in str(corpo)

    @pytest.mark.parametrize("agora,dia", [
        (datetime(2026, 11, 3, 23, 59, 59, tzinfo=BRASILIA_TZ), "2026-11-03"),
        (datetime(2026, 11, 4, 0, 0, 1, tzinfo=BRASILIA_TZ), "2026-11-04"),
    ])
    def test_o_dia_e_o_de_brasilia(self, cliente, contas, monkeypatch, agora, dia):
        """Pelo `_hoje` de verdade: 23h59 de Brasília já é o dia seguinte em UTC, e não muda o dia."""
        _painel(monkeypatch, "76")
        monkeypatch.setattr(tarefas_endpoint, "_hoje", _HOJE_REAL)
        monkeypatch.setattr(tarefas_endpoint, "agora_brasilia", lambda: agora)
        assert cliente.get(ROTA, headers=contas["header"]("painel_tv_admin")).json()["data"] == dia

    def test_ordem_estavel(self, cliente, contas, monkeypatch):
        _painel(monkeypatch, "76")
        leituras = [cliente.get(ROTA, headers=contas["header"]("painel_tv_admin")).json() for _ in range(3)]
        assert leituras[0] == leituras[1] == leituras[2]
        chaves = [(date.fromisoformat(t["proxima_data"]), t["id"]) for t in leituras[0]["tarefas"]]
        assert chaves == sorted(chaves)


class TestContratoParaOQuadro:
    """O que o quadro da TV vai consumir: o contrato publicado no OpenAPI."""

    def test_o_openapi_da_rota(self):
        esquema = main.app.openapi()
        caminho = esquema["paths"][f"{API}/tarefas-recorrentes/lembretes-do-dia"]
        assert set(caminho) == {"get"}
        ref = caminho["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        componentes = esquema["components"]["schemas"]
        resposta = componentes[ref.rsplit("/", 1)[1]]
        assert set(resposta["properties"]) == {"data", "tarefas"}
        assert set(resposta["required"]) == {"data", "tarefas"}
        assert resposta["properties"]["data"] == {"type": "string", "format": "date", "title": "Data"}
        item = componentes[resposta["properties"]["tarefas"]["items"]["$ref"].rsplit("/", 1)[1]]
        assert set(item["properties"]) == set(item["required"]) == {"id", "titulo", "proxima_data", "situacao"}
        assert item["properties"]["situacao"]["enum"] == ["atrasada", "hoje", "realizada_hoje"]
        assert [p["name"] for p in caminho["get"].get("parameters", [])] == []


@pytest.mark.usefixtures("saidas")
class TestDiagnostico:
    def test_confere_a_lista_contra_o_cadastro_sem_nomes(self, cliente, contas, monkeypatch):
        _painel(monkeypatch, f"76,79,{contas['ids']['admin']},999")
        corpo = cliente.get(f"{API}/diagnostico/", headers=contas["header"]("admin")).json()
        painel = corpo["painel"]
        assert painel["painel_contas_ids"] == {
            "estado": "valida",
            "configurados": sorted({76, 79, contas["ids"]["admin"], 999}),
            "autorizadas": [76],
            "inexistentes": [999],
            "inativas": [79],
            "nao_sao_de_servico": [contas["ids"]["admin"]],
        }
        assert len(painel["alertas"]) == 3
        assert "painel.tv" not in str(painel) and "admin.teste" not in str(painel)

    @pytest.mark.parametrize("valor,estado", [(None, "ausente"), ("", "vazia"), ("76,x", "invalida")])
    def test_sem_lista_valida_avisa(self, cliente, contas, monkeypatch, valor, estado):
        _painel(monkeypatch, valor)
        painel = cliente.get(f"{API}/diagnostico/", headers=contas["header"]("admin")).json()["painel"]
        assert painel["painel_contas_ids"]["estado"] == estado
        assert painel["painel_contas_ids"]["autorizadas"] == []
        assert any(estado in a for a in painel["alertas"])

    def test_a_conta_do_painel_nao_le_o_diagnostico(self, cliente, contas, monkeypatch):
        _painel(monkeypatch, "76,77")
        for nome in ("painel_tv_admin", "painel_tv_tecnico"):
            assert cliente.get(f"{API}/diagnostico/", headers=contas["header"](nome)).status_code == 403
