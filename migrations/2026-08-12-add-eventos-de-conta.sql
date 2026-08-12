-- ============================================
-- MIGRATION: trilha de auditoria do cadastro de usuários
-- ============================================
--
-- Aplicar ANTES de subir o código que grava nela. O model já declara a tabela,
-- e todo POST/PUT/DELETE de usuário passa a escrever aqui — com o banco antigo,
-- o código novo derruba a edição de cadastro inteira.
--
-- Rodar esta migration antes do deploy é seguro mesmo que o deploy atrase: uma
-- tabela vazia que ninguém lê não muda o comportamento da API que está no ar.
-- Rollback da imagem depois de aplicá-la também é seguro, pelo mesmo motivo.
--
-- É `CREATE TABLE` puro — aditivo, não toca em dado existente, não altera
-- nenhuma tabela atual. Reversão: não há automática, e não é necessária
-- (`DROP TABLE eventos_de_conta;` é o oposto exato, e só faz sentido antes de
-- a tabela ter recebido linha nenhuma — depois disso ele apaga a trilha, que é
-- o dano que a tabela existe para impedir).
--
-- --------------------------------------------
-- POR QUE
-- --------------------------------------------
--
-- O sistema atende ISO 27001 e não respondia "quem fez o quê com qual conta, e
-- quando". As três fontes possíveis não servem:
--
--   historico_chamados  -> escopado por chamado: `chamado_id` é NOT NULL e a FK
--                          é ON DELETE CASCADE. Evento de usuário não cabe, e o
--                          que coubesse sumiria com o chamado.
--   usuarios.updated_at -> sobrescrito por qualquer edição e sem autor. Diz que
--                          algo mudou, nunca o quê nem por quem.
--   log da aplicação    -> não é retido, não é consultável e não é evidência.
--
-- --------------------------------------------
-- DECISÕES DE FORMATO
-- --------------------------------------------
--
-- 1. ATOR e ALVO em colunas separadas (`ator_id` e `usuario_id`). "A conta X
--    foi desativada" sem dizer por quem não é auditoria.
--
-- 2. NENHUMA das duas FKs tem ON DELETE. No PostgreSQL isso é NO ACTION:
--    apagar uma conta que aparece na trilha passa a ser recusado pelo banco.
--    É o mesmo raciocínio das FKs de `chamados` para `usuarios`, e é o ponto
--    inteiro da tabela — com CASCADE, a trilha morreria junto com a conta,
--    isto é, no exato caso em que ela é procurada.
--
-- 3. Uma linha por mudança, com `valor_anterior` e `valor_novo`. Guardar só
--    "perfil alterado" tornaria impossível reconstruir o de/para depois da
--    segunda alteração. Os valores são texto legível — NOME do perfil e do
--    setor, não id: o nome congela o que o valor significava naquele momento,
--    enquanto o id depende de uma consulta que devolve o presente.
--
--    `(nenhum)` é o texto usado quando o campo estava vazio (`setor_id` é
--    anulável). NULL nos dois campos significa evento sem valores, que é o
--    caso da senha: nem senha nem hash entram na trilha.
--
-- 4. `acao` sem CHECK, como `historico_chamados.acao`. O vocabulário fica em
--    `app/services/evento_conta_service.py`, único lugar do código que escreve
--    nesta tabela. Um CHECK exigiria migration a cada verbo novo, e os verbos
--    ainda vão crescer nos próximos passos.
--
-- 5. `origem` guarda a rota que gravou, como template. Enquanto o DELETE e os
--    PATCH de desativar/reativar conviverem, é por ela que se mede o que o
--    frontend ainda usa:
--      SELECT origem, count(*) FROM eventos_de_conta GROUP BY origem;
--
-- ============================================

CREATE TABLE IF NOT EXISTS eventos_de_conta (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    ator_id INTEGER NOT NULL REFERENCES usuarios(id),
    acao VARCHAR(50) NOT NULL,
    valor_anterior VARCHAR(255),
    valor_novo VARCHAR(255),
    origem VARCHAR(60),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_eventos_conta_usuario ON eventos_de_conta(usuario_id);
CREATE INDEX IF NOT EXISTS idx_eventos_conta_ator ON eventos_de_conta(ator_id);
CREATE INDEX IF NOT EXISTS idx_eventos_conta_data ON eventos_de_conta(created_at);

COMMENT ON TABLE eventos_de_conta IS
  'Trilha de auditoria do cadastro de usuários: quem fez o quê com qual conta';
COMMENT ON COLUMN eventos_de_conta.usuario_id IS 'Alvo: a conta que sofreu a mudança';
COMMENT ON COLUMN eventos_de_conta.ator_id IS 'Quem fez a mudança (usuário autenticado na requisição)';
COMMENT ON COLUMN eventos_de_conta.acao IS
  'criacao, desativacao, reativacao, alteracao_de_nome/perfil/setor/senha/conta_de_servico';
COMMENT ON COLUMN eventos_de_conta.valor_anterior IS
  'Valor antes da mudança, em texto legível; NULL em evento sem valores (senha)';
COMMENT ON COLUMN eventos_de_conta.valor_novo IS
  'Valor depois da mudança, em texto legível; nunca guarda senha nem hash';
COMMENT ON COLUMN eventos_de_conta.origem IS
  'Rota que gravou o evento, como template (ex: PUT /api/v1/usuarios/{id})';

-- ============================================
-- VERIFICAR
-- ============================================

SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'eventos_de_conta'
ORDER BY ordinal_position;

-- Esperado: 8 colunas; usuario_id, ator_id e acao com is_nullable = NO.

-- As duas FKs precisam estar SEM ação de exclusão. Se alguma linha voltar
-- delete_rule diferente de NO ACTION, a trilha é apagável e a tabela não
-- cumpre o que promete.
SELECT tc.constraint_name, rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.referential_constraints rc
  ON rc.constraint_name = tc.constraint_name
WHERE tc.table_name = 'eventos_de_conta' AND tc.constraint_type = 'FOREIGN KEY';

-- Esperado: duas linhas, ambas com delete_rule = NO ACTION.

-- ============================================
-- DEPOIS DO DEPLOY
-- ============================================
--
-- A trilha começa vazia e passa a registrar do deploy em diante. O que
-- aconteceu antes não é recuperável — não existe fonte de onde reconstruir, e
-- é por isso que este passo veio antes dos endpoints novos.
--
-- Primeira conferência, depois de editar um usuário pela tela:
--
-- SELECT e.created_at, ator.nome AS quem, alvo.nome AS conta,
--        e.acao, e.valor_anterior, e.valor_novo, e.origem
-- FROM eventos_de_conta e
-- JOIN usuarios ator ON ator.id = e.ator_id
-- JOIN usuarios alvo ON alvo.id = e.usuario_id
-- ORDER BY e.created_at DESC
-- LIMIT 20;

-- ============================================
-- FIM DA MIGRATION
-- ============================================
