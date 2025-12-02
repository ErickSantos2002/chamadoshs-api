-- ============================================
-- CRIAR USUÁRIO INICIAL PARA TESTES
-- ============================================

-- Primeiro, verificar se a migration de autenticação foi executada
-- Se der erro aqui, execute o arquivo migrations/add_auth_fields.sql primeiro
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'usuarios' AND column_name = 'senha_hash';

-- Se retornou 'senha_hash', a migration está OK
-- Caso contrário, execute: \i migrations/add_auth_fields.sql

-- ============================================
-- CRIAR USUÁRIO ADMIN
-- ============================================

-- Deletar admin se já existir (para recriá-lo)
DELETE FROM usuarios WHERE nome = 'admin';

-- Criar usuário admin
-- Username: admin
-- Senha: admin123
INSERT INTO usuarios (nome, senha_hash, role_id, ativo)
VALUES (
  'admin',
  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5FS2B2c5ymNSm',
  1,
  true
);

-- ============================================
-- VERIFICAR SE FOI CRIADO
-- ============================================

SELECT
  id,
  nome,
  role_id,
  CASE
    WHEN senha_hash IS NULL THEN '❌ SEM SENHA'
    WHEN senha_hash = '' THEN '❌ SENHA VAZIA'
    ELSE '✅ SENHA OK'
  END as status_senha,
  CASE
    WHEN ativo = true THEN '✅ ATIVO'
    ELSE '❌ INATIVO'
  END as status_ativo,
  created_at
FROM usuarios
WHERE nome = 'admin';

-- Se aparecer uma linha com:
-- - status_senha: ✅ SENHA OK
-- - status_ativo: ✅ ATIVO
-- Então está tudo certo!

-- ============================================
-- CREDENCIAIS DE LOGIN
-- ============================================

-- Use estas credenciais no frontend:
-- Username: admin
-- Senha: admin123

-- ============================================
-- CRIAR OUTROS USUÁRIOS DE TESTE (OPCIONAL)
-- ============================================

-- Usuário técnico (senha: tecnico123)
INSERT INTO usuarios (nome, senha_hash, role_id, setor_id, ativo)
VALUES (
  'tecnico',
  '$2b$12$Eq.nZ8ZhAKLNH/pMC1vLluOxJ5w0HxF.YgPBvH2Oo1aKQZkXCYL.6',
  2, -- Role: Tecnico
  1, -- Setor: TI
  true
)
ON CONFLICT (nome) DO NOTHING;

-- Usuário comum (senha: user123)
INSERT INTO usuarios (nome, senha_hash, role_id, setor_id, ativo)
VALUES (
  'usuario',
  '$2b$12$8YnZxqJPvF/OZ4YQF4FH3.NJqvdCJCKvjrLXjmYxP9.QH5F5VJXBK',
  3, -- Role: Usuario
  2, -- Setor: ADM
  true
)
ON CONFLICT (nome) DO NOTHING;

-- ============================================
-- LISTAR TODOS OS USUÁRIOS
-- ============================================

SELECT
  u.id,
  u.nome,
  r.nome as role,
  s.nome as setor,
  CASE WHEN u.senha_hash IS NOT NULL AND u.senha_hash != '' THEN '✅' ELSE '❌' END as tem_senha,
  CASE WHEN u.ativo THEN '✅' ELSE '❌' END as ativo
FROM usuarios u
LEFT JOIN roles r ON u.role_id = r.id
LEFT JOIN setores s ON u.setor_id = s.id
ORDER BY u.id;

-- ============================================
-- FIM
-- ============================================
