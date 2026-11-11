-- =====================================================================
-- API-6 — Diagnóstico de cadastro para definir SETORES_TI_IDS
-- =====================================================================
--
-- SOMENTE LEITURA. Para o operador autorizado rodar, com psql, no banco do
-- ambiente que vai receber a API-6 — ANTES do deploy dela. Nada aqui grava:
-- a transação é READ ONLY (o PostgreSQL recusa qualquer escrita dentro dela)
-- e termina em ROLLBACK.
--
--   psql "$DATABASE_URL" -v setores_ti='{}' -f diagnosticos/api6_setores_ti.sql
--
-- `setores_ti` é a lista CANDIDATA, no formato de array do PostgreSQL:
-- '{}' (nenhum), '{1}', '{1,7}'. Rode primeiro com '{}' (consultas 1 a 4 e
-- 7 bastam para escolher), decida os ids com quem conhece a equipe, e rode
-- de novo com a lista escolhida para ver as consultas 5, 6 e 8. A lista vai
-- para SETORES_TI_IDS no formato "1,7".
--
-- A decisão dos ids é HUMANA: o nome do setor ajuda a procurar, mas não diz
-- quem é da TI. "Suporte", por exemplo, pode ser ou não ser — confirme com
-- a gestão antes de incluir. Não cole o resultado (nomes de pessoas) em
-- chamado, documentação ou commit.
--
-- O perfil é comparado sem acento e sem caixa, como a API compara: um role
-- gravado "Técnico" conta como técnico.
-- =====================================================================

\set ON_ERROR_STOP on
BEGIN READ ONLY;

-- 1. Setores existentes, com quantos técnicos e quantas pessoas ativas têm.
SELECT s.id, s.nome, s.ativo,
       count(u.id) FILTER (WHERE u.ativo) AS pessoas_ativas,
       count(u.id) FILTER (WHERE u.ativo AND translate(lower(r.nome), 'áéíóúâêôãõç', 'aeiouaeoaoc') = 'tecnico') AS tecnicos_ativos,
       count(u.id) FILTER (WHERE u.ativo AND translate(lower(r.nome), 'áéíóúâêôãõç', 'aeiouaeoaoc') = 'administrador') AS administradores_ativos
FROM setores s
LEFT JOIN usuarios u ON u.setor_id = s.id
LEFT JOIN roles r ON r.id = u.role_id
GROUP BY s.id, s.nome, s.ativo
ORDER BY s.id;

-- 2. Técnicos ativos e seus setores.
SELECT u.id, u.nome, r.nome AS perfil, u.setor_id, s.nome AS setor, s.ativo AS setor_ativo, u.conta_de_servico
FROM usuarios u
JOIN roles r ON r.id = u.role_id
LEFT JOIN setores s ON s.id = u.setor_id
WHERE u.ativo
  AND translate(lower(r.nome), 'áéíóúâêôãõç', 'aeiouaeoaoc') = 'tecnico'
ORDER BY u.setor_id NULLS FIRST, u.nome;

-- 3. Técnicos ativos SEM setor (H1: só leem pelo vínculo; regularizar antes).
SELECT u.id, u.nome, r.nome AS perfil
FROM usuarios u
JOIN roles r ON r.id = u.role_id
WHERE u.ativo
  AND u.setor_id IS NULL
  AND translate(lower(r.nome), 'áéíóúâêôãõç', 'aeiouaeoaoc') = 'tecnico'
ORDER BY u.nome;

-- 4. Quem é responsável por chamado da TI hoje, por perfil e setor.
SELECT u.id, u.nome, r.nome AS perfil, u.setor_id, s.nome AS setor, u.ativo, u.conta_de_servico,
       count(*) AS chamados_ti,
       count(*) FILTER (WHERE NOT c.cancelado AND NOT c.arquivado
                          AND c.status NOT IN ('Resolvido', 'Fechado')) AS chamados_ti_em_aberto
FROM chamados c
JOIN usuarios u ON u.id = c.tecnico_responsavel_id
JOIN roles r ON r.id = u.role_id
LEFT JOIN setores s ON s.id = u.setor_id
WHERE c.setor_destino = 'TI'
GROUP BY u.id, u.nome, r.nome, u.setor_id, s.nome, u.ativo, u.conta_de_servico
ORDER BY chamados_ti DESC;

-- 5. Responsáveis atuais de chamado da TI FORA da lista candidata (D9).
--    Não serão trocados pela API-6: o chamado continua com eles, mas ninguém
--    novo fora da equipe pode ser atribuído, e eles próprios só leem o
--    chamado pelo vínculo.
SELECT c.id AS chamado_id, c.protocolo, c.status, c.cancelado, c.arquivado,
       u.id AS responsavel_id, u.nome, r.nome AS perfil, u.setor_id
FROM chamados c
JOIN usuarios u ON u.id = c.tecnico_responsavel_id
JOIN roles r ON r.id = u.role_id
WHERE c.setor_destino = 'TI'
  AND (u.setor_id IS NULL OR u.setor_id <> ALL (:'setores_ti'::int[])
       OR translate(lower(r.nome), 'áéíóúâêôãõç', 'aeiouaeoaoc') NOT IN ('tecnico', 'administrador'))
ORDER BY c.id;

-- 6. Contas de serviço envolvidas: com perfil de equipe ou responsáveis por
--    algum chamado (o PUT já recusa atribuir a elas; isto acha o legado).
SELECT u.id, u.nome, r.nome AS perfil, u.setor_id, u.ativo,
       (SELECT count(*) FROM chamados c WHERE c.tecnico_responsavel_id = u.id) AS chamados_atribuidos
FROM usuarios u
JOIN roles r ON r.id = u.role_id
WHERE u.conta_de_servico
  AND (translate(lower(r.nome), 'áéíóúâêôãõç', 'aeiouaeoaoc') IN ('tecnico', 'administrador')
       OR EXISTS (SELECT 1 FROM chamados c WHERE c.tecnico_responsavel_id = u.id))
ORDER BY u.id;

-- 7. Setores que PODEM ser de suporte técnico — só pistas, para a conversa
--    com a gestão: têm técnico ativo, atendem chamado da TI, ou o nome lembra
--    TI/suporte. Nenhum entra na lista por aparecer aqui.
SELECT s.id, s.nome, s.ativo,
       EXISTS (SELECT 1 FROM usuarios u JOIN roles r ON r.id = u.role_id
               WHERE u.setor_id = s.id AND u.ativo
                 AND translate(lower(r.nome), 'áéíóúâêôãõç', 'aeiouaeoaoc') = 'tecnico') AS tem_tecnico_ativo,
       EXISTS (SELECT 1 FROM chamados c JOIN usuarios u ON u.id = c.tecnico_responsavel_id
               WHERE u.setor_id = s.id AND c.setor_destino = 'TI') AS atende_chamado_ti,
       (s.nome ILIKE '%suporte%' OR s.nome ILIKE 'ti' OR s.nome ILIKE '%informática%'
        OR s.nome ILIKE '%tecnologia%') AS nome_sugere
FROM setores s
ORDER BY s.id;

-- 8. Quem perde o alcance por perfil com a lista candidata: técnicos ativos
--    cujo setor não está nela (nem é o da Qualidade, que tem regra própria —
--    confira o id dela em SETOR_QUALIDADE_ID). Passam a ler e alterar só
--    pelo vínculo.
SELECT u.id, u.nome, r.nome AS perfil, u.setor_id, s.nome AS setor
FROM usuarios u
JOIN roles r ON r.id = u.role_id
LEFT JOIN setores s ON s.id = u.setor_id
WHERE u.ativo
  AND translate(lower(r.nome), 'áéíóúâêôãõç', 'aeiouaeoaoc') = 'tecnico'
  AND (u.setor_id IS NULL OR u.setor_id <> ALL (:'setores_ti'::int[]))
ORDER BY u.setor_id NULLS FIRST, u.nome;

ROLLBACK;
