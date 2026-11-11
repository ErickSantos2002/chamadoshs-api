"""
A migration da versão do chamado e o trigger que a mantém, em PostgreSQL real.

O SQLite da suíte não tem trigger plpgsql nem `pg_trigger`: nada aqui seria
provado lá. Estes testes rodam só com `CHAMADOSHS_TESTE_PG_URL` apontando para
um servidor local (ver `tests/pg_descartavel.py`), e cada um recebe um banco
novo e descartável.

O ponto de partida é o banco de produção ANTES desta migration: o
`schema_chamados.sql` com a reversão documentada na própria migration
aplicada por cima. Assim o teste da reversão e o do ponto de partida são o
mesmo texto — se a reversão do cabeçalho mudar, os dois mudam juntos.

O que "mudança efetiva" quer dizer está no cabeçalho da migration: qualquer
coluna persistida, menos `versao`, `updated_at` e `data_atualizacao`.
"""

import re

import pytest

from pg_descartavel import banco_descartavel, executar_script, ler

pytestmark = pytest.mark.postgres

MIGRATION = "migrations/2026-10-28-add-versao-chamados.sql"


def _reversao_documentada() -> str:
    """O bloco BEGIN … COMMIT da seção REVERSÃO DO SCHEMA, sem o `--   `."""
    texto = ler(MIGRATION)
    secao = texto.split("REVERSÃO DO SCHEMA", 1)[1].split("-- ====", 1)[0]
    linhas = [
        linha[len("--   "):]
        for linha in secao.splitlines()
        if linha.startswith("--   ") and not linha.startswith("--   --")
    ]
    sql = "\n".join(linhas)
    assert sql.startswith("BEGIN;") and sql.rstrip().endswith("COMMIT;"), sql
    return sql


REVERSAO = _reversao_documentada()


def _psql(url):
    import psycopg2

    conexao = psycopg2.connect(url)
    conexao.autocommit = True
    return conexao


def _consultar(url, sql, parametros, buscar):
    conexao = _psql(url)
    try:
        with conexao.cursor() as cur:
            cur.execute(sql, parametros)
            return buscar(cur)
    finally:
        conexao.close()


def _um(url, sql, parametros=None):
    return _consultar(url, sql, parametros, lambda cur: cur.fetchone())


def _todos(url, sql, parametros=None):
    return _consultar(url, sql, parametros, lambda cur: cur.fetchall())


def _fazer(url, sql, parametros=None):
    _consultar(url, sql, parametros, lambda cur: None)


def _aplicar(url):
    return executar_script(url, ler(MIGRATION))


def _pecas(url) -> dict:
    """O que existe das quatro peças, lido do catálogo."""
    coluna = _um(
        url,
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_name = 'chamados' AND column_name = 'versao'",
    )
    check = _um(
        url,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'chamados'::regclass AND conname = 'chk_chamados_versao'",
    )
    check = check[0] if check else None
    funcao = _um(url, "SELECT to_regprocedure('chamados_versao()') IS NOT NULL")[0]
    gatilhos = [
        nome
        for (nome,) in _todos(
            url,
            "SELECT tgname FROM pg_trigger WHERE tgrelid = 'chamados'::regclass "
            "AND NOT tgisinternal ORDER BY tgname",
        )
    ]
    return {"coluna": coluna, "check": check, "funcao": funcao, "gatilhos": gatilhos}


@pytest.fixture(scope="module")
def producao_de_hoje():
    """O banco como produção está hoje: schema completo, sem a versão. Só leitura: é o modelo."""
    with banco_descartavel("modelo_versao") as url:
        executar_script(url, ler("schema_chamados.sql"))
        executar_script(url, REVERSAO)
        _fazer(
            url,
            "INSERT INTO usuarios (id, nome, role_id, setor_id, ativo) VALUES (1, 'admin.teste', 1, 1, true)",
        )
        yield url


@pytest.fixture
def banco(producao_de_hoje):
    """Uma cópia nova de `producao_de_hoje` por teste."""
    with banco_descartavel(modelo=producao_de_hoje) as url:
        yield url


def _novo_chamado(url, protocolo="CH-1", **extra) -> int:
    colunas = {"protocolo": protocolo, "solicitante_id": 1, "titulo": "Impressora", "descricao": "Não liga", **extra}
    nomes = ", ".join(colunas)
    marcas = ", ".join(["%s"] * len(colunas))
    return _um(url, f"INSERT INTO chamados ({nomes}) VALUES ({marcas}) RETURNING id", list(colunas.values()))[0]


def _versao(url, chamado_id) -> int:
    return _um(url, "SELECT versao FROM chamados WHERE id = %s", [chamado_id])[0]


def _erro_da_migration(url) -> str:
    import psycopg2

    with pytest.raises(psycopg2.Error) as erro:
        _aplicar(url)
    return str(erro.value)


# ── A migration ───────────────────────────────────────────────────────────


class TestMigration:
    def test_o_ponto_de_partida_nao_tem_nenhuma_das_quatro_pecas(self, banco):
        assert _pecas(banco) == {
            "coluna": None,
            "check": None,
            "funcao": False,
            "gatilhos": ["trigger_chamados_updated_at"],
        }

    def test_aplica_em_tabela_com_chamados_e_todos_comecam_em_1(self, banco):
        ids = [_novo_chamado(banco, f"CH-{n}") for n in range(3)]
        _fazer(banco, "UPDATE chamados SET status = 'Em Andamento' WHERE id = %s", [ids[0]])

        avisos = _aplicar(banco)

        assert any("versao criada" in a for a in avisos), avisos
        assert _todos(banco, "SELECT id, versao FROM chamados ORDER BY id") == [(i, 1) for i in ids]
        assert _pecas(banco) == {
            "coluna": ("integer", "NO", "1"),
            "check": "CHECK ((versao >= 1))",
            "funcao": True,
            "gatilhos": ["trigger_chamados_updated_at", "trigger_chamados_versao"],
        }

    def test_aplica_em_tabela_vazia(self, banco):
        _aplicar(banco)
        assert _pecas(banco)["coluna"] == ("integer", "NO", "1")

    def test_a_coluna_recusa_nulo_e_versao_menor_que_1(self, banco):
        import psycopg2

        _aplicar(banco)
        assert _um(banco, "SELECT count(*) FROM information_schema.columns WHERE table_name = 'chamados' "
                          "AND column_name = 'versao' AND is_nullable = 'NO'")[0] == 1
        # O trigger força 1 no INSERT; o CHECK é a segunda trava, para o dia
        # em que o trigger estiver desligado.
        _fazer(banco, "ALTER TABLE chamados DISABLE TRIGGER trigger_chamados_versao")
        with pytest.raises(psycopg2.errors.CheckViolation):
            _novo_chamado(banco, versao=0)
        with pytest.raises(psycopg2.errors.NotNullViolation):
            _novo_chamado(banco, "CH-2", versao=None)

    def test_reexecutar_nao_faz_nada_e_preserva_as_versoes(self, banco):
        _aplicar(banco)
        chamado = _novo_chamado(banco)
        _fazer(banco, "UPDATE chamados SET status = 'Em Andamento' WHERE id = %s", [chamado])
        antes = _pecas(banco)

        avisos = _aplicar(banco)

        assert any("já aplicada" in a for a in avisos), avisos
        assert _pecas(banco) == antes
        assert _versao(banco, chamado) == 2

    def test_a_funcao_reformatada_continua_valendo_como_igual(self, banco):
        _aplicar(banco)
        corpo = _um(banco, "SELECT prosrc FROM pg_proc WHERE oid = 'chamados_versao()'::regprocedure")[0]
        reformatado = re.sub(r"\n\s*", "\n        ", corpo)
        assert reformatado != corpo
        _fazer(banco, "CREATE OR REPLACE FUNCTION chamados_versao() RETURNS trigger LANGUAGE plpgsql AS %s", [reformatado])

        assert any("já aplicada" in a for a in _aplicar(banco))

    def test_sem_a_tabela_recusa(self):
        with banco_descartavel() as url:
            assert "Tabela chamados não encontrada" in _erro_da_migration(url)


class TestEstadoParcialOuIncompativel:
    """Qualquer combinação fora de "nada" ou "tudo certo" para, sem mexer."""

    @pytest.mark.parametrize(
        "preparo, ausente",
        [
            ("ALTER TABLE chamados ADD COLUMN versao INTEGER NOT NULL DEFAULT 1", "coluna versao presente"),
            (
                "CREATE FUNCTION chamados_versao() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'",
                "função chamados_versao() presente",
            ),
        ],
        ids=["so-a-coluna", "so-a-funcao"],
    )
    def test_so_uma_peca_criada_a_mao(self, banco, preparo, ausente):
        _fazer(banco, preparo)
        antes = _pecas(banco)

        erro = _erro_da_migration(banco)

        assert "Estado inconsistente" in erro and ausente in erro
        assert _pecas(banco) == antes

    def test_falta_so_o_trigger(self, banco):
        _aplicar(banco)
        _fazer(banco, "DROP TRIGGER trigger_chamados_versao ON chamados")

        assert "trigger trigger_chamados_versao ausente" in _erro_da_migration(banco)
        assert "trigger_chamados_versao" not in _pecas(banco)["gatilhos"]

    @pytest.mark.parametrize(
        "alteracao",
        [
            "ALTER TABLE chamados ALTER COLUMN versao TYPE BIGINT",
            "ALTER TABLE chamados ALTER COLUMN versao DROP NOT NULL",
            "ALTER TABLE chamados ALTER COLUMN versao SET DEFAULT 2",
        ],
        ids=["bigint", "aceita-nulo", "default-2"],
    )
    def test_coluna_incompativel(self, banco, alteracao):
        _aplicar(banco)
        _fazer(banco, alteracao)

        assert "chamados.versao existe com formato inesperado" in _erro_da_migration(banco)

    def test_check_incompativel(self, banco):
        _aplicar(banco)
        _fazer(banco, "ALTER TABLE chamados DROP CONSTRAINT chk_chamados_versao")
        _fazer(banco, "ALTER TABLE chamados ADD CONSTRAINT chk_chamados_versao CHECK (versao >= 0)")

        assert "chk_chamados_versao existe com definição inesperada" in _erro_da_migration(banco)

    def test_funcao_com_outro_corpo(self, banco):
        _aplicar(banco)
        _fazer(
            banco,
            "CREATE OR REPLACE FUNCTION chamados_versao() RETURNS trigger LANGUAGE plpgsql AS "
            "'BEGIN NEW.versao := OLD.versao + 1; RETURN NEW; END'",
        )

        assert "chamados_versao() existe com outra definição" in _erro_da_migration(banco)

    @pytest.mark.parametrize(
        "definicao",
        [
            "AFTER INSERT OR UPDATE ON chamados FOR EACH ROW",
            "BEFORE UPDATE ON chamados FOR EACH ROW",
            "BEFORE INSERT OR UPDATE OF status ON chamados FOR EACH ROW",
            "BEFORE INSERT OR UPDATE ON chamados FOR EACH ROW WHEN (NEW.versao IS NOT NULL)",
        ],
        ids=["after", "so-update", "so-uma-coluna", "com-when"],
    )
    def test_trigger_com_outra_definicao(self, banco, definicao):
        _aplicar(banco)
        _fazer(banco, "DROP TRIGGER trigger_chamados_versao ON chamados")
        _fazer(banco, f"CREATE TRIGGER trigger_chamados_versao {definicao} EXECUTE FUNCTION chamados_versao()")

        assert "trigger_chamados_versao existe com definição inesperada" in _erro_da_migration(banco)

    def test_trigger_desabilitado(self, banco):
        _aplicar(banco)
        _fazer(banco, "ALTER TABLE chamados DISABLE TRIGGER trigger_chamados_versao")

        assert "trigger_chamados_versao existe com definição inesperada" in _erro_da_migration(banco)

    def test_segundo_trigger_com_a_mesma_funcao(self, banco):
        _aplicar(banco)
        _fazer(
            banco,
            "CREATE TRIGGER trigger_chamados_versao_copia BEFORE INSERT OR UPDATE ON chamados "
            "FOR EACH ROW EXECUTE FUNCTION chamados_versao()",
        )

        assert "é chamada por 2 triggers" in _erro_da_migration(banco)


class TestReversao:
    def test_a_reversao_documentada_tira_as_quatro_pecas_e_mais_nada(self, banco):
        chamado = _novo_chamado(banco, status="Aguardando")
        _aplicar(banco)
        _fazer(banco, "UPDATE chamados SET prioridade = 'Alta' WHERE id = %s", [chamado])

        executar_script(banco, REVERSAO)

        assert _pecas(banco) == {
            "coluna": None,
            "check": None,
            "funcao": False,
            "gatilhos": ["trigger_chamados_updated_at"],
        }
        assert _um(banco, "SELECT status, prioridade FROM chamados WHERE id = %s", [chamado]) == (
            "Aguardando",
            "Alta",
        )

    def test_depois_da_reversao_a_migration_aplica_de_novo(self, banco):
        _aplicar(banco)
        executar_script(banco, REVERSAO)

        assert any("versao criada" in a for a in _aplicar(banco))


# ── O trigger ─────────────────────────────────────────────────────────────


@pytest.fixture
def com_versao(banco):
    _aplicar(banco)
    return banco


class TestTrigger:
    def test_insert_comeca_em_1(self, com_versao):
        assert _versao(com_versao, _novo_chamado(com_versao)) == 1

    def test_insert_ignora_a_versao_do_comando(self, com_versao):
        assert _versao(com_versao, _novo_chamado(com_versao, versao=7)) == 1

    @pytest.mark.parametrize(
        "campo, valor",
        [
            ("status", "Em Andamento"),
            ("tecnico_responsavel_id", 1),
            ("prioridade", "Alta"),
            ("solucao", "Troquei o toner."),
            ("cancelado", True),
            ("arquivado", True),
            ("avaliacao", 5),
            ("data_resolucao", "2026-10-28 10:00:00"),
        ],
    )
    def test_mudanca_de_um_campo_sobe_1(self, com_versao, campo, valor):
        chamado = _novo_chamado(com_versao)
        _fazer(com_versao, f"UPDATE chamados SET {campo} = %s WHERE id = %s", [valor, chamado])
        assert _versao(com_versao, chamado) == 2

    def test_varios_campos_no_mesmo_update_sobem_1(self, com_versao):
        chamado = _novo_chamado(com_versao)
        _fazer(
            com_versao,
            "UPDATE chamados SET status = 'Resolvido', solucao = 'ok', prioridade = 'Baixa', "
            "tecnico_responsavel_id = 1 WHERE id = %s",
            [chamado],
        )
        assert _versao(com_versao, chamado) == 2

    @pytest.mark.parametrize(
        "atribuicao",
        [
            "status = status",
            "status = 'Aberto'",
            "prioridade = 'Média', status = 'Aberto'",
            "solucao = NULL",
        ],
        ids=["proprio-campo", "mesmo-valor", "varios-mesmos-valores", "nulo-para-nulo"],
    )
    def test_update_sem_mudanca_nao_sobe(self, com_versao, atribuicao):
        chamado = _novo_chamado(com_versao)
        _fazer(com_versao, f"UPDATE chamados SET {atribuicao} WHERE id = %s", [chamado])
        assert _versao(com_versao, chamado) == 1

    def test_carimbos_automaticos_nao_contam_como_mudanca(self, com_versao):
        chamado = _novo_chamado(com_versao)
        _fazer(
            com_versao,
            "UPDATE chamados SET updated_at = now() + interval '1 day', "
            "data_atualizacao = now() + interval '1 day' WHERE id = %s",
            [chamado],
        )
        assert _versao(com_versao, chamado) == 1

    def test_o_trigger_do_updated_at_continua_como_era(self, com_versao):
        """Ele reescreve `updated_at` até no UPDATE vazio — e a versão não sobe por isso."""
        chamado = _novo_chamado(com_versao)
        _fazer(com_versao, "UPDATE chamados SET updated_at = '2000-01-01' WHERE id = %s", [chamado])
        _fazer(com_versao, "UPDATE chamados SET status = status WHERE id = %s", [chamado])
        updated_at, versao = _um(com_versao, "SELECT updated_at, versao FROM chamados WHERE id = %s", [chamado])
        assert updated_at.year > 2000
        assert versao == 1

    @pytest.mark.parametrize(
        "atribuicao",
        ["versao = 999", "versao = 0", "versao = 1", "versao = versao + 10"],
        ids=["adiantar", "zerar", "redefinir", "somar"],
    )
    def test_update_so_da_versao_nao_muda_nada(self, com_versao, atribuicao):
        chamado = _novo_chamado(com_versao)
        _fazer(com_versao, "UPDATE chamados SET status = 'Em Andamento' WHERE id = %s", [chamado])
        _fazer(com_versao, f"UPDATE chamados SET {atribuicao} WHERE id = %s", [chamado])
        assert _versao(com_versao, chamado) == 2

    def test_versao_no_comando_junto_de_mudanca_real_sobe_1_a_partir_da_antiga(self, com_versao):
        chamado = _novo_chamado(com_versao)
        _fazer(com_versao, "UPDATE chamados SET versao = 50, status = 'Aguardando' WHERE id = %s", [chamado])
        assert _versao(com_versao, chamado) == 2

    def test_escritas_seguidas_dao_versoes_em_sequencia(self, com_versao):
        chamado = _novo_chamado(com_versao)
        vistas = []
        for status in ["Em Andamento", "Aguardando", "Em Andamento", "Resolvido"]:
            vistas.append(
                _um(com_versao, "UPDATE chamados SET status = %s WHERE id = %s RETURNING versao", [status, chamado])[0]
            )
        assert vistas == [2, 3, 4, 5]

    def test_update_de_varias_linhas_sobe_cada_uma_uma_vez(self, com_versao):
        a, b = _novo_chamado(com_versao, "CH-A"), _novo_chamado(com_versao, "CH-B", prioridade="Alta")
        _fazer(com_versao, "UPDATE chamados SET prioridade = 'Alta'")
        assert (_versao(com_versao, a), _versao(com_versao, b)) == (2, 1)

    def test_rollback_preserva_a_versao_anterior(self, com_versao):
        import psycopg2

        chamado = _novo_chamado(com_versao)
        conexao = psycopg2.connect(com_versao)
        try:
            with conexao.cursor() as cur:
                cur.execute("UPDATE chamados SET status = 'Em Andamento' WHERE id = %s RETURNING versao", [chamado])
                assert cur.fetchone()[0] == 2
            conexao.rollback()
        finally:
            conexao.close()
        assert _versao(com_versao, chamado) == 1

    def test_erro_no_meio_da_transacao_desfaz_a_versao(self, com_versao):
        import psycopg2

        chamado = _novo_chamado(com_versao)
        conexao = psycopg2.connect(com_versao)
        try:
            with conexao.cursor() as cur:
                cur.execute("UPDATE chamados SET status = 'Em Andamento' WHERE id = %s", [chamado])
                with pytest.raises(psycopg2.errors.CheckViolation):
                    cur.execute("UPDATE chamados SET prioridade = 'Urgentíssima' WHERE id = %s", [chamado])
            conexao.rollback()
        finally:
            conexao.close()
        assert _um(com_versao, "SELECT status, versao FROM chamados WHERE id = %s", [chamado]) == ("Aberto", 1)

    def test_a_versao_nao_depende_do_que_o_front_manda_em_outras_tabelas(self, com_versao):
        """Comentário e histórico são outras tabelas: não sobem a versão do chamado."""
        chamado = _novo_chamado(com_versao)
        _fazer(
            com_versao,
            "INSERT INTO historico_chamados (chamado_id, usuario_id, acao) VALUES (%s, 1, 'Teste')",
            [chamado],
        )
        _fazer(
            com_versao,
            "INSERT INTO comentarios_chamados (chamado_id, usuario_id, comentario) VALUES (%s, 1, 'oi')",
            [chamado],
        )
        assert _versao(com_versao, chamado) == 1
