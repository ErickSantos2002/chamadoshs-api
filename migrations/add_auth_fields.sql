-- ============================================
-- MIGRATION: Adicionar campo de autenticação
-- ============================================

-- Adicionar campo senha_hash na tabela usuarios
ALTER TABLE usuarios
ADD COLUMN senha_hash VARCHAR(255);

-- Tornar o campo nome UNIQUE para ser usado como username
ALTER TABLE usuarios
ADD CONSTRAINT usuarios_nome_unique UNIQUE (nome);

-- Criar índice no nome para busca rápida no login
CREATE INDEX idx_usuarios_nome_login ON usuarios(nome) WHERE ativo = true;

-- Adicionar comentário
COMMENT ON COLUMN usuarios.senha_hash IS 'Hash bcrypt da senha do usuário';

-- ============================================
-- FIM DA MIGRATION
-- ============================================
