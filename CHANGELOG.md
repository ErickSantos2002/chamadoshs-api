# Changelog

Registro das mudanças relevantes da ChamadosHS API.

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
O sistema atende **ISO 27001**, então este arquivo também serve de evidência
de auditoria: mudanças de segurança e de rastreabilidade são registradas com
o que exigiu ação no deploy.

O deploy é manual, pelo Easypanel. A seção **Ação necessária no deploy** de
cada versão lista o que precisa ser feito além de subir a imagem.

## [Não publicado]

### Adicionado
- **`usuarios.conta_de_servico`** (`BOOLEAN NOT NULL DEFAULT false`), exposto em
  `UsuarioResponse` e aceito em `UsuarioCreate` e `UsuarioUpdate`. Marca contas
  que não representam pessoas — painel de parede, integração, login
  compartilhado. Elas precisam autenticar, então desativar não servia:
  `get_current_user` recusa usuário inativo. O campo descreve o que a conta é,
  não uma permissão derivada, para servir a outros usos além do seletor de
  técnico. Migration em `migrations/2026-08-10-add-conta-de-servico.sql`.
- `PUT /api/v1/chamados/{id}` recusa com **400** atribuir um chamado a uma conta
  de serviço, e devolve 400 em vez de 500 quando o técnico informado não existe.
  A validação só roda quando `tecnico_responsavel_id` vem na requisição: olhar o
  técnico já gravado tornaria ineditável um chamado cuja pessoa atribuída
  virasse conta de serviço depois.
- **Tamanho mínimo dos campos de texto do chamado**, igualando a API ao que o
  frontend passou a exigir: `titulo` 10, `descricao` 20, `solucao` 10. Vale na
  criação (`POST`) e na edição (`PUT`). A contagem é sobre o texto aparado,
  senão a barra de espaço satisfaz o mínimo; o valor também é gravado sem os
  espaços das pontas.

  `solucao` guarda também o **motivo do cancelamento** — o `PATCH /cancelar`
  não tem corpo, então o motivo chega por `PUT {solucao}` e cai na mesma
  coluna. O mínimo vale para os dois, o que é o desejado: cancelar com "x" não
  passa por uma porta que resolver com "x" não passa.

  Exigir na edição **não trava chamado legado**, porque o que não vem na
  requisição não é validado (`exclude_unset`) e o frontend não reenvia valor
  intocado. Mexer no status de um chamado antigo de título curto continua
  funcionando; há teste para isso.

  O legado foi medido antes da regra entrar, em 11/08/2026: de **145 chamados**,
  ficariam abaixo do mínimo **26 títulos, 30 descrições e 37 soluções**. Nenhum
  deles fica travado — os 37 de solução curta seguem editáveis por qualquer
  outro campo. Os números também justificam a regra: solução com menos de 10
  caracteres é "ok" e "resolvido", ou seja, cerca de um em cada quatro chamados
  não registrou o que foi feito.

  A restrição fica em `ChamadoCreate`/`ChamadoUpdate`, e não em `ChamadoBase`,
  porque `ChamadoResponse` herda da base e o FastAPI valida a resposta contra
  ela: o mínimo na base faria todo chamado antigo de título curto — que
  existe, porque a API aceitou qualquer tamanho até aqui — virar
  `ResponseValidationError`, ou seja, **500 no GET e na listagem**. Há teste
  cobrindo isso.
- **Trava de divergência entre o `.sql` e os models**
  (`tests/test_schema_sql_bate_com_os_models.py`). Lê o `schema_chamados.sql` e
  compara tabelas e colunas com `Base.metadata`, nos dois sentidos. Coluna nova
  em `app/models/` sem a coluna no arquivo derruba a suíte. É o que impede o
  arquivo de envelhecer de novo: sem isso, a correção acima valeria até a
  próxima migration. Lê o SQL em vez de executá-lo porque o arquivo é
  PostgreSQL (SERIAL, plpgsql, índice parcial) e a suíte não depende de banco
  externo. Não compara tipo, `nullable` nem `default` — isso exigiria
  interpretar dialeto e passaria a falhar por diferença de escrita.
- Estrutura de testes com pytest, em `requirements-dev.txt` separado do de
  produção — o Dockerfile instala apenas o de produção, então nada de teste
  vai para a imagem publicada.
- 133 testes cobrindo o limitador de login, o motor de horas úteis, as regras
  de SLA, o cálculo de recorrência, o envio de webhook e o aviso de
  `usuario_id` depreciado. Nenhum depende de banco ou do relógio real: os
  instantes são passados por parâmetro, o que mantém o resultado estável mesmo
  com o container em UTC e o sistema operando em horário de Brasília.

### Alterado
- A URL do webhook do n8n saiu do código e virou `WEBHOOK_TECNICO_URL`. O
  padrão vazio desliga o envio, para desenvolvimento e testes não dispararem
  notificação no fluxo de produção por descuido.
- `print()` do serviço de webhook trocado por `logging`, sem nunca registrar
  a URL.
- **Aviso `param usuario_id depreciado` corrigido.** A condição exigia que o
  id recebido fosse diferente do id do token, e por isso o caso mais comum —
  a pessoa logada agindo em nome de si mesma — não gerava aviso nenhum. O log
  podia estar zerado com o frontend enviando o parâmetro em todas as chamadas.
  Agora o aviso dispara sempre que o parâmetro chega, nos seis pontos. O
  volume sobe enquanto o frontend não for atualizado: é o baseline esperado.

### Corrigido
- **O solicitante voltou a conseguir avaliar o atendimento.** Desde a 1.1.0 o
  widget de estrelas salvava por `PUT /api/v1/chamados/{id}`, que passou a
  exigir perfil de administrador ou técnico — o solicitante, única pessoa que
  deveria avaliar, levava 403. Corrigido com rota dedicada
  **`PATCH /api/v1/chamados/{id}/avaliar`**, corpo `{"avaliacao": 1..5}`,
  aberta a qualquer usuário autenticado e restrita ao próprio solicitante do
  chamado (403 para os demais, inclusive administrador e técnico), permitida
  só com o chamado `Resolvido` ou `Fechado` (409 caso contrário). A avaliação
  fica registrada no histórico do chamado.

  O `require_staff` do PUT **não** foi afrouxado, de propósito: por aquela rota
  o solicitante alteraria status, prioridade e técnico responsável do próprio
  chamado. A rota nova grava um campo só, e 17 testes cobrem tanto o caminho
  do solicitante quanto o escopo — que ela não virou porta lateral para o que
  o PUT protege.

  Sem migration: a coluna `chamados.avaliacao` já existe, com
  `CHECK (avaliacao >= 1 AND avaliacao <= 5)`, espelhado no schema Pydantic
  para nota fora da faixa dar 422 em vez de 500.

- **`schema_chamados.sql` voltou a descrever o banco.** O arquivo estava parado
  na 1.0 (`07e606c`) enquanto seis entregas mexiam no schema. Faltavam três
  tabelas (`sla_configs`, `tarefas_recorrentes`,
  `tarefas_recorrentes_execucoes`) e cinco colunas (`usuarios.senha_hash`,
  `usuarios.conta_de_servico`, `chamados.urgencia`, `chamados.cancelado`,
  `chamados.arquivado`). Rodá-lo criava um banco **sem `senha_hash`**, isto é,
  um banco em que ninguém autentica — e ele é justamente o arquivo que se abre
  numa recuperação de desastre ou ao montar homologação. Agora está completo,
  atual e idempotente, incluindo os 16 índices, os 3 triggers e o seed.

  **Muda o procedimento:** banco novo roda **só** `schema_chamados.sql` e
  **não** roda `migrations/`; banco existente roda **só** o que falta de
  `migrations/`. Misturar falha, porque parte das migrations não é idempotente
  (`add_auth_fields.sql` faz `ADD COLUMN` sem `IF NOT EXISTS`). DEPLOY.md e
  README atualizados.

### Segurança
- **`PUT /api/v1/usuarios/{id}` passou a respeitar as travas de desativação.**
  O `DELETE` recusava desativar a si mesmo e desativar o último administrador
  ativo; o `PUT` aceita `ativo` e não tinha nenhuma das duas, então
  `PUT {"ativo": false}` derrubava o administrador pela porta ao lado da que o
  `DELETE` trancava — e sem nenhum administrador não há recuperação pela
  aplicação, porque criar e editar usuário também exigem esse perfil. As travas
  ficam agora em `_garantir_desativacao_segura`, compartilhada pelas duas rotas:
  a duplicação era o que permitia divergirem.

  **Só valem quando `ativo` chega como `false`.** Reativar
  (`PUT {"ativo": true}`) é o único caminho de volta pela interface; travar
  qualquer mudança de `ativo` bloquearia a recuperação em vez do dano. Há teste
  para os dois lados em `tests/test_desativacao_de_usuario.py`.

  Alcance antes da correção: era preciso token de administrador e chamada
  direta à API — o frontend não tem campo `ativo` no cadastro e nunca envia
  `false`. Ou seja, o mesmo conjunto de pessoas que já podia desativar pelo
  caminho legítimo. Não houve exploração conhecida.
- **`PUT /api/v1/usuarios/{id}` recusa rebaixar o último administrador ativo.**
  Tirar o perfil de administrador deixa o sistema no mesmo estado que
  desativar a conta, mas a recuperação é pior: quem se rebaixa perde o acesso
  à tela de Cadastros, exclusiva de administrador, e some da própria condição
  de consertar — o desativado ao menos continua listado para outro
  administrador reativar. Sendo o último, ninguém conserta pela aplicação.

  Diferente da desativação, **este caminho era alcançável pela interface**: o
  modal de usuário envia o perfil em toda gravação, então trocar o próprio
  para "Usuario" e salvar eram três cliques, sem token nem chamada direta.

  A regra é sobre o último, e não sobre si mesmo: rebaixar a própria conta é
  legítimo quando há outro administrador ativo, e é o que se faz ao sair da
  equipe. Reenviar o mesmo perfil também passa — é o que o modal faz em toda
  gravação, e travar a presença do campo em vez da mudança de valor tornaria o
  último administrador ineditável.
- **Header de autenticação no webhook do n8n.** Até aqui a URL era a única
  credencial: quem conhecesse o endereço disparava o fluxo. O backend passa a
  enviar `WEBHOOK_TECNICO_TOKEN` no header `X-Webhook-Token`, para o nó
  Webhook validar via Header Auth. Token vazio não envia header, o que permite
  subir o backend antes de ligar a exigência no n8n. Nem a URL nem o token
  aparecem no log.
- **Credenciais em texto claro removidas do HEAD.** `criar_usuario_inicial.sql`
  e `AUTH.md` traziam usuário `admin` com senha e hash bcrypt embutidos, num
  repositório público. O script passa a receber o hash por variável do psql,
  sem valor padrão. As senhas seguem no histórico do Git e devem ser
  consideradas comprometidas.
- **`criar_usuario_inicial.sql` deixou de ser destrutivo.** Fazia
  `DELETE FROM usuarios WHERE nome = 'admin'` seguido de `INSERT` com hash
  fixo: rodado por engano em produção, redefiniria a senha do administrador
  para a que vazou. Trocado por `ON CONFLICT (nome) DO NOTHING`.
- A URL antiga do webhook permanece no histórico do Git e deve ser
  considerada comprometida. O identificador do fluxo embutido nela é o que
  autoriza a escrita no n8n, ou seja, funciona como credencial.

### Ação necessária no deploy
- Configurar `WEBHOOK_TECNICO_URL` no Easypanel. **Sem isso o webhook para
  de ser enviado**, já que o padrão é desligado.
- Gerar um webhook novo no n8n e aposentar o antigo, em vez de reaproveitar a
  URL que está no histórico.
- **`WEBHOOK_TECNICO_TOKEN`**: gerar com `openssl rand -hex 32` e configurar no
  Easypanel **antes** de mudar o nó Webhook do n8n para Header Auth. Na ordem
  inversa, o n8n recusa os envios e os técnicos deixam de ser notificados sem
  que nada falhe visivelmente — o sintoma aparece só no log, como `ERROR` com
  status 401/403.
- **Migration `migrations/2026-08-10-add-conta-de-servico.sql`**: aplicar
  **antes** de subir a imagem. O model já declara a coluna, então o código novo
  contra o banco antigo quebra qualquer leitura de usuário. Idempotente
  (`ADD COLUMN IF NOT EXISTS`); sem reversão automática — o rollback é o backup.
  Marcar as contas de serviço é um `UPDATE` separado, comentado no fim do
  arquivo, para ser rodado depois de conferir os nomes.
- **`PATCH /chamados/{id}/avaliar`**: subir a API **antes** de ligar o widget
  de estrelas no frontend. Rota nova, sem migration — a ordem inversa faria o
  front chamar um caminho que ainda devolve 404. Nada a configurar.
- **Tamanho mínimo dos textos: FRONTEND PRIMEIRO, API DEPOIS.** É o inverso da
  ordem usual deste projeto, e não é preferência.

  O frontend em produção trata `detail` como string em 26 lugares
  (`setError(err.response.data.detail)`). O 422 do FastAPI devolve `detail`
  como **lista de objetos**: o estado recebe um array, o React não renderiza
  objeto como filho e **a tela fica branca**. Não é a tela nova — é a que está
  no ar agora. Subindo a API primeiro, o primeiro título curto que alguém
  digitar derruba a tela dessa pessoa.

  A correção está no interceptor do `api.ts` do frontend, que normaliza
  `detail` para string em um ponto só. Ela precisa estar em produção **antes**
  de esta versão da API subir. Rodar o frontend novo contra a API antiga é
  seguro: sem validação de tamanho, o 422 simplesmente não acontece.

## [1.1.0] — 2026-08-07

Correção da exposição pública da API. Antes desta versão, 43 dos 46 endpoints
respondiam sem token: era possível listar e alterar chamados e usuários, e
trocar a senha de qualquer conta — inclusive a de administrador — sem
credencial nenhuma.

Verificado em produção após o deploy: todas as rotas `/api/v1` respondem 401
sem token.

### Segurança

- **Autenticação em toda a API.** A dependency passou a ser aplicada no
  `include_router`, e não endpoint a endpoint, para a política caber numa
  tela e endpoint novo nascer protegido. `POST /api/v1/auth/login` é a única
  rota pública sob `/api/v1`; `/` e `/health` seguem abertas para o
  healthcheck do Docker e do Easypanel.
- **Tomada de conta fechada.** `PUT /api/v1/usuarios/{id}` aceitava `senha` e
  `role_id` sem autenticação: uma requisição anônima trocava a senha de
  qualquer usuário. Passou a exigir administrador.
- **Escalada de privilégio fechada.** `POST /api/v1/auth/registro` era
  público e aceitava `role_id`, permitindo criar uma conta Administrador sem
  credencial. Passou a exigir administrador.
- **Vazamento de usuários fechado.** `/api/v1/diagnostico` era público e
  listava nomes de usuário, `role_id` e quais contas estavam sem senha —
  combinado com o `PUT` acima, era uma lista de alvos pronta. Passou a exigir
  administrador.
- **Trilha de auditoria não forjável.** Quatro endpoints de chamados recebiam
  o autor da ação como query parameter, e comentários e execução de tarefa
  recorrente recebiam `usuario_id` no corpo. O histórico registrava quem o
  chamador dissesse ser. O autor passou a vir sempre do token. `POST
  /chamados/` também deixou de aceitar `solicitante_id` do corpo, salvo para
  administrador abrindo em nome de outro.
- **Força bruta contida.** `POST /auth/login` aceitava tentativas ilimitadas.
  Passou a ter dois limitadores de tentativas falhas em janela deslizante: 10
  por usuário e 50 por IP, em 15 minutos, com resposta 429 e `Retry-After`.
  O limite por IP é folgado de propósito, porque um escritório atrás de um
  único IP público compartilha a contagem.
- **Autorização por perfil.** 14 operações restritas a administrador e 6 a
  administrador ou técnico. Exigir token responde "quem é você"; sem isto,
  qualquer usuário logado ainda poderia apagar chamados e promover a si
  mesmo.
- **Comentários internos protegidos.** A marcação `is_interno` existia mas
  não era aplicada em lugar nenhum: comentário interno era devolvido para
  qualquer um. Passou a ser visível e criável só por administrador e técnico.
- **Documentação fechada em produção.** `/docs`, `/redoc` e `/openapi.json`
  só existem quando `ENVIRONMENT=development`. O padrão de `ENVIRONMENT`
  passou a ser `production`, para que esquecer a variável no painel seja o
  caso seguro.

### Adicionado

- `require_roles()`, com os atalhos `require_admin` e `require_staff`, e os
  predicados `is_admin`/`is_staff`. O perfil é lido do banco e não da claim
  do JWT: a claim fica congelada até o token expirar, então rebaixar alguém
  só surtiria efeito na renovação.
- **Trava de inicialização** que percorre as rotas registradas e levanta
  `RuntimeError` se alguma rota `/api/v1` não exigir autenticação. Um
  endpoint novo desprotegido passa a impedir a aplicação de subir, em vez de
  virar um buraco silencioso. Rotas públicas de propósito ficam declaradas em
  `ROTAS_PUBLICAS`.
- As 11 skills `hsapi-*` versionadas, como tooling do projeto.

### Corrigido

- `HTTPBearer` passou a `auto_error=False`. No padrão, header `Authorization`
  ausente produz **403**, não 401 — e o frontend só trata 401. Sem essa
  correção, trancar os endpoints deixaria as telas quebradas em silêncio, sem
  redirecionar para o login.
- Sessão ampliada de 30 minutos para 8 horas. Trinta minutos passava
  despercebido enquanto quase nada validava o token; com a API inteira
  exigindo token, desconectaria o usuário no meio do expediente.
- `docker-compose.yml` alinhado com o padrão da aplicação, que divergia.
- `AUTH.md` afirmava "Todas as outras rotas da API requerem autenticação"
  enquanto 43 endpoints respondiam sem token, e trazia uma receita de `curl`
  que criava um administrador sem credencial. Ambos corrigidos.

### Removido

- `get_current_active_user`, que nunca era referenciado e era redundante com
  a checagem que o `get_current_user` já fazia.

### Depreciado

- Os campos `usuario_id` em chamados, comentários e execução de tarefa
  recorrente. Continuam sendo aceitos e **ignorados**, com `logger.warning` a
  cada uso, apenas para o frontend não quebrar na janela entre os deploys dos
  dois repositórios. A remoção depende de o aviso zerar nos logs — ver a
  correção do aviso em [Não publicado], sem a qual essa contagem não valia
  como sinal.

### Ação necessária no deploy

- **`ENVIRONMENT`**: não pode ficar como `development` em produção, senão
  `/docs` e `/openapi.json` continuam expostos.
- **`ACCESS_TOKEN_EXPIRE_MINUTES`**: se estiver fixado em `30` no painel, a
  variável de ambiente vence o novo padrão e os usuários continuam caindo a
  cada 30 minutos — agora com a autenticação realmente ativa.
- **`PROXY_HOPS_CONFIAVEIS`**: `1` para Easypanel/Traefik, que é o padrão.
  Usar `0` só se a aplicação receber conexão direta.
- Acompanhar nos logs o aviso `param usuario_id depreciado`, cuja contagem
  precisa zerar antes de o campo ser removido.

## [1.0.0] — 2026-07-16

Estado do sistema antes do trabalho de segurança. Reconstruído a partir do
histórico do Git; não havia changelog até aqui.

### Adicionado
- Tarefas recorrentes: tabelas, models, schemas, endpoints e cálculo da
  próxima data, com exclusão em cascata do histórico.
- SLA de atendimento, com paginação de chamados.
- Autenticação JWT com `login`, `registro`, `me`, `alterar-senha` e `refresh`
  — aplicada, à época, apenas a três endpoints.
- CRUD de chamados, usuários, comentários, histórico, setores e categorias.

### Corrigido
- Teto no `limit` da listagem de chamados.
- Exclusão de categoria vinculada a chamados.
