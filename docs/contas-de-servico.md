# Contas de serviço — menor privilégio (API-10 e API-11)

Conta de serviço é a conta que não é uma pessoa: `usuarios.conta_de_servico =
true` (migration `2026-08-10-add-conta-de-servico.sql`). A migration cita três
usos reais: **a conta compartilhada de administração**, **o painel de parede**
que exibe os chamados e **o login usado via FortiPAM**. Nenhum deles foi
conferido no banco de produção por este trabalho — ver "Inventário pendente".

A regra é uma só: **conta de serviço lê o que o perfil deixa ler e não age
como equipe nem como administrador.** O que ela ainda faz é o que qualquer
conta faz pelo próprio vínculo. Só `conta_de_servico` igual a `False` conta
como pessoa: `None` (o ORM antes do flush) ou outro valor não prova que a
conta é humana. No banco a coluna é `NOT NULL DEFAULT false`, então o caso só
existe como defesa.

## O que cada conta de serviço faz

| | Técnico de serviço (qualquer setor) | Administrador de serviço | Usuário de serviço |
|---|---|---|---|
| Login, `/auth/me`, renovar, `/auth/alterar-senha` (a própria) | sim | sim | sim |
| `integra_equipe_ti` no `/auth/me` | `false` (API-10) | `false` (API-10) | `false` |
| Ler chamados | pelo alcance do perfil (API-5) | todos, pelo perfil | os que abriu ou atende |
| `GET /usuarios/` | sim (só autenticação; inalterado) | sim | sim |
| Abrir chamado próprio, comentar em público, avaliar o próprio, cancelar o que abriu | sim | sim | sim |
| `PUT`, arquivar, desarquivar, cancelar alheio, reatribuir | **403** `"Conta de serviço não altera chamado como equipe"` (API-11, S2) | **403**, idem | 403 de perfil |
| Abrir chamado em nome de outro (`solicitante_id`) | ignorado: o solicitante é a própria conta | **ignorado** (API-11, S3) | ignorado |
| Editar ou excluir comentário alheio | não | **não** (API-11, S3) | não |
| Comentário interno | não (API-10) | **não** (API-11, S3) | não |
| `require_equipe_ti`: setores, categorias, SLA, tarefas, trilha de setor, responsáveis da TI | 403 (API-10) | **403** (API-11, S3) | 403 |
| `require_admin`: usuários (criar, editar, senha alheia, perfil, setor, `conta_de_servico`, desativar, reativar, eventos), `POST /auth/registro`, excluir chamado e setor, diagnóstico | 403 de perfil | **403** `"Conta de serviço não executa administração"` (API-11, S3) | 403 de perfil |
| Ser responsável de chamado da TI | não (API-9) | não | não |
| Contar como "último administrador ativo" | — | **não** (API-11, S4) | — |
| `GET /tarefas-recorrentes/lembretes-do-dia` | **403** (API-11, S1) | **403** | 403 |

Nas recusas: nada é gravado — nem o chamado, nem a versão, nem o histórico,
nem webhook. O 404 de quem não lê o chamado vem antes do 403, e o 401/409/428
seguem como eram.

## Onde mora a regra

| Regra | Onde |
|---|---|
| Equipe da TI | `integra_equipe_ti` (`app/services/leitura_service.py`) — API-10 |
| Escrita de equipe | `pode_alterar_como_equipe` e `buscar_chamado_alteravel` (mesmo arquivo) — API-11, S2 |
| Administrador humano | `is_admin_humano` e `require_admin` (`app/api/deps.py`) — API-11, S3 |
| Leitura | `is_admin` (perfil só) e `setores_lidos_pelo_perfil` — inalterados |
| Último administrador | `_outros_admins_humanos_ativos` e `_garantir_que_resta_admin_humano` (`app/api/endpoints/usuarios.py`) — API-11, S4 |
| Registro | `UsuarioCreate` de `app/schemas/auth.py` — API-11, S5 |

Nenhuma rota tem exceção por nome, IP, `User-Agent`, parâmetro do cliente ou id.

## Último administrador humano (S4)

Só conta quem é ativo, administrador e `conta_de_servico = false`. A trava
avalia o estado final da conta com tudo o que o `PUT` muda junto (perfil,
`ativo`, `conta_de_servico`) e vale também no `PATCH .../desativar` e no
`DELETE`. A contagem trava as linhas (`SELECT ... FOR UPDATE`): dois
administradores removendo um ao outro ao mesmo tempo deixam um — provado em
PostgreSQL com a sincronização da API-4c (sem a trava, os três cenários
falham).

**Banco sem administrador humano** (só a conta compartilhada administrava): a
API-11 não cria atalho. A conta de serviço recebe 403 em toda administração,
inclusive para se tornar pessoa, reativar alguém ou criar conta. A recuperação
é a do primeiro usuário, fora da API, com registro de mudança:

1. Abrir registro de mudança (quem pediu, quem executa, por quê).
2. Backup (`pg_dump -Fc`).
3. Criar **uma conta nominativa** de administrador com
   `criar_usuario_inicial.sql` (hash gerado como em AUTH.md, "Criar Primeiro
   Usuário"), para uma pessoa identificada — nunca converter a conta
   compartilhada em "pessoa".
4. A pessoa entra e troca a senha (`/auth/alterar-senha`).
5. Anotar no registro de mudança: o SQL direto **não** grava evento de conta.

Isto é um procedimento documentado; nada dele foi executado.

## Inventário pendente (antes do deploy)

Nada disto foi conferido: todo trabalho foi local, sem acesso a produção. Cada
item é uma consulta só de leitura ou uma pergunta ao responsável.

- [ ] **Contas de serviço reais:** `SELECT id, nome, role_id, setor_id, ativo FROM usuarios WHERE conta_de_servico ORDER BY id;`
- [ ] **Perfil e setor de cada uma**, e se o setor está em `SETORES_TI_IDS` ou é o `SETOR_QUALIDADE_ID`.
- [ ] **Status da migration** `2026-08-10-add-conta-de-servico.sql` e do `UPDATE` comentado no fim dela (as contas foram marcadas?).
- [ ] **Administradores humanos ativos:** `SELECT id, nome FROM usuarios u JOIN roles r ON r.id = u.role_id WHERE r.nome = 'Administrador' AND u.ativo AND NOT u.conta_de_servico;` — **se der zero, não subir a API-11** antes de executar a recuperação acima: a administração ficaria sem ninguém.
- [ ] **A conta compartilhada de administração:** quem a usa hoje, para quê, e por onde (FortiPAM?).
- [ ] **FortiPAM:** quais contas o cofre entrega, a quem, e se alguma pessoa administra por uma conta de serviço.
- [ ] **A conta da TV:** qual é (id, nome, perfil, setor), em que máquina roda, quem tem a senha.
- [ ] **Integrações:** alguma automação usa a API com conta de serviço? (O n8n hoje só recebe webhook.)
- [ ] **n8n com acesso direto ao banco:** se existir, ele escreve fora da API e fora de toda esta regra — conferir credencial e permissões dele no PostgreSQL.
- [ ] **Versão em produção:** qual imagem da API está no ar (`GET /` / `/health`, ver memória de endereços) e qual front.

## Painel de parede (S1) — bloqueado

O quadro de chamados do frontend é o painel de parede: atualiza
`GET /chamados/` a cada 10 minutos e, se `podeAdministrar`, também
`GET /tarefas-recorrentes/?ativo=true`, para o lembrete "tarefas do dia".
`GET /usuarios/` roda uma vez, na montagem.

**O que a API-11 entregou:** `GET /tarefas-recorrentes/lembretes-do-dia`, com
só `id`, `titulo`, `proxima_data` e `situacao` (`atrasada`, `hoje`,
`realizada_hoje`), o dia de Brasília em `data`, ordem por próxima data e id, só
leitura. Mesma regra do quadro: tarefas ativas que vencem até hoje e as
realizadas hoje. Quem lê: administrador humano e técnico da TI. **Nenhuma
conta de serviço, inclusive a da TV.**

**Por que bloqueado:** não existe hoje um jeito seguro de dizer "esta conta é
a TV". Nome, perfil, `conta_de_servico`, IP, `User-Agent`, parâmetro e id
inventado não servem — qualquer um deles libera mais do que a TV, ou é
falsificável. Liberar a rota para toda conta de serviço seria a autorização
genérica que a API-11 proíbe.

**Opções** (cada uma precisa de autorização; nenhuma foi implementada):

| | Como | Custo | Falha segura |
|---|---|---|---|
| **A. Lista por configuração** (recomendada) | `PAINEL_CONTAS_IDS` no ambiente, com os ids **conferidos no inventário**; a rota aceita a conta se estiver na lista **e** for `conta_de_servico` ativa | Variável nova; sem migration; só esta rota | Vazia por padrão: ninguém |
| B. Permissão por conta | Coluna `pode_ler_painel` (migration), editável pelo administrador humano, com evento de conta | Migration, front de cadastro, trilha | `false` por padrão |
| C. Perfil "Painel" | Role nova, só leitura | Mexe em todo `require_roles`, no `roleMapper` do front e nas políticas de leitura | Precisa revisar todas as rotas |

Em qualquer opção a rota continua só leitura e não abre nenhuma das sete
rotas de tarefas.

## Dependência do FE-5 (sem mudar o frontend)

- **TV como técnico de serviço:** desde a API-10, `podeAdministrar` é falso e
  o quadro nem pede as tarefas: o lembrete some. A API-11 não muda isso.
- **TV como administrador de serviço:** `podeAdministrar` segue verdadeiro
  (vem do `role`), então o quadro continua pedindo
  `GET /tarefas-recorrentes/?ativo=true` a cada 10 minutos, e agora recebe
  403 — o lembrete some e a tela pode mostrar o aviso de erro a cada ciclo. O
  menu de administração também aparece e devolve 403 em tudo.
- **O que o front precisa (FE futuro, não iniciado):** o lembrete passar a usar
  `lembretes-do-dia` sem depender de `podeAdministrar`, tratar o 403 dela em
  silêncio (sem toast), e esconder a administração de conta de serviço — o
  `/auth/me` não diz hoje se a conta é de serviço; seria preciso expor isso,
  ou um `pode_administrar` calculado pela API.

## Plano de migração nominativa (não executado)

Para tirar pessoas da conta compartilhada. Cada passo é uma decisão humana;
nada foi feito, e nenhuma conta real foi alterada.

1. Fazer o inventário acima e anexar o resultado ao registro de mudança.
2. Para cada conta de serviço, nomear o dono (pessoa responsável) e o uso.
3. Para cada pessoa que administra pela conta compartilhada, decidir o perfil
   mínimo de que ela precisa (administrador, técnico da TI, ou nenhum).
4. Criar as contas nominativas por `POST /usuarios/`, por um administrador
   humano, com `conta_de_servico: false` — fica evento de criação com o ator.
5. Entregar a senha inicial fora de banda e exigir a troca
   (`/auth/alterar-senha`) no primeiro acesso.
6. Confirmar **pelo menos dois** administradores humanos ativos (a trava do
   último administrador só garante um).
7. Homologar a API-11 com essas contas (memória "Homologação local").
8. Subir a API-11 e conferir que a conta compartilhada recebe 403 na
   administração e continua lendo.
9. Ajustar o FortiPAM: retirar a conta compartilhada do uso administrativo e
   entregar a cada pessoa a conta dela.
10. Decidir o destino da conta compartilhada — rebaixar, manter só leitura ou
    desativar — **por um administrador humano, à mão**; nada é automático.
11. Conferir a trilha (`GET /usuarios/{id}/eventos`) das contas alteradas.
12. Revisar o inventário periodicamente (sugestão: trimestral) e a cada conta
    de serviço nova.

## Riscos residuais

- **A leitura continua.** O administrador de serviço lê todos os chamados; o
  técnico de serviço, os do alcance do perfil. É o que o painel precisa, e
  ficou de propósito.
- **`GET /usuarios/` continua aberto a toda conta autenticada** (fora do
  escopo da API-11).
- **Sem trilha geral de `PUT` de chamado nem de exclusão definitiva**: o `PUT`
  só grava histórico de mudança de status, e o `DELETE` de chamado não deixa
  evento. Fora do escopo (S6).
- **SQL direto** (n8n, DBeaver, recuperação) passa por fora de toda a regra e
  não grava evento.
- **O lembrete do dia some na TV** até haver decisão sobre a identidade dela
  e um FE que use a rota nova.
- **Banco sem administrador humano** fica sem administração pela API até a
  recuperação manual.

## Rollback

Voltar a imagem da API-10. Nada no banco a desfazer (sem migration). **Reabre
R1, R2 e S4:** o administrador de serviço volta a administrar tudo (inclusive
resetar senha alheia e excluir chamado sem evento), o técnico de serviço volta
a alterar chamados como equipe, a conta compartilhada volta a contar como
último administrador, `/auth/registro` volta a ignorar `conta_de_servico`
calado, e a rota `lembretes-do-dia` sai (o FE-5 não a usa, então nada quebra
na tela).
