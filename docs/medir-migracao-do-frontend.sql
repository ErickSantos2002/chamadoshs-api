-- ============================================
-- MEDIR A MIGRAÇÃO DO FRONTEND
-- ============================================
--
-- Rodar no DBeaver, contra produção. Não altera nada — são cinco SELECTs.
--
-- PARA QUE SERVE
--
-- Os passos 3 e 4 do plano de exclusão mudam o contrato de rotas que o
-- frontend usa hoje:
--
--   passo 3 -> DELETE /setores/{id} deixa de desativar e passa a APAGAR
--   passo 4 -> DELETE /usuarios/{id} SAI
--
-- Os dois quebram qualquer cliente que ainda chame o `DELETE` esperando
-- desativação. A pergunta "o frontend já migrou?" precisa de resposta medida,
-- e não de memória de quem mexeu: o front tem três abas que chamam essas
-- rotas, e basta uma ter passado despercebida.
--
-- É para isso que a coluna `origem` existe nas duas trilhas. Ela guarda a rota
-- que gravou cada evento, então o próprio uso responde.
--
-- COMO LER O RESULTADO
--
--   só PATCH aparece    -> o frontend migrou; o passo pode acontecer
--   PATCH e DELETE      -> migração parcial; falta pelo menos uma tela
--   só DELETE           -> nada migrou ainda
--   nada aparece        -> ninguém desativou nada desde o deploy; a medição
--                          ainda não tem o que dizer. Ver a consulta 5.
--
-- ATENÇÃO AO ÚLTIMO CASO. Trilha vazia não é "migrou", é "não sei" — e é o
-- resultado esperado logo depois do deploy, porque a trilha só registra do
-- deploy em diante. Deixe passar tempo de uso real antes de concluir.
--
-- ============================================

-- --------------------------------------------
-- 1. Contas: por onde as desativações chegaram
-- --------------------------------------------
SELECT origem, count(*) AS eventos,
       min(created_at) AS primeiro, max(created_at) AS ultimo
FROM eventos_de_conta
WHERE acao = 'desativacao'
GROUP BY origem
ORDER BY ultimo DESC;

-- `DELETE /api/v1/usuarios/{id}` na lista = o passo 4 ainda quebra o front.


-- --------------------------------------------
-- 2. Setores: a mesma pergunta
-- --------------------------------------------
SELECT origem, count(*) AS eventos,
       min(created_at) AS primeiro, max(created_at) AS ultimo
FROM eventos_de_setor
WHERE acao = 'desativacao'
GROUP BY origem
ORDER BY ultimo DESC;

-- `DELETE /api/v1/setores/{id}` na lista = o passo 3 ainda quebra o front.


-- --------------------------------------------
-- 3. Ainda usa a rota antiga? (resposta direta)
-- --------------------------------------------
SELECT 'usuarios' AS cadastro,
       count(*) FILTER (WHERE origem LIKE 'DELETE%') AS pela_rota_antiga,
       count(*) FILTER (WHERE origem LIKE 'PATCH%')  AS pela_rota_nova
FROM eventos_de_conta WHERE acao = 'desativacao'
UNION ALL
SELECT 'setores',
       count(*) FILTER (WHERE origem LIKE 'DELETE%'),
       count(*) FILTER (WHERE origem LIKE 'PATCH%')
FROM eventos_de_setor WHERE acao = 'desativacao';

-- `pela_rota_antiga = 0` COM `pela_rota_nova > 0` é o sinal verde.
-- `pela_rota_antiga = 0` com `pela_rota_nova = 0` não é sinal nenhum.


-- --------------------------------------------
-- 4. Últimos 30 dias, para não julgar por uso velho
-- --------------------------------------------
--
-- Uma tela migrada há meses ainda tem eventos antigos com a origem antiga. O
-- recorte responde "o que está sendo usado AGORA", que é a pergunta real.
SELECT origem, count(*) AS eventos, max(created_at) AS ultimo
FROM eventos_de_conta
WHERE acao = 'desativacao' AND created_at >= now() - interval '30 days'
GROUP BY origem
ORDER BY ultimo DESC;


-- --------------------------------------------
-- 5. A trilha está viva?
-- --------------------------------------------
--
-- Rodar SEMPRE que as consultas acima vierem vazias, para separar "ninguém
-- desativou nada" de "a imagem nova não subiu / a trilha não está gravando".
SELECT 'eventos_de_conta' AS tabela, count(*) AS linhas,
       min(created_at) AS primeiro, max(created_at) AS ultimo
FROM eventos_de_conta
UNION ALL
SELECT 'eventos_de_setor', count(*), min(created_at), max(created_at)
FROM eventos_de_setor;

-- Zero linhas nas duas, logo após o deploy, é normal: a trilha começa vazia e
-- só registra o que acontecer daqui em diante.
--
-- Zero linhas DEPOIS de dias de uso, com gente editando cadastro, é sinal de
-- que a imagem nova não está no ar — a tabela existe desde 12/08/2026, mas o
-- código que grava nela é o do passo 2.

-- ============================================
-- FIM
-- ============================================
