-- ============================================
-- MIGRATION: versão do chamado (controle otimista, API-4a)
-- ============================================
--
-- Aplicar ANTES de subir a imagem que traz o campo. O model já declara a
-- coluna, então todo SELECT de chamados passa a pedi-la: código novo contra
-- banco antigo derruba /api/v1/chamados inteiro.
--
-- Aditiva. Rollback da IMAGEM depois desta migration é seguro: a API-3 não
-- conhece a coluna, os INSERTs dela caem no DEFAULT 1, e o trigger continua
-- contando as escritas dela — é o que se quer.
--
-- Esta etapa só PREPARA o controle otimista: a coluna, o trigger que a
-- incrementa e o campo na resposta. Nenhuma rota confere a versão ainda; isso
-- é a API-4b. Até lá a corrida descrita no M-1 continua existindo.
--
-- Escrito para PostgreSQL 15 (o do docker-compose); testado em 16.2 local,
-- num banco descartável. Requer 11+ (ADD COLUMN com DEFAULT constante sem
-- reescrever a tabela, EXECUTE FUNCTION no CREATE TRIGGER).
--
-- --------------------------------------------
-- O QUE A VERSÃO CONTA
-- --------------------------------------------
--
-- `versao` começa em 1 e sobe exatamente 1 a cada UPDATE que muda alguma
-- coluna persistida do chamado — status, responsável, prioridade, solução,
-- cancelado, arquivado, avaliação, qualquer uma, inclusive coluna criada no
-- futuro —, venha a escrita do SQLAlchemy, de SQL direto ou de uma imagem
-- antiga da API.
--
-- NÃO contam, e não sobem a versão sozinhos:
--
--   updated_at        o trigger_chamados_updated_at o reescreve em TODO
--                     UPDATE, até no que não muda nada; contá-lo faria todo
--                     UPDATE parecer mudança.
--   data_atualizacao  o `onupdate` do SQLAlchemy o reescreve em toda escrita
--                     do ORM — é carimbo, não estado.
--   versao            é o próprio contador.
--
-- UPDATE que não muda nada além desses três não sobe a versão. Um UPDATE que
-- muda vários campos sobe uma vez só (o trigger é FOR EACH ROW, por comando).
--
-- A versão nunca vem do comando. No INSERT ela é 1; no UPDATE é derivada de
-- OLD.versao. `UPDATE chamados SET versao = 999` não muda nada (e, como não
-- é mudança, também não sobe). Não há como reduzir, adiantar ou zerar a
-- sequência por UPDATE comum. A função não faz UPDATE nenhum: sem recursão.
--
-- Nada de regra de negócio ou de autorização aqui. Quem decide se uma
-- escrita com versão velha passa é a API (API-4b), com a linha travada.
--
-- --------------------------------------------
-- EXECUÇÃO REPETIDA E ESTADO PARCIAL
-- --------------------------------------------
--
-- São quatro peças: a coluna, o CHECK chk_chamados_versao, a função
-- chamados_versao() e o trigger trigger_chamados_versao. O bloco abaixo olha
-- o banco antes de agir:
--
--   nenhuma das quatro                -> cria as quatro, juntas.
--   as quatro, no formato esperado,
--   e um único trigger usando a função -> não faz nada (NOTICE "já aplicada").
--   qualquer outra combinação         -> ERRO, sem alterar nada.
--
-- "Outra combinação" é, por exemplo, a coluna criada à mão sem o trigger, a
-- função com outro corpo, o trigger AFTER ou só de UPDATE, ou um segundo
-- trigger chamando a mesma função (contaria duas vezes). Corrigir sozinho
-- seria decidir sobre algo que alguém fez de propósito; a migration para e
-- deixa a decisão para quem aplica. Tudo roda numa transação.
--
-- O corpo da função é comparado sem diferença de espaço e quebra de linha:
-- o mesmo texto colado por outra ferramenta continua valendo como igual.
--
-- Rodar como SCRIPT (no DBeaver, "Execute script", Alt+X), não instrução por
-- instrução: o BEGIN/COMMIT e o bloco DO precisam ir inteiros.
--
-- --------------------------------------------
-- ANTES DE RODAR
-- --------------------------------------------
--
--   1. Backup:   pg_dump -Fc -f pre_versao_chamados.dump <banco>
--   2. Conferir: pg_restore --list pre_versao_chamados.dump | head
--
-- Restaurar um dump COMPLETO preserva as versões: o pg_dump cria os triggers
-- depois dos dados. Um restore SÓ DE DADOS (`--data-only`) com o trigger já
-- instalado faria todo chamado voltar para 1 — nesse caso usar
-- `--disable-triggers`.
--
-- --------------------------------------------
-- REVERSÃO DO SCHEMA (só se imprescindível)
-- --------------------------------------------
--
-- Não há automática; o caminho seguro é restaurar o backup. O oposto exato,
-- SÓ DEPOIS de a imagem no ar voltar a ser uma que não declara `versao`
-- (com a API-4a no ar, o DROP COLUMN derruba /chamados na hora):
--
--   -- conferir antes: a imagem no ar é a API-3 ou anterior
--   BEGIN;
--   DROP TRIGGER IF EXISTS trigger_chamados_versao ON chamados;
--   DROP FUNCTION IF EXISTS chamados_versao();
--   ALTER TABLE chamados DROP COLUMN IF EXISTS versao;
--   COMMIT;
--
-- O DROP COLUMN perde as versões, e só elas: nenhum outro dado depende da
-- coluna. Com a API-4b no ar, o front passa a usar a versão para não
-- sobrescrever trabalho alheio; derrubá-la reabre o M-1.
--
-- ============================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $migracao$
DECLARE
    -- O corpo de chamados_versao(). O schema_chamados.sql traz o mesmo texto,
    -- e a reexecução compara contra este.
    corpo CONSTANT text := $corpo$
BEGIN
    -- INSERT: todo chamado nasce na versão 1, diga o comando o que disser.
    IF TG_OP = 'INSERT' THEN
        NEW.versao := 1;
        RETURN NEW;
    END IF;

    -- UPDATE: sobe 1 se alguma coluna persistida mudou, fora os carimbos
    -- automáticos (updated_at, data_atualizacao) e a própria versão. Senão
    -- fica a de antes — inclusive quando o comando tentou gravar outra.
    IF (to_jsonb(NEW) - 'versao' - 'updated_at' - 'data_atualizacao')
       IS DISTINCT FROM
       (to_jsonb(OLD) - 'versao' - 'updated_at' - 'data_atualizacao') THEN
        NEW.versao := OLD.versao + 1;
    ELSE
        NEW.versao := OLD.versao;
    END IF;
    RETURN NEW;
END;
$corpo$;

    esquema         text;
    coluna_tipo     text;
    coluna_nula     text;
    coluna_default  text;
    check_tipo      "char";
    check_validado  boolean;
    check_def       text;
    funcao_oid      oid;
    funcao_src      text;
    funcao_lang     text;
    funcao_ret      text;
    gatilho_tipo    smallint;
    gatilho_ativo   "char";
    gatilho_funcao  oid;
    gatilho_args    smallint;
    gatilho_colunas int2vector;
    gatilho_when    boolean;
    usos_da_funcao  integer;
BEGIN
    IF to_regclass('chamados') IS NULL THEN
        RAISE EXCEPTION 'Tabela chamados não encontrada no search_path atual (%). Nada foi alterado.',
            current_setting('search_path');
    END IF;

    SELECT n.nspname
      INTO esquema
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.oid = 'chamados'::regclass;

    SELECT data_type, is_nullable, column_default
      INTO coluna_tipo, coluna_nula, coluna_default
      FROM information_schema.columns
     WHERE table_schema = esquema
       AND table_name = 'chamados'
       AND column_name = 'versao';

    SELECT contype, convalidated, pg_get_constraintdef(oid)
      INTO check_tipo, check_validado, check_def
      FROM pg_constraint
     WHERE conrelid = 'chamados'::regclass
       AND conname = 'chk_chamados_versao';

    funcao_oid := to_regprocedure(format('%I.chamados_versao()', esquema));
    IF funcao_oid IS NOT NULL THEN
        SELECT p.prosrc, l.lanname, format_type(p.prorettype, NULL)
          INTO funcao_src, funcao_lang, funcao_ret
          FROM pg_proc p
          JOIN pg_language l ON l.oid = p.prolang
         WHERE p.oid = funcao_oid;

        SELECT count(*)
          INTO usos_da_funcao
          FROM pg_trigger
         WHERE tgfoid = funcao_oid
           AND NOT tgisinternal;
    END IF;

    SELECT tgtype, tgenabled, tgfoid, tgnargs, tgattr, tgqual IS NOT NULL
      INTO gatilho_tipo, gatilho_ativo, gatilho_funcao, gatilho_args, gatilho_colunas, gatilho_when
      FROM pg_trigger
     WHERE tgrelid = 'chamados'::regclass
       AND tgname = 'trigger_chamados_versao'
       AND NOT tgisinternal;

    -- Estado 1: nada aplicado ainda.
    IF coluna_tipo IS NULL AND check_def IS NULL AND funcao_oid IS NULL AND gatilho_tipo IS NULL THEN
        ALTER TABLE chamados
            ADD COLUMN versao INTEGER NOT NULL DEFAULT 1
            CONSTRAINT chk_chamados_versao CHECK (versao >= 1);

        EXECUTE format(
            'CREATE FUNCTION %I.chamados_versao() RETURNS trigger LANGUAGE plpgsql AS %L',
            esquema, corpo
        );

        EXECUTE format(
            'CREATE TRIGGER trigger_chamados_versao BEFORE INSERT OR UPDATE ON %I.chamados '
            'FOR EACH ROW EXECUTE FUNCTION %I.chamados_versao()',
            esquema, esquema
        );

        RAISE NOTICE 'versao criada (DEFAULT 1, CHECK chk_chamados_versao), com a função chamados_versao() e o trigger trigger_chamados_versao.';
        RETURN;
    END IF;

    -- Estado parcial: alguma das quatro peças falta.
    IF coluna_tipo IS NULL OR check_def IS NULL OR funcao_oid IS NULL OR gatilho_tipo IS NULL THEN
        RAISE EXCEPTION 'Estado inconsistente da versão dos chamados: coluna versao %, constraint chk_chamados_versao %, função chamados_versao() %, trigger trigger_chamados_versao %. Nada foi alterado.',
            CASE WHEN coluna_tipo IS NULL THEN 'ausente' ELSE 'presente' END,
            CASE WHEN check_def IS NULL THEN 'ausente' ELSE 'presente' END,
            CASE WHEN funcao_oid IS NULL THEN 'ausente' ELSE 'presente' END,
            CASE WHEN gatilho_tipo IS NULL THEN 'ausente' ELSE 'presente' END;
    END IF;

    -- As quatro existem: só aceitar como "já aplicada" se baterem com o esperado.
    IF coluna_tipo <> 'integer'
       OR coluna_nula <> 'NO'
       OR coluna_default IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'chamados.versao existe com formato inesperado (tipo %, nula %, default %). Esperado: integer, NO, 1. Nada foi alterado.',
            coluna_tipo, coluna_nula, coluna_default;
    END IF;

    IF check_tipo <> 'c'
       OR NOT check_validado
       OR regexp_replace(check_def, '[\s()]', '', 'g') <> 'CHECKversao>=1' THEN
        RAISE EXCEPTION 'chk_chamados_versao existe com definição inesperada: % (validada: %). Esperado: CHECK (versao >= 1). Nada foi alterado.',
            check_def, check_validado;
    END IF;

    IF funcao_lang <> 'plpgsql'
       OR funcao_ret <> 'trigger'
       OR btrim(regexp_replace(funcao_src, '\s+', ' ', 'g'))
          <> btrim(regexp_replace(corpo, '\s+', ' ', 'g')) THEN
        RAISE EXCEPTION 'A função chamados_versao() existe com outra definição (linguagem %, retorno %). Nada foi alterado. Confira com: SELECT pg_get_functiondef(''chamados_versao()''::regprocedure);',
            funcao_lang, funcao_ret;
    END IF;

    -- tgtype 23 = ROW (1) + BEFORE (2) + INSERT (4) + UPDATE (16).
    IF gatilho_tipo <> 23
       OR gatilho_ativo <> 'O'
       OR gatilho_funcao <> funcao_oid
       OR gatilho_args <> 0
       OR cardinality(gatilho_colunas::int2[]) <> 0
       OR gatilho_when THEN
        RAISE EXCEPTION 'trigger_chamados_versao existe com definição inesperada: %. Esperado: BEFORE INSERT OR UPDATE, FOR EACH ROW, sem colunas nem WHEN, habilitado, chamando chamados_versao(). Nada foi alterado.',
            pg_get_triggerdef((SELECT oid FROM pg_trigger
                                WHERE tgrelid = 'chamados'::regclass
                                  AND tgname = 'trigger_chamados_versao'));
    END IF;

    IF usos_da_funcao <> 1 THEN
        RAISE EXCEPTION 'chamados_versao() é chamada por % triggers; esperado 1 (trigger_chamados_versao). Dois triggers contariam cada escrita duas vezes. Nada foi alterado. Confira com: SELECT tgrelid::regclass, tgname FROM pg_trigger WHERE tgfoid = ''chamados_versao()''::regprocedure;',
            usos_da_funcao;
    END IF;

    RAISE NOTICE 'versao dos chamados já aplicada e no formato esperado; nada a fazer.';
END
$migracao$;

COMMENT ON COLUMN chamados.versao IS
  'Versão do chamado: começa em 1 e sobe 1 a cada mudança persistida (trigger_chamados_versao). Base do controle otimista.';

COMMENT ON FUNCTION chamados_versao() IS
  'Mantém chamados.versao: 1 no INSERT; OLD.versao + 1 no UPDATE que muda alguma coluna além de versao, updated_at e data_atualizacao.';

COMMIT;

-- ============================================
-- VERIFICAR (somente leitura)
-- ============================================

SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_name = 'chamados' AND column_name = 'versao';

-- Esperado: versao | integer | NO | 1

SELECT conname, convalidated, pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE conrelid = 'chamados'::regclass AND conname = 'chk_chamados_versao';

-- Esperado: 1 linha, convalidated = true, CHECK ((versao >= 1))

SELECT tgname, tgenabled, pg_get_triggerdef(oid)
  FROM pg_trigger
 WHERE tgrelid = 'chamados'::regclass AND NOT tgisinternal
 ORDER BY tgname;

-- Esperado: trigger_chamados_updated_at (o de antes) e trigger_chamados_versao,
-- BEFORE INSERT OR UPDATE ... EXECUTE FUNCTION chamados_versao(), tgenabled = O.

SELECT versao, count(*) FROM chamados GROUP BY versao;
SELECT count(*) AS total FROM chamados;

-- Esperado logo depois de aplicar: uma única linha, versao 1, com a mesma
-- contagem do total.

-- ============================================
-- FIM DA MIGRATION
-- ============================================
