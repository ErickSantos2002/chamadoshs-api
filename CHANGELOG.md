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
- **`GET /api/v1/health`**, público e barato o bastante para ser chamado a cada
  60s, para a faixa de status do frontend e para monitoramento externo.

  - **200** — `{"status": "ok", "banco": "ok", "hora": "<ISO-8601 com fuso>"}`
  - **503** — `{"status": "degradado", "banco": "erro"}`

  Verifica o banco com um `SELECT 1` e nada além disso. Não reaproveita
  `/api/v1/diagnostico/`, que conta usuários, consulta `information_schema` e
  monta amostra: aquilo é relatório administrativo, restrito a administrador e
  caro por resposta — os dois existem separados de propósito.

  **503 e não 200 com `status: degradado`**, porque o front precisa distinguir
  "API caiu" (sem resposta) de "API no ar, banco fora" (503 com corpo). Um 200
  carregando a palavra "degradado" faria todo monitoramento que olha só o código
  de status — incluindo o do Easypanel — enxergar saúde onde não há.

  **É o segundo endpoint público da API** (o outro é o login), e a resposta é um
  contrato fechado de três campos por causa disso: sem versão, sem nome ou host
  de banco, sem contagem de registros, sem nada do ambiente. Endpoint de saúde é
  alvo clássico de reconhecimento, justamente por responder sem credencial. A
  mensagem da exceção também não entra no corpo — um `OperationalError` do
  psycopg2 traz host, porta, usuário e nome do banco no texto, e isso vai para o
  log, onde o acesso já é controlado.

  A abertura exigiu registrar a rota em `main.ROTAS_PUBLICAS`, senão a trava de
  proteção derruba a aplicação na inicialização. Há teste conferindo que a
  exceção é só essa e que nenhuma outra rota ficou aberta.

  13 testes em `tests/test_health.py`, incluindo o caminho de banco fora e a
  lista do que o corpo não pode conter.

- **`HEALTHCHECK` do contêiner corrigido.** O comando fazia
  `requests.get(...)` sem checar o resultado, e `requests` só levanta exceção
  por falha de conexão: qualquer resposta HTTP contava como saudável, inclusive
  500 e 503. Na prática o healthcheck só falharia com a porta fechada. Agora usa
  `raise_for_status()` e `timeout=5`. O `docker-compose.yml`, que não tinha
  healthcheck no serviço da API, ganhou o mesmo.

  Ele aponta para `/health` (sem banco), e **não** para `/api/v1/health`. É o
  que decide reinício de contêiner, e banco fora não se conserta reiniciando a
  API: apontá-lo para a verificação com banco colocaria a API em ciclo de
  restart durante uma queda do Postgres, destruindo a resposta "API no ar, banco
  fora" exatamente quando ela é a informação útil. A saúde das dependências é
  monitorada de fora. Tabela dos dois caminhos em `DEPLOY.md`.
- **`PATCH /usuarios/{id}/desativar` e `/reativar`**, e os equivalentes em
  **`/setores/{id}`**. Passam a dizer no verbo o que o corpo sempre fez: o
  `DELETE` desses dois cadastros nunca apagou nada — desativava.

  **O `DELETE` continua existindo e delega para o mesmo corpo**, então o
  frontend não quebra e as duas rotas não têm como divergir. A única diferença
  entre elas é a `origem` gravada na trilha, e é ela que responde quando a
  migração do frontend terminou:

  ```sql
  SELECT origem, count(*) FROM eventos_de_conta
  WHERE acao = 'desativacao' GROUP BY origem;
  ```

  Compartilhar o corpo não é economia de linhas: foi a duplicação entre
  `DELETE` e `PUT` que deixou, até 11/08/2026, um `PUT {"ativo": false}`
  derrubar o último administrador pela porta que o `DELETE` trancava.

  Os `PATCH` devolvem o registro atualizado (200), e não 204, para a tela
  atualizar a linha sem uma segunda requisição. Desativar quem já está inativo
  responde sucesso e **não** gera evento — o estado pedido é o estado final, e
  a trilha registra mudança, não requisição.

- **Trilha de auditoria do cadastro de setores** (`eventos_de_setor`), irmã da
  de contas. Migration em `migrations/2026-08-12-add-eventos-de-setor.sql`.

  Tabela separada, e não uma coluna a mais na de contas, por causa do **futuro
  do alvo**. Em `eventos_de_conta` o alvo é FK sem `ON DELETE`, o que faz o
  banco recusar apagar uma conta que aparece na trilha — ali isso é o ponto.
  Para setor seria uma armadilha: o passo seguinte torna setor apagável de
  verdade, e a mesma FK faria um setor renomeado uma vez **nunca mais poder ser
  excluído**. O evento sobreviveria ao setor só para impedi-lo de morrer.

  O que substitui a FK é o par **`setor_id` (sem FK) + `setor_nome` congelado**
  no momento do evento: o id liga os eventos do mesmo setor entre si mesmo
  depois de a linha sumir, e o nome diz que setor era aquele sem depender de uma
  consulta que devolveria o presente — ou nada. O `ator_id` mantém a FK, porque
  quem se apaga aqui é o setor, não a conta.

  Grava em todos os caminhos: `POST`, `PUT`, os dois `PATCH` e o `DELETE`.

- **Leitura da trilha pela aplicação**, que até aqui só saía por SQL no banco:
  - **`GET /usuarios/{id}/eventos`** (admin) — o que aconteceu com UMA conta,
    para o painel de histórico do modal de usuário. Escopado pelo alvo: o que
    a conta fez com outras não entra. 404 para conta inexistente, porque lista
    vazia se leria como "esta conta nunca foi tocada".
  - **`GET /eventos`** (admin) — a tela de auditoria, com filtros `alvo`,
    `ator_id`, `de`, `ate` e paginação. Junta os dois cadastros num formato só:
    a pergunta é "quem fez o quê, com o quê, e quando", e ela não muda conforme
    a tabela. `alvo_tipo` diz de onde a linha veio e `chave` é única na trilha
    inteira — os ids das duas tabelas colidem entre si.

  O período é **em dias, com os dois extremos incluídos**: `ate=2026-08-12`
  cobre o dia 12 até o fim, não até a meia-noite dele — que devolveria lista
  vazia justamente para quem filtra o dia corrente.

  Router próprio (`/api/v1/eventos`) em vez de rota sob `/usuarios`: a listagem
  cobre os dois cadastros, e `/usuarios/eventos` dependeria da ordem de
  declaração para não ser engolida por `/usuarios/{usuario_id}`.

- **Trava: desativar setor com usuários ativos vinculados devolve 400.** Setor
  inativo some do seletor do formulário mas não solta quem aponta para ele; as
  contas ficam presas a um setor que a tela não oferece mais, e o estrago
  aparece longe da causa — na hora de editar uma dessas pessoas. Vale nos três
  caminhos (`PATCH`, `PUT` e `DELETE`) desde já, em vez de repetir a lição do
  `PUT` de usuários.

  A contagem é de usuários **ativos**. Setor extinto anos atrás ainda tem
  ex-funcionários apontando para ele, e esses vínculos são o histórico que não
  se apaga — contá-los tornaria todo setor antigo indesativável.

- 66 testes em `tests/test_patch_desativar_reativar.py`,
  `tests/test_eventos_de_setor.py`, `tests/test_consulta_da_trilha.py` e
  `tests/test_vinculos_do_cadastro.py`.

- **Trilha de auditoria do cadastro de usuários** (`eventos_de_conta`), que
  responde "**quem** fez **o quê** com **qual conta**, e **quando**" — pergunta
  de ISO 27001 que o sistema não respondia. Migration em
  `migrations/2026-08-12-add-eventos-de-conta.sql`.

  Não havia de onde tirar essa resposta. `historico_chamados` é escopado por
  chamado (`chamado_id NOT NULL` + `ON DELETE CASCADE`), então evento de usuário
  não cabe lá e o que coubesse sumiria junto com o chamado;
  `usuarios.updated_at` é sobrescrito por qualquer edição e não guarda autor.

  Formato, e o motivo de cada escolha:

  - **Ator e alvo em colunas separadas** (`ator_id`, `usuario_id`). "A conta X
    foi desativada" sem dizer por quem não é evidência.
  - **Nenhuma das duas FKs tem `ON DELETE`** — no PostgreSQL, `NO ACTION`.
    Apagar uma conta que aparece na trilha passa a ser recusado pelo banco. Com
    `CASCADE`, a trilha morreria junto com a conta, isto é, exatamente no caso
    em que ela é procurada.
  - **Uma linha por mudança, com `valor_anterior` e `valor_novo`** em texto
    legível. Registrar só "perfil alterado" tornaria impossível reconstruir o
    de/para depois da segunda alteração. Perfil e setor guardam o **nome**, não
    o id: o nome congela o que o valor significava naquele momento, enquanto o
    id depende de uma consulta que devolve o presente.
  - **Senha e hash nunca entram nos valores.** A alteração de senha é evento
    sem valores; há teste procurando a senha e os dois hashes na trilha inteira.
  - `origem` guarda a rota que gravou, como template. Enquanto o `DELETE` e os
    `PATCH` de desativar/reativar conviverem, é por ela que se mede o que o
    frontend ainda usa (`GROUP BY origem`).

  **Como ler um evento de senha:** quem classifica é a `origem`, não o
  `ator_id`. `POST /auth/alterar-senha` exige a senha atual ("trocou sabendo a
  antiga"); `PUT /usuarios/{id}` com `senha` não ("sobrescreveu usando poder de
  administrador"). Ator igual ao alvo **não** identifica a primeira: o botão de
  resetar senha da aba de Usuários aparece também na linha do próprio
  administrador, e esse reset chega pelo `PUT` com ator e alvo iguais.

  **Grava em todos os caminhos que alteram cadastro, não só nos novos**: `PUT` e
  `DELETE /usuarios/{id}`, `POST /usuarios/`, `POST /auth/registro` e
  `POST /auth/alterar-senha`. O `PUT` é por onde o frontend edita usuário hoje e
  também muda `ativo` e `role_id` — gravar só nas rotas novas faria a trilha
  nascer cega justamente para o uso real, e trilha incompleta é pior que
  trilha nenhuma, porque é lida como se fosse completa.

  A trilha registra **mudança, não requisição**: campo reenviado com o mesmo
  valor não gera evento (o modal de usuário envia o cadastro inteiro em toda
  gravação), e requisição recusada pelas travas de administrador não deixa
  rastro — o evento e a mudança são gravados na mesma transação, então não
  existe conta alterada sem evento nem evento de algo que não aconteceu.

  A leitura pela aplicação entrou junto, nesta mesma versão: `GET
  /usuarios/{id}/eventos` e `GET /eventos` (ver acima). Os dois foram escritos
  depois da gravação, de propósito — a tabela precisava existir e estar sendo
  preenchida antes de valer a pena consultá-la.

  22 testes em `tests/test_eventos_de_conta.py`, cobrindo cada caminho de
  gravação, o de/para encadeado, a ausência de senha e a ausência de `ON
  DELETE` nas FKs.

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
- **`POST` e `PUT /usuarios/` devolvem 400, e não 500, para `role_id` ou
  `setor_id` inexistente.** O valor inválido seguia até o banco e voltava como
  erro de FK, que o FastAPI entrega como 500: a resposta afirmava defeito do
  servidor sobre dado inválido do cliente, e a tela mostrava erro genérico em
  vez de dizer o que houve. As travas de administrador do mesmo formulário já
  respondiam 400 — as duas recusas saíam em códigos diferentes.

  A validação roda **antes** das travas, para a mensagem descrever o que
  aconteceu: um `role_id` inexistente também não é administrador, então a trava
  de rebaixamento barraria a requisição sozinha, falando de rebaixamento a
  partir de um id que não resolve para perfil nenhum.

  `setor_id: null` continua passando: é como se tira alguém de um setor. Setor
  **inativo** também — a validação é sobre existir, não sobre estar ativo, e
  barrá-lo aqui quebraria a edição de quem já está vinculado a um deles, já que
  o modal reenvia o cadastro inteiro em toda gravação.
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
- ~~**Migration `migrations/2026-08-12-add-eventos-de-conta.sql`**~~ — **JÁ
  APLICADA em 12/08/2026**, à mão pelo DBeaver. Não precisa rodar de novo (e
  rodar não faria mal: é `CREATE TABLE IF NOT EXISTS`).

  **A tabela está vazia em produção, e isso é o esperado.** Ela foi criada antes
  do código que escreve nela, que é o do passo 2 e ainda não subiu. Zero linhas
  significa "a imagem nova ainda não foi para o ar", não defeito — foi
  exatamente esta a dúvida que custou uma investigação em 12/08. A trilha começa
  a encher no deploy da imagem, e o que aconteceu antes não é recuperável,
  porque não existe fonte de onde reconstruir.

  Aplicar adiantado era seguro por construção, e continua sendo: tabela vazia
  que ninguém lê não muda o comportamento da API que está no ar, e rollback da
  imagem depois também não.
- **Migration `migrations/2026-08-12-add-eventos-de-setor.sql`**: aplicar
  **antes** de subir a imagem, pelos mesmos motivos da de cima — todo
  `POST`/`PUT`/`PATCH`/`DELETE` de setor passa a gravar nela, e com o banco
  antigo o código novo derruba a edição de setor inteira. `CREATE TABLE` puro,
  idempotente, sem nada a configurar no Easypanel.

- **ORDEM DO DEPLOY: uma migration pendente, não duas.**

  1. `migrations/2026-08-12-add-eventos-de-setor.sql` — a única que falta
  2. subir a imagem
  3. apontar o healthcheck do Easypanel para `/health`

  A de `eventos_de_conta` já foi aplicada em 12/08 (ver acima). Subir a imagem
  sem a de setor quebra a edição de setor na primeira gravação; o arquivo termina
  com as consultas de verificação.

- **Depois do deploy, para liberar os passos 3 e 4:**
  `docs/medir-migracao-do-frontend.sql`. São cinco `SELECT`s que respondem, pela
  coluna `origem` das trilhas, se o frontend ainda chama os `DELETE` antigos —
  a pergunta que decide se aqueles passos podem acontecer sem quebrar cliente.
  A resposta precisa ser medida, não lembrada: são três abas do front, e basta
  uma ter passado despercebida.

  Não rodar logo depois do deploy esperando conclusão: a trilha registra do
  deploy em diante, então vazio ali significa "ainda não sei", e não "migrou".
  A quinta consulta serve para separar os dois casos.

- **Nenhuma rota mudou de comportamento nesta versão**, então o frontend atual
  continua funcionando sem ajuste: `DELETE` de usuário e de setor respondem
  como sempre responderam. As rotas novas (`PATCH .../desativar`,
  `PATCH .../reativar`, `GET /eventos`) ficam disponíveis para o frontend
  adotar quando for conveniente — e é essa adoção que o passo seguinte espera.

  **O que vem depois, e por que ainda não veio:** o `DELETE` de setor passará a
  apagar de verdade, e o de usuário sairá de cena. Esse é o único passo que
  quebra cliente, e só acontece depois que o frontend migrar para os `PATCH`.
  A consulta de `origem` acima é o que diz quando isso é seguro.
- **`GET /api/v1/health`: API ANTES DO FRONTEND 1.4.1.** Não é urgente, mas tem
  ordem. A faixa de status da 1.4.1 consome este endpoint; com a API antiga em
  produção, ela recebe 404 e **nasce dizendo "fora do ar" com o sistema no ar** —
  o oposto exato do que ela existe para fazer, e pior do que não ter faixa.

  Rota nova, sem migration, sem nada a configurar: pode subir junto com a
  fundação visual, desde que a API vá primeiro. A ordem inversa é segura em
  outro sentido — API nova com frontend antigo não incomoda ninguém, porque
  quem não chama o endpoint não percebe que ele existe.

- **Healthcheck do Easypanel: apontar para `/health`**, o caminho **sem** banco,
  e não para o `/api/v1/health` novo. Se o Easypanel reinicia o serviço quando o
  healthcheck falha, essa é a única opção segura — banco fora não se conserta
  reiniciando a API, e a queda do Postgres viraria ciclo de restart. Se ele
  apenas alerta, o que se perde é detalhe que a faixa de status do frontend
  mostra de qualquer forma. Nas duas hipóteses `/health` é a escolha certa.
  Tabela dos dois caminhos em `DEPLOY.md`.

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
