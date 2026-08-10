-- ============================================
-- CRIAR USUÁRIO INICIAL
-- ============================================
--
-- Este script NÃO contém senha. O hash é informado na hora da execução, por
-- variável do psql — o repositório é público e uma senha versionada aqui vale
-- como senha vazada, mesmo depois de trocada.
--
-- --------------------------------------------
-- COMO USAR
-- --------------------------------------------
--
-- 1) Gere o hash da senha escolhida, usando o mesmo algoritmo da API
--    (bcrypt via passlib, exatamente como em app/core/security.py):
--
--      python -c "from passlib.context import CryptContext; \
--        import getpass; \
--        print(CryptContext(schemes=['bcrypt']).hash(getpass.getpass('Senha: ')))"
--
--    getpass evita que a senha fique no histórico do shell.
--
-- 2) Rode o script passando o hash (entre aspas simples — o hash contém $):
--
--      psql -d chamados_db \
--        -v senha_hash_admin="'$2b$12$...'" \
--        -f criar_usuario_inicial.sql
--
--    Para criar também os usuários de teste, acrescente
--    -v senha_hash_tecnico="'...'" e/ou -v senha_hash_usuario="'...'".
--    Sem essas variáveis, os blocos correspondentes são pulados.
--
-- ============================================

-- Pré-requisito: a migration de autenticação precisa ter rodado.
-- Se esta consulta não retornar 'senha_hash', execute antes:
--   \i migrations/add_auth_fields.sql
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'usuarios' AND column_name = 'senha_hash';

-- ============================================
-- CRIAR USUÁRIO ADMIN
-- ============================================

\if :{?senha_hash_admin}
\else
  \echo ''
  \echo 'ERRO: variavel senha_hash_admin nao informada.'
  \echo 'Gere o hash e rode novamente — veja o cabecalho deste arquivo.'
  \echo ''
  \quit
\endif

-- ON CONFLICT DO NOTHING, nunca DELETE + INSERT: um admin já existe em
-- produção, com senha própria. Recriar a conta a partir daqui sobrescreveria
-- essa senha e derrubaria o acesso da equipe de TI.
-- Para trocar a senha de um admin existente, use o UPDATE comentado no fim.
INSERT INTO usuarios (nome, senha_hash, role_id, ativo)
VALUES (
  'admin',
  :senha_hash_admin,
  1,
  true
)
ON CONFLICT (nome) DO NOTHING;

-- ============================================
-- USUÁRIOS DE TESTE (OPCIONAIS)
-- ============================================
-- Só são criados se o hash correspondente for informado na linha de comando.
-- Não crie estes usuários em produção.

\if :{?senha_hash_tecnico}
INSERT INTO usuarios (nome, senha_hash, role_id, setor_id, ativo)
VALUES (
  'tecnico',
  :senha_hash_tecnico,
  2, -- Role: Tecnico
  1, -- Setor: TI
  true
)
ON CONFLICT (nome) DO NOTHING;
\endif

\if :{?senha_hash_usuario}
INSERT INTO usuarios (nome, senha_hash, role_id, setor_id, ativo)
VALUES (
  'usuario',
  :senha_hash_usuario,
  3, -- Role: Usuario
  2, -- Setor: ADM
  true
)
ON CONFLICT (nome) DO NOTHING;
\endif

-- ============================================
-- VERIFICAR
-- ============================================
-- O hash nunca é exibido: este script pode ser rodado com a tela compartilhada.

SELECT
  u.id,
  u.nome,
  r.nome as role,
  s.nome as setor,
  CASE
    WHEN u.senha_hash IS NULL OR u.senha_hash = '' THEN 'SEM SENHA'
    ELSE 'SENHA OK'
  END as status_senha,
  CASE WHEN u.ativo THEN 'ATIVO' ELSE 'INATIVO' END as status_ativo,
  u.created_at
FROM usuarios u
LEFT JOIN roles r ON u.role_id = r.id
LEFT JOIN setores s ON u.setor_id = s.id
ORDER BY u.id;

-- ============================================
-- TROCAR A SENHA DE UM USUÁRIO EXISTENTE
-- ============================================
-- O INSERT acima não altera quem já existe. Para redefinir uma senha,
-- descomente e rode com o hash novo:
--
-- UPDATE usuarios
-- SET senha_hash = :senha_hash_admin, updated_at = CURRENT_TIMESTAMP
-- WHERE nome = 'admin';

-- ============================================
-- FIM
-- ============================================
