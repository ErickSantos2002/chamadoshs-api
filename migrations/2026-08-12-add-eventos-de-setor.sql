-- ============================================
-- MIGRATION: trilha de auditoria do cadastro de setores
-- ============================================
--
-- Aplicar ANTES de subir o código que grava nela, como a de `eventos_de_conta`.
-- O model já declara a tabela, e todo POST/PUT/PATCH/DELETE de setor passa a
-- escrever aqui — com o banco antigo, o código novo derruba a edição de setor
-- inteira.
--
-- ESTA É A ÚNICA MIGRATION PENDENTE. A de `eventos_de_conta`
-- (2026-08-12-add-eventos-de-conta.sql), do passo anterior, já foi aplicada em
-- 12/08/2026, à mão pelo DBeaver. As duas são independentes — não se
-- referenciam — então não há ordem a respeitar entre elas.
--
-- Se `eventos_de_conta` estiver vazia no banco, está certo: ela foi criada
-- antes do código que escreve nela, que é o desta entrega e ainda não subiu.
-- Zero linhas ali significa "a imagem nova não foi para o ar", não defeito.
--
-- É `CREATE TABLE` puro — aditivo, não toca em dado existente. Rodar com o
-- deploy atrasado é seguro: tabela vazia que ninguém lê não muda o
-- comportamento da API no ar. Rollback da imagem depois, idem.
--
-- --------------------------------------------
-- POR QUE UMA TABELA SEPARADA
-- --------------------------------------------
--
-- `eventos_de_conta` responde "quem fez o quê com qual conta". A pergunta para
-- setor é a mesma, mas o alvo tem um futuro diferente, e é o futuro do alvo que
-- decide o desenho da coluna.
--
-- Em `eventos_de_conta` o alvo é FK sem ON DELETE, o que faz o banco RECUSAR
-- apagar uma conta que aparece na trilha. Ali isso é o ponto: conta que sai da
-- empresa vira inativa, não sumida, e o histórico existe para não sumir junto.
--
-- Para setor, a mesma FK seria uma armadilha. O passo seguinte torna setor
-- apagável de verdade (hard delete com checagem de vínculo, como categorias), e
-- a FK bloquearia exatamente a exclusão que o produto quer permitir: bastaria
-- um setor ter sido renomeado uma vez para ele nunca mais poder ser apagado. O
-- evento sobreviveria ao setor só para impedi-lo de morrer.
--
-- --------------------------------------------
-- DECISÕES DE FORMATO
-- --------------------------------------------
--
-- 1. ALVO = `setor_id` SEM FOREIGN KEY + `setor_nome` congelado. O par cobre as
--    duas pontas que uma coluna sozinha não cobre:
--
--      setor_id   -> liga os eventos do mesmo setor entre si, e continua
--                    ligando depois de a linha em `setores` deixar de existir.
--      setor_nome -> diz QUE setor era aquele, sem depender de uma consulta
--                    que devolveria o presente (ou, após o hard delete, nada).
--
--    Só o id deixaria a trilha ilegível depois da exclusão; só o nome
--    desmontaria a corrente na primeira renomeação.
--
-- 2. `ator_id` MANTÉM a FK sem ON DELETE, igual a `eventos_de_conta`. Quem agiu
--    não pode evaporar da trilha, e aqui não há conflito com o hard delete —
--    quem se apaga é o setor, não a conta.
--
-- 3. Uma linha por mudança, com `valor_anterior`/`valor_novo` em texto legível,
--    e `acao` sem CHECK. Mesmas razões da tabela irmã: o de/para é o que
--    permite reconstruir a história depois da segunda alteração, e o
--    vocabulário fica em `app/services/evento_setor_service.py` para não
--    exigir migration a cada verbo novo.
--
-- 4. `origem` guarda a rota que gravou, como template. Enquanto o DELETE e os
--    PATCH de desativar/reativar conviverem, é por ela que se mede o que o
--    frontend ainda usa:
--      SELECT origem, count(*) FROM eventos_de_setor GROUP BY origem;
--
-- ============================================

CREATE TABLE IF NOT EXISTS eventos_de_setor (
    id SERIAL PRIMARY KEY,
    setor_id INTEGER NOT NULL,
    setor_nome VARCHAR(100) NOT NULL,
    ator_id INTEGER NOT NULL REFERENCES usuarios(id),
    acao VARCHAR(50) NOT NULL,
    valor_anterior VARCHAR(255),
    valor_novo VARCHAR(255),
    origem VARCHAR(60),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eventos_setor_setor ON eventos_de_setor(setor_id);
CREATE INDEX IF NOT EXISTS idx_eventos_setor_ator ON eventos_de_setor(ator_id);
CREATE INDEX IF NOT EXISTS idx_eventos_setor_data ON eventos_de_setor(created_at);

COMMENT ON TABLE eventos_de_setor IS
  'Trilha de auditoria do cadastro de setores: quem fez o quê com qual setor';
COMMENT ON COLUMN eventos_de_setor.setor_id IS
  'Alvo: o setor que sofreu a mudança. SEM FK de propósito — setor vira apagável e a trilha precisa sobreviver a isso';
COMMENT ON COLUMN eventos_de_setor.setor_nome IS
  'Nome do setor no momento do evento; congelado para a trilha não depender da linha em setores';
COMMENT ON COLUMN eventos_de_setor.ator_id IS 'Quem fez a mudança (usuário autenticado na requisição)';
COMMENT ON COLUMN eventos_de_setor.acao IS
  'criacao, desativacao, reativacao, alteracao_de_nome/descricao';
COMMENT ON COLUMN eventos_de_setor.origem IS
  'Rota que gravou o evento, como template (ex: PATCH /api/v1/setores/{id}/desativar)';

-- ============================================
-- VERIFICAR
-- ============================================

SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'eventos_de_setor'
ORDER BY ordinal_position;

-- Esperado: 9 colunas; setor_id, setor_nome, ator_id e acao com is_nullable = NO.

-- Só UMA foreign key, a do ator, e sem ação de exclusão. Se aparecer uma
-- segunda linha, alguém acrescentou FK para `setores` — e o hard delete do
-- passo seguinte vai bater nela.
SELECT tc.constraint_name, rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.referential_constraints rc
  ON rc.constraint_name = tc.constraint_name
WHERE tc.table_name = 'eventos_de_setor' AND tc.constraint_type = 'FOREIGN KEY';

-- Esperado: uma linha (ator_id), com delete_rule = NO ACTION.

-- ============================================
-- DEPOIS DO DEPLOY
-- ============================================
--
-- A trilha começa vazia e registra do deploy em diante. Primeira conferência,
-- depois de desativar um setor pela tela:
--
-- SELECT e.created_at, ator.nome AS quem, e.setor_nome AS setor,
--        e.acao, e.valor_anterior, e.valor_novo, e.origem
-- FROM eventos_de_setor e
-- JOIN usuarios ator ON ator.id = e.ator_id
-- ORDER BY e.created_at DESC
-- LIMIT 20;

-- ============================================
-- FIM DA MIGRATION
-- ============================================
