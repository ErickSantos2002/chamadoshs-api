-- ============================================
-- MIGRATION: marca contas de serviço no cadastro de usuários
-- ============================================
--
-- Aplicar ANTES de subir o código que expõe o campo.
-- Reversão: não há automática — restaurar backup. (Se for imprescindível
-- desfazer, o oposto exato é: ALTER TABLE usuarios DROP COLUMN conta_de_servico;)
--
-- --------------------------------------------
-- POR QUE
-- --------------------------------------------
--
-- Algumas contas não são pessoas: a conta compartilhada de administração, o
-- painel de parede que exibe os chamados e o login usado via FortiPAM. Elas
-- aparecem no seletor de "Técnico Responsável" junto com gente de verdade.
--
-- Desativar não serve: as três precisam autenticar, e `get_current_user`
-- recusa usuário inativo. Faltava um jeito de dizer o que a conta É.
--
-- O campo descreve a natureza da conta, não uma permissão derivada dela. Se
-- amanhã outro lugar precisar ignorar não-pessoas — um relatório de
-- solicitantes mais frequentes, por exemplo — o mesmo campo serve.
--
-- --------------------------------------------
-- SEGURANÇA DO DADO EXISTENTE
-- --------------------------------------------
--
-- DEFAULT false é obrigatório aqui, por dois motivos:
--
--   1. ADD COLUMN NOT NULL sem DEFAULT falha numa tabela com linhas.
--   2. Toda conta existente precisa continuar sendo tratada como pessoa. Com
--      DEFAULT true, o seletor de técnico esvaziaria no instante do deploy.
--
-- As contas de serviço são marcadas à mão depois (ver o fim do arquivo).
--
-- ============================================

ALTER TABLE usuarios
ADD COLUMN IF NOT EXISTS conta_de_servico BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN usuarios.conta_de_servico IS
  'true quando a conta não representa uma pessoa (painel, integração, login compartilhado)';

-- ============================================
-- VERIFICAR
-- ============================================

SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'usuarios' AND column_name = 'conta_de_servico';

-- Esperado: boolean | NO | false

-- ============================================
-- MARCAR AS CONTAS DE SERVIÇO
-- ============================================
--
-- Passo separado, de propósito: a migration só cria a estrutura, e marcar
-- conta errada tira alguém do seletor de técnico sem aviso.
--
-- Confira quem são antes de marcar:

SELECT id, nome, role_id, ativo, conta_de_servico
FROM usuarios
WHERE nome IN ('admin', 'televisao', 'fortipam')
ORDER BY nome;

-- Conferido, descomente e rode:
--
-- UPDATE usuarios
-- SET conta_de_servico = true, updated_at = CURRENT_TIMESTAMP
-- WHERE nome IN ('admin', 'televisao', 'fortipam');
--
-- O WHERE é por nome e a coluna é UNIQUE (usuarios_nome_unique), então cada
-- literal atinge no máximo uma linha. Confira que o retorno foi UPDATE 3.

-- ============================================
-- FIM DA MIGRATION
-- ============================================
