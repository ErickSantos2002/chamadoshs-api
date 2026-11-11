-- ============================================
-- MIGRATION: setor de destino do chamado (TI | QUALIDADE)
-- ============================================
--
-- Aplicar ANTES de subir a imagem que traz o campo. O model já declara a
-- coluna, então todo SELECT de chamados passa a pedi-la: código novo contra
-- banco antigo derruba /api/v1/chamados inteiro.
--
-- Aditiva. Rollback da IMAGEM depois desta migration é seguro: a API antiga
-- não conhece a coluna, e os INSERTs dela caem no DEFAULT 'TI'.
--
-- Reversão do SCHEMA: não há automática — restaurar backup. O oposto exato,
-- se for imprescindível, é `ALTER TABLE chamados DROP COLUMN setor_destino;`,
-- e só depois de voltar a imagem: com a imagem nova no ar, o DROP derruba
-- /chamados na hora. Enquanto a criação de QUALIDADE estiver bloqueada na API,
-- toda linha é TI e o DROP não perde informação; depois disso, perde.
--
-- Escrito e revisado para PostgreSQL 15. Requer 11+ (ADD COLUMN com DEFAULT
-- constante sem reescrever a tabela).
--
-- --------------------------------------------
-- POR QUE
-- --------------------------------------------
--
-- O chamado passa a dizer qual setor o atende: TI (o de sempre) ou Qualidade.
-- Não confundir com o setor de quem abre, que já existe em usuarios.setor_id
-- e continua intocado. Enum em texto com CHECK, sem FK para `setores`: setor é
-- cadastro apagável (DELETE /setores exclui de verdade), e o destino de um
-- chamado não pode depender de uma linha que some.
--
-- --------------------------------------------
-- SEGURANÇA DO DADO EXISTENTE
-- --------------------------------------------
--
-- DEFAULT 'TI' é o que classifica todo chamado existente como TI, e é também
-- o que torna o NOT NULL aplicável numa tabela com linhas. No PostgreSQL 11+ o
-- default constante vira metadado: não há reescrita da tabela. O CHECK faz uma
-- varredura, curta no volume atual, sob trava exclusiva — o lock_timeout faz a
-- migration desistir limpa em vez de enfileirar a API atrás dela.
--
-- --------------------------------------------
-- EXECUÇÃO REPETIDA E ESTADO PARCIAL
-- --------------------------------------------
--
-- O bloco abaixo olha o banco antes de agir:
--
--   coluna ausente E constraint ausente -> cria as duas, juntas.
--   coluna presente E constraint presente, ambas no formato esperado
--                                        -> não faz nada (NOTICE "já aplicada").
--   qualquer outra combinação           -> ERRO, sem alterar nada.
--
-- "Outra combinação" é, por exemplo, a coluna criada à mão sem o CHECK, ou com
-- outro tipo ou outro default. Corrigir isso automaticamente exigiria decidir
-- sobre dado que alguém gravou de propósito; a migration para e deixa a
-- decisão para quem aplica. Tudo roda numa transação: ou a coluna nasce com o
-- CHECK, ou nada muda.
--
-- Rodar como SCRIPT (no DBeaver, "Execute script", Alt+X), não instrução por
-- instrução: o BEGIN/COMMIT e o bloco DO precisam ir inteiros.
--
-- --------------------------------------------
-- ANTES DE RODAR
-- --------------------------------------------
--
--   1. Backup:   pg_dump -Fc -f pre_setor_destino.dump <banco>
--   2. Conferir: pg_restore --list pre_setor_destino.dump | head
--
-- ============================================

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $$
DECLARE
    coluna_tipo     text;
    coluna_tamanho  integer;
    coluna_nula     text;
    coluna_default  text;
    check_tipo      "char";
    check_validado  boolean;
    check_def       text;
    check_valores   text[];
BEGIN
    IF to_regclass('chamados') IS NULL THEN
        RAISE EXCEPTION 'Tabela chamados não encontrada no search_path atual (%). Nada foi alterado.',
            current_setting('search_path');
    END IF;

    SELECT data_type, character_maximum_length, is_nullable, column_default
      INTO coluna_tipo, coluna_tamanho, coluna_nula, coluna_default
      FROM information_schema.columns
     WHERE table_schema = (SELECT n.nspname
                             FROM pg_class c
                             JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE c.oid = 'chamados'::regclass)
       AND table_name = 'chamados'
       AND column_name = 'setor_destino';

    SELECT contype, convalidated, pg_get_constraintdef(oid)
      INTO check_tipo, check_validado, check_def
      FROM pg_constraint
     WHERE conrelid = 'chamados'::regclass
       AND conname = 'chk_setor_destino';

    -- Estado 1: nada aplicado ainda.
    IF coluna_tipo IS NULL AND check_def IS NULL THEN
        ALTER TABLE chamados
            ADD COLUMN setor_destino VARCHAR(20) NOT NULL DEFAULT 'TI'
            CONSTRAINT chk_setor_destino CHECK (setor_destino IN ('TI', 'QUALIDADE'));
        RAISE NOTICE 'setor_destino criada com DEFAULT ''TI'' e CHECK chk_setor_destino.';
        RETURN;
    END IF;

    -- Estado parcial: só uma das duas existe.
    IF coluna_tipo IS NULL THEN
        RAISE EXCEPTION 'Estado inconsistente: a constraint chk_setor_destino existe, mas a coluna chamados.setor_destino não. Nada foi alterado. Constraint encontrada: %', check_def;
    END IF;
    IF check_def IS NULL THEN
        RAISE EXCEPTION 'Estado inconsistente: a coluna chamados.setor_destino existe, mas a constraint chk_setor_destino não. Nada foi alterado. Confira com: SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = ''chamados''::regclass;';
    END IF;

    -- As duas existem: só aceitar como "já aplicada" se baterem com o esperado.
    IF coluna_tipo <> 'character varying'
       OR coluna_tamanho IS DISTINCT FROM 20
       OR coluna_nula <> 'NO'
       OR coluna_default IS NULL
       OR coluna_default NOT LIKE '''TI''%' THEN
        RAISE EXCEPTION 'chamados.setor_destino existe com formato inesperado (tipo %, tamanho %, nula %, default %). Esperado: character varying, 20, NO, ''TI''. Nada foi alterado.',
            coluna_tipo, coluna_tamanho, coluna_nula, coluna_default;
    END IF;

    -- Os valores aceitos são lidos dos literais da definição, e não comparando
    -- o texto inteiro: o PostgreSQL reescreve `IN (...)` como `= ANY (ARRAY...)`
    -- e o formato exato dessa reescrita não é contrato.
    SELECT array_agg(m[1] ORDER BY m[1])
      INTO check_valores
      FROM regexp_matches(check_def, '''([^'']*)''', 'g') AS m;

    IF check_tipo <> 'c'
       OR NOT check_validado
       OR check_def NOT LIKE '%setor_destino%'
       OR check_valores IS DISTINCT FROM ARRAY['QUALIDADE', 'TI'] THEN
        RAISE EXCEPTION 'chk_setor_destino existe com definição inesperada: % (validada: %). Esperado: CHECK de setor_destino em (''TI'', ''QUALIDADE''). Nada foi alterado.',
            check_def, check_validado;
    END IF;

    RAISE NOTICE 'setor_destino já aplicada e no formato esperado; nada a fazer.';
END
$$;

COMMENT ON COLUMN chamados.setor_destino IS
  'Setor que atende o chamado (TI | QUALIDADE). NÃO é o setor do solicitante (usuarios.setor_id)';

COMMIT;

-- ============================================
-- VERIFICAR (somente leitura)
-- ============================================

SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_name = 'chamados' AND column_name = 'setor_destino';

-- Esperado: setor_destino | character varying | 20 | NO | 'TI'::character varying

SELECT conname, convalidated, pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE conrelid = 'chamados'::regclass AND conname = 'chk_setor_destino';

-- Esperado: 1 linha, convalidated = true, CHECK com 'TI' e 'QUALIDADE'

SELECT setor_destino, count(*) FROM chamados GROUP BY setor_destino;
SELECT count(*) AS total FROM chamados;

-- Esperado: uma única linha, TI, com a mesma contagem do total.

-- ============================================
-- FIM DA MIGRATION
-- ============================================
