"""
Trava de divergência entre `schema_chamados.sql` e os models do SQLAlchemy.

O arquivo de schema ficou parado da 1.0 até 11/08/2026 enquanto seis entregas
mexiam no banco. Rodá-lo criava um banco sem `usuarios.senha_hash` — ou seja,
um banco onde ninguém autentica. E ele é justamente o arquivo que alguém abre
numa recuperação de desastre ou ao montar homologação: o momento em que menos
se quer descobrir que a documentação envelheceu.

Atualizar o arquivo à mão resolve hoje e volta a divergir na próxima migration.
Este teste é o que torna a divergência impossível de passar despercebida: nova
coluna em `app/models/` sem a coluna correspondente no `.sql` derruba a suíte.

Por que ler o SQL em vez de executá-lo: o arquivo é PostgreSQL de verdade
(SERIAL, plpgsql, índice parcial), coisas que o SQLite dos outros testes não
executa. Subir um Postgres aqui quebraria a regra da suíte — nada de serviço
externo, nada de flake de ambiente. A comparação que interessa é de estrutura,
e essa dá para fazer lendo o texto.

O que este teste NÃO cobre, de propósito: tipo, nullable, default e CHECK.
Comparar isso exigiria interpretar dialeto (`VARCHAR(20)` vs `String(20)`,
`now()` vs `agora_brasilia`) e o teste passaria a falhar por diferença de
escrita, não de schema. Tabela e coluna ausentes é a falha que apagou o login;
é essa que a trava precisa pegar.
"""

import re
from pathlib import Path

import pytest

from app.core.database import Base
# Importar o pacote registra todos os models no Base.metadata. Sem isso, a
# comparação rodaria contra um metadata parcial e passaria sem verificar nada.
import app.models  # noqa: F401

RAIZ = Path(__file__).resolve().parent.parent
SCHEMA_SQL = RAIZ / "schema_chamados.sql"

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.IGNORECASE,
)
_ADD_COLUMN = re.compile(
    r"ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+"
    r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)

# Itens do corpo do CREATE TABLE que declaram restrição, não coluna.
_NAO_E_COLUNA = ("CONSTRAINT", "PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "EXCLUDE")


def _sem_comentarios(sql: str) -> str:
    """Remove os comentários `--`, que contêm vírgulas e parênteses soltos."""
    return re.sub(r"--[^\n]*", "", sql)


def _corpo_entre_parenteses(sql: str, abre: int) -> str:
    """
    Texto entre o parêntese em `abre` e o seu fechamento.

    Conta profundidade em vez de procurar o primeiro `)`: os CHECK embutidos
    têm parênteses próprios, e parar no primeiro cortaria a tabela no meio.
    """
    profundidade = 0
    for i in range(abre, len(sql)):
        if sql[i] == "(":
            profundidade += 1
        elif sql[i] == ")":
            profundidade -= 1
            if profundidade == 0:
                return sql[abre + 1 : i]
    raise AssertionError(f"CREATE TABLE sem parêntese de fechamento em {SCHEMA_SQL.name}")


def _colunas_do_corpo(corpo: str) -> set:
    """Nome da primeira palavra de cada item de topo, ignorando restrições."""
    itens, profundidade, atual = [], 0, []
    for ch in corpo:
        if ch == "(":
            profundidade += 1
        elif ch == ")":
            profundidade -= 1
        if ch == "," and profundidade == 0:
            itens.append("".join(atual))
            atual = []
        else:
            atual.append(ch)
    itens.append("".join(atual))

    colunas = set()
    for item in itens:
        palavras = item.split()
        if not palavras or palavras[0].upper() in _NAO_E_COLUNA:
            continue
        colunas.add(palavras[0].strip('"').lower())
    return colunas


def _tabelas_do_sql() -> dict:
    """{nome_da_tabela: {colunas}} conforme declarado no arquivo .sql."""
    sql = _sem_comentarios(SCHEMA_SQL.read_text(encoding="utf-8"))

    tabelas = {}
    for m in _CREATE_TABLE.finditer(sql):
        nome = m.group(1).lower()
        tabelas[nome] = _colunas_do_corpo(_corpo_entre_parenteses(sql, m.end() - 1))

    # ALTER TABLE ... ADD COLUMN no mesmo arquivo também conta, para o caso de
    # alguém acrescentar coluna no fim em vez de dentro do CREATE TABLE.
    for m in _ADD_COLUMN.finditer(sql):
        tabela, coluna = m.group(1).lower(), m.group(2).lower()
        if tabela in tabelas:
            tabelas[tabela].add(coluna)

    return tabelas


def _tabelas_dos_models() -> dict:
    return {
        nome.lower(): {c.name.lower() for c in tabela.columns}
        for nome, tabela in Base.metadata.tables.items()
    }


SQL = _tabelas_do_sql()
MODELS = _tabelas_dos_models()


def test_o_parser_enxergou_o_arquivo():
    """
    Guarda do próprio teste.

    Se o parser deixar de casar (arquivo renomeado, DDL reescrito de outro
    jeito), ele devolveria zero tabelas e todas as comparações passariam por
    vacuidade — uma trava que silenciosamente parou de travar.

    A verificação é estrutural, e não por contagem de tabelas, para a mensagem
    de falha não mentir: `len(SQL) >= 11` também quebraria com um arquivo
    apenas desatualizado, acusando o parser de um defeito que é do .sql. Estas
    duas tabelas existem desde a 1.0 e não vão sumir.
    """
    assert "chamados" in SQL and "usuarios" in SQL, (
        f"parser não encontrou as tabelas base em {SCHEMA_SQL.name} — "
        "provavelmente o formato do DDL mudou e o parser precisa acompanhar"
    )
    assert {"id", "protocolo", "titulo"} <= SQL["chamados"], (
        "corpo de `chamados` veio incompleto — parser quebrado, não arquivo velho"
    )


def test_nenhuma_tabela_dos_models_falta_no_sql():
    """
    O caso que motivou a trava: `sla_configs`, `tarefas_recorrentes` e
    `tarefas_recorrentes_execucoes` existiam nos models e não no arquivo.
    """
    faltando = sorted(set(MODELS) - set(SQL))
    assert not faltando, (
        f"tabelas em app/models/ que faltam em {SCHEMA_SQL.name}: {faltando}. "
        "Um banco criado com esse arquivo não tem essas tabelas."
    )


def test_nenhuma_tabela_do_sql_sobra_sem_model():
    """
    A direção inversa: tabela criada no .sql que nenhum model conhece é ou
    resto de feature removida, ou model esquecido. Nos dois casos, algo a
    resolver antes de o arquivo virar referência de recuperação.
    """
    sobrando = sorted(set(SQL) - set(MODELS))
    assert not sobrando, (
        f"tabelas em {SCHEMA_SQL.name} sem model correspondente: {sobrando}"
    )


@pytest.mark.parametrize("tabela", sorted(_tabelas_dos_models()))
def test_colunas_do_model_existem_no_sql(tabela):
    """
    O caso concreto que quebrava o login: `usuarios.senha_hash` no model e
    ausente no arquivo. Um teste por tabela para a falha dizer qual é.
    """
    if tabela not in SQL:
        pytest.skip("coberto por test_nenhuma_tabela_dos_models_falta_no_sql")

    faltando = sorted(MODELS[tabela] - SQL[tabela])
    assert not faltando, (
        f"colunas de `{tabela}` no model e ausentes em {SCHEMA_SQL.name}: {faltando}"
    )


@pytest.mark.parametrize("tabela", sorted(_tabelas_dos_models()))
def test_colunas_do_sql_existem_no_model(tabela):
    """
    Coluna no banco que nenhum model declara não quebra a API na hora, mas
    quebra o `INSERT` se for NOT NULL sem default — e é sinal de model
    desatualizado.
    """
    if tabela not in SQL:
        pytest.skip("coberto por test_nenhuma_tabela_dos_models_falta_no_sql")

    sobrando = sorted(SQL[tabela] - MODELS[tabela])
    assert not sobrando, (
        f"colunas de `{tabela}` em {SCHEMA_SQL.name} e ausentes no model: {sobrando}"
    )
