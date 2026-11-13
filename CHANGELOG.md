# Changelog

Registro das mudanças relevantes da ChamadosHS API.

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
O sistema atende **ISO 27001**, então este arquivo também serve de evidência
de auditoria: mudanças de segurança e de rastreabilidade são registradas com
o que exigiu ação no deploy.

O deploy é manual, pelo Easypanel. A seção **Ação necessária no deploy** de
cada versão lista o que precisa ser feito além de subir a imagem.

## [Não publicado]

### Adicionado — notificação da Qualidade por fluxo próprio (API-15)
- **Os técnicos da Qualidade passam a poder ser avisados por WhatsApp**, por
  um webhook separado do da TI (`WEBHOOK_QUALIDADE_URL`,
  `WEBHOOK_QUALIDADE_TOKEN`, `WEBHOOK_QUALIDADE_HEADER`). **Desligado por
  padrão**: sem a URL nada é enviado, e a API se comporta como a API-14.
- **Chamado aberto sem responsável** gera `chamado_aberto` para os técnicos
  elegíveis da Qualidade — a lista de `GET /chamados/atendentes-qualidade` —,
  menos quem abriu. Aberto já com responsável (o corpo do cliente antigo),
  gera `responsavel_atribuido` só para ele.
- **Atribuição e redistribuição** geram `responsavel_atribuido` só para o
  novo responsável, e só quando outra pessoa fez a troca: **assumir não
  avisa ninguém**. Status, comentário, cancelamento e arquivamento não
  avisam.
- **O corpo leva só ids e o protocolo.** Sem título, descrição, nome,
  solicitante ou telefone: os contatos ficam no n8n, por id de usuário. Cada
  evento tem um `id_evento` estável (`<chamado>:<versão>:<evento>`), que o
  fluxo usa para não avisar duas vezes.
- **Depois do commit, fora da requisição e sem repetição.** Falha, timeout
  ou resposta inválida do n8n não desfazem a abertura nem a atribuição e não
  atrasam a resposta; a falha vai para o log com o `id_evento`, sem URL nem
  token. Não repetir é proposital: um POST recebido cuja resposta se perdeu,
  repetido, viraria mensagem duplicada. Não há garantia de entrega
  exatamente uma vez — ver `docs/notificacao-qualidade.md`.
- **Com a URL, o token é obrigatório**: URL configurada sem token não envia
  e registra erro. (O token do webhook da TI segue opcional.)
- **A TI não muda**: mesmo webhook, mesmo corpo, mesmos momentos. O fluxo da
  Qualidade nunca usa a URL nem o token da TI, e chamado da TI nunca gera
  evento da Qualidade.
- Sem migration e sem mudança no frontend.

#### Ação necessária no deploy
- Nenhuma para subir: com as variáveis vazias nada muda.
- Para ligar: publicar o fluxo `[CHAMADOSHS] Notificação Qualidade` no n8n
  (com Header Auth e as tabelas de contatos e de envios), preencher
  `WEBHOOK_QUALIDADE_URL` e `WEBHOOK_QUALIDADE_TOKEN` no painel e reiniciar a
  API. Para desligar: esvaziar a URL e reiniciar.

#### Testes
- `tests/test_notificacao_qualidade.py`: abertura com e sem responsável,
  assumir, atribuição manual, redistribuição, autor fora dos destinatários,
  nenhum técnico elegível, URL vazia, token ausente, falha/timeout/resposta
  inválida do n8n, um envio por escrita e regressão do webhook da TI.

### Mudado — distribuição interna dos chamados da Qualidade (API-14)
- **O chamado da Qualidade nasce sem responsável.** Quem abre não escolhe
  mais quem atende: `tecnico_responsavel_id` passou a ser opcional em
  `ChamadoCreateQualidade`, e sem ele — ou com `null` — o chamado é gravado
  aguardando atribuição. Não há estado novo: "aguardando atribuição" é a
  ausência de responsável, que a coluna sempre aceitou. O histórico da
  abertura registra `Setor de destino: Qualidade | Aguardando atribuição`.
- **Compatível com o front 1.8.1.** O responsável enviado na abertura
  continua aceito e validado pela mesma regra (400 para inelegível ou
  inexistente): a API-14 pode subir antes do front novo, e segue servindo o
  antigo num rollback do front.
- **Sem técnico elegível, a abertura sem responsável é recusada**: 409
  `Não há técnico da Qualidade disponível para receber chamados no momento`.
  Nenhuma conta da equipe veria o chamado. A Qualidade não configurada segue
  503.
- **A equipe distribui pelo `PUT`.** O Técnico da Qualidade e o administrador
  humano atribuem e redistribuem, só para conta elegível
  (`qualidade_service.eh_elegivel`, sem mudança). As permissões são as que o
  `PUT` já tinha: usuário comum 403, técnico da TI 404, conta de serviço 403.
- **Atribuição e redistribuição ficam no histórico.** Ação
  `Atribuição de responsável`, com o autor do token e a descrição
  `Responsável definido: <novo> (antes: aguardando atribuição)` ou
  `Responsável alterado de <anterior> para <novo>`, no mesmo commit da troca
  (linha travada). Até aqui o `PUT` não registrava troca de responsável em
  nenhum setor; **na TI continua sem registrar**. A entrada não tem status, e
  o cálculo de SLA, que lê o histórico pelos status, não a enxerga.
- **Sem responsável o atendimento não começa.** Em chamado da Qualidade sem
  responsável, mudar o status é 409 `Chamado aguardando atribuição: defina o
  responsável antes de iniciar o atendimento`, igual no `PUT` da equipe e no
  `PATCH /chamados/{id}/atendimento` (que antes respondia 403 "Só o
  responsável atual"), depois da conferência de versão. Vale para o
  administrador. Atribuir e mudar o status na mesma requisição é aceito;
  prioridade e observações seguem editáveis; o cancelamento pelo solicitante
  não muda.
- **O atribuído não volta à fila.** Desatribuir chamado da Qualidade segue
  400 `Chamado da Qualidade precisa de responsável`.
- **Atendimento compartilhado preservado:** depois de atribuído, qualquer
  Técnico da Qualidade atende pelo `PUT`, e a rota `/atendimento` segue só do
  responsável atual. **Isolamento TI × Qualidade preservado:** nenhuma regra
  de leitura ou de equipe mudou. **TI inalterada:** abertura, atribuição,
  desatribuição, webhook e atendimento sem responsável como antes.
- Concorrência: a trava de linha e a `versao_esperada` obrigatória da
  Qualidade valem para a atribuição como já valiam; de duas atribuições com a
  mesma versão, uma grava e a outra recebe 409.
- Sem migration, sem variável nova, sem notificação nova.
- Testes: `tests/test_distribuicao_qualidade.py` (novo) e a classe
  `TestT4bDistribuicaoDoChamadoSemResponsavel` em
  `tests/test_concorrencia_versao_postgres.py`. Mudaram de expectativa, por
  serem a regra antiga: `test_sem_responsavel_e_422` e
  `test_responsavel_nulo_e_422` (saem; a abertura sem responsável agora é
  aceita), `test_nao_registra_historico_de_reatribuicao` (passa a registrar) e
  três conferências de histórico que contavam zero entradas na reatribuição.

#### Ação necessária no deploy
- **Antes** do front que tira o campo "Responsável" da abertura: o front novo
  contra a API-13 recebe 422 ao abrir para a Qualidade. A ordem inversa é
  segura.
- Nenhuma migration e nenhuma variável. Chamados existentes não mudam.
- Rollback da imagem: os chamados já abertos sem responsável continuam
  legíveis e editáveis na API-13, e podem ser atribuídos por ela; ela só não
  impede o atendimento antes da atribuição, e volta a exigir responsável na
  abertura (o front novo passaria a receber 422).

### Segurança — cada equipe no seu setor de destino (API-13)
- **O técnico da TI deixa de ler e de alterar os chamados da Qualidade.**
  Até a API-12, pela decisão D1, o perfil Técnico num setor de
  `SETORES_TI_IDS` lia os dois setores de destino e, pelo mesmo alcance,
  editava, arquivava, cancelava e via o interno dos chamados da Qualidade.
  Agora o alcance dele é só a TI, como o do técnico da Qualidade já era só a
  Qualidade (D2). Chamado da Qualidade que ele não lê responde o 404 de um id
  que não existe (D6); o que ele lê pelo vínculo — abriu, ou é o responsável
  — segue legível, e a escrita de equipe nele é 403 ("Este chamado não é da
  sua equipe"). O administrador humano segue com os dois setores.
- **Comentário interno é da equipe do setor do chamado.**
  `pode_acessar_comentario_interno` passou a receber o chamado e é a mesma
  regra de `pode_alterar_como_equipe`: administrador humano em todos, o
  técnico da TI nos da TI, o técnico da Qualidade nos da Qualidade — que até
  aqui não via interno nenhum (API-8). O vínculo não dá o interno, e conta de
  serviço continua sem ele. Vale para listar, buscar, criar, editar e
  excluir.
- **Abertura sem `setor_destino` fica registrada.** O front 1.8.0 manda o
  setor escolhido em toda abertura; a ausência, que só o front antigo produz,
  continua valendo TI — para não quebrar a abertura entre o deploy da API e o
  do front, nem num rollback do front — e agora deixa
  `criar_chamado sem setor_destino (cliente antigo): gravado como TI` no log.
  Valor inválido segue 422. Tornar o campo obrigatório é passo próprio, depois
  que o log zerar.
- **Responsável da Qualidade só pode ser Técnico da Qualidade.** Quem abre
  um chamado da Qualidade escolhe o responsável, e ele nasce atribuído; a
  elegibilidade (`qualidade_service.eh_elegivel`) passou a exigir o perfil
  Técnico, além de conta ativa, que não é de serviço, no setor de
  `SETOR_QUALIDADE_ID`. Até aqui valia qualquer perfil do setor: o usuário
  comum lotado na Qualidade era oferecido e aceito como responsável sem ser
  da equipe (não edita nem vê o interno), e o administrador do setor também.
  Vale na lista `GET /chamados/atendentes-qualidade`, na abertura e na
  reatribuição (400 `Atendente não é elegível para a Qualidade`) e na rota de
  atendimento (403 `Você não atende a Qualidade`).
- Sem migration, sem variável nova. `integra_equipe_ti`, `require_equipe_ti`,
  `/auth/me` e a regra de responsável da TI não mudam.

#### Ação necessária no deploy
- Junto com a API-12 (mesmas migrations), **antes** do front 1.8.0. Para
  publicar a Qualidade: `SETOR_QUALIDADE_ID` com o id do setor Qualidade, e as
  contas que atendem a Qualidade no setor dele, com perfil Técnico — sem
  isso elas não aparecem como responsáveis, e com nenhuma elegível a
  abertura para a Qualidade fica desabilitada no front ("Nenhum atendente da
  Qualidade cadastrado").

### Corrigido — concorrência da TI com versão (API-12)
- **Duas escritas da TI com a mesma versão não passam mais as duas.** Na
  API-11 o `PUT` da TI conferia `versao_esperada` sem travar a linha: duas
  requisições ao mesmo tempo conferiam a mesma versão antes de qualquer
  `UPDATE` e gravavam as duas (12 de 20 rodadas na homologação local do
  FE-5). Agora, quando a TI manda a versão, o `PUT` e as marcas
  (`cancelar`, `arquivar`, `desarquivar`) seguem o caminho da Qualidade:
  `SELECT ... FOR UPDATE`, conferência na linha travada, chamado e histórico
  num commit só, webhook depois do commit. Uma escrita vence; a outra
  recebe o 409 de sempre (`versao_desatualizada`, `versao_atual`), sem gravar
  campo, histórico nem webhook. 25 de 25 rodadas simultâneas em PostgreSQL
  com exatamente um 200.
- **Sem versão, a TI segue como antes** — versão opcional, sem trava, vale a
  última escrita. As ações rápidas, o resolver, o cancelar com motivo,
  arquivar, desarquivar e a troca de responsável no modal do FE-5 saem sem
  versão: **a concorrência nesses fluxos não está resolvida** e depende de o
  front passar a mandar a versão, sem mudança na API. A edição da página
  (FE-5, T-1) já manda e fica protegida.
- **Sem mudança** de contrato HTTP, de autorização, de SLA, na Qualidade
  (428/409/trava iguais, T1–T14 aprovados) ou no banco. Contrato, inventário
  das escritas, riscos e rollback: [docs/concorrencia-da-ti.md](docs/concorrencia-da-ti.md).
  Testes: `tests/test_concorrencia_ti_postgres.py` (40, PostgreSQL) e
  `tests/test_concorrencia_ti.py` (8, SQLite).

  **Ação no deploy:** nenhuma além da imagem. Sem migration nem variável;
  sem ordem com o front (o FE-5 funciona com a API-11 e com a API-12).
  Rollback: a imagem da API-11.

### Segurança — menor privilégio das contas de serviço (API-11)
- **Decisões S1–S6 (auditoria pós-API-10):** conta de serviço lê o que o
  perfil deixa e não age como equipe nem como administrador. A API-10 tirou
  a conta de serviço da equipe da TI, mas a auditoria seguinte achou o que
  ficava: a **conta compartilhada de administração** (citada na migration
  de `conta_de_servico`) mantinha todo o poder do perfil — resetar senha
  alheia, mudar perfil e `conta_de_servico`, excluir chamado de vez sem
  evento, e contava como "último administrador" (R1) —, e a **conta de
  serviço técnica** ainda fazia `PUT`, arquivava, desarquivava e cancelava
  chamado alheio pelo alcance do perfil, sem trilha além da de status (R2).
  Política inteira, inventário pendente e plano de migração:
  [docs/contas-de-servico.md](docs/contas-de-servico.md).

  **S2 — escrita de equipe.** `pode_alterar_como_equipe` recusa toda conta
  com `conta_de_servico` diferente de `False`, antes do perfil: `PUT`,
  arquivar, desarquivar, cancelar chamado alheio e reatribuir dão 403
  `"Conta de serviço não altera chamado como equipe"`, sem gravar nada — nem
  versão, nem histórico, nem webhook. O 404 de quem não lê vem antes, e o
  401/409/428 seguem. Continua: ler pelo alcance do perfil (o painel de
  parede), abrir o próprio chamado, comentar em público, avaliar o próprio
  e cancelar o que a conta abriu.

  **S3 — administração.** `require_admin` passa a exigir administrador
  humano (`is_admin_humano`: o perfil e `conta_de_servico = false`); a conta
  de serviço administradora recebe 403 `"Conta de serviço não executa
  administração"` em usuários (criar, editar, senha alheia, perfil, setor,
  `conta_de_servico`, desativar, reativar, eventos), `POST /auth/registro`,
  exclusão de chamado e de setor e diagnóstico. `require_equipe_ti` e o
  comentário interno também passam a exigir o humano, e abrir chamado em
  nome de outro e editar ou excluir comentário alheio idem. A **leitura não
  muda**: `is_admin` (só o perfil) segue valendo para ler todos os
  chamados. Nenhuma conta real foi alterada.

  **S4 — último administrador humano.** A trava do `PUT`, do `PATCH
  .../desativar` e do `DELETE` de usuário conta só quem é ativo,
  administrador e pessoa, e avalia o estado final com tudo o que o `PUT`
  muda junto (perfil, `ativo`, `conta_de_servico`): o último humano não é
  rebaixado, desativado nem convertido em conta de serviço, com a conta
  compartilhada ativa ou não. A contagem usa `SELECT ... FOR UPDATE`, então
  dois administradores removendo um ao outro ao mesmo tempo deixam um. Sem
  atalho para banco sem administrador humano: a recuperação é manual,
  documentada e não executada.

  **S5 — registro.** `POST /auth/registro` responde 422 a qualquer presença
  de `conta_de_servico` no corpo, inclusive `false`, e não cria a conta. O
  schema não tinha o campo e o descartava calado: `true` voltava 201 com uma
  conta humana. `POST /usuarios/` (que tem o campo) e
  `/auth/alterar-senha` não mudam.

  **S1 — lembrete do painel.** Nova rota
  `GET /tarefas-recorrentes/lembretes-do-dia`: só `id`, `titulo`,
  `proxima_data` e `situacao` (`atrasada`, `hoje`, `realizada_hoje`), o dia
  de Brasília em `data`, ordem por próxima data e id, só leitura, sem
  parâmetro. Lê quem já lia o módulo — administrador humano e técnico da
  TI — e a **conta do painel**: decisão aprovada, a lista por configuração
  **`PAINEL_CONTAS_IDS`** (ids de usuário separados por vírgula). A conta
  passa se for de serviço, ativa e com o id numa lista válida — as três
  lidas do banco pelo `sub` do token. Nome, perfil, setor, `conta_de_servico`
  sozinho, cabeçalho, query, IP, `User-Agent` e claim extra do token não
  contam; um id de pessoa na lista não lhe dá nada. **Vazia por padrão:
  ninguém.** Um item inválido (texto, zero, negativo, separador vazio, zero à
  esquerda, mais de dez dígitos, acima do teto do `INTEGER`) descarta a lista
  inteira, e a API sobe assim mesmo, com aviso no log que não escreve os ids.
  A recusa é a de sempre (403 `"Requer perfil: Administrador ou Técnico da
  TI"`), igual para todos. `require_leitura_dos_lembretes` é usada só por esta
  rota: `require_admin`, `require_equipe_ti` e `integra_equipe_ti` não mudam,
  e a conta do painel segue com 403 nas sete rotas de tarefas, na
  administração, no interno e nas escritas de equipe. O diagnóstico ganhou a
  seção `painel`: a lista contra o cadastro, só com ids. O FE-5 não usa a rota.

  **Riscos residuais e dependências:**
  - **O lembrete "tarefas do dia" some na TV.** Como técnico de serviço,
    já desde a API-10. Como administrador de serviço, o FE-5 segue pedindo
    `GET /tarefas-recorrentes/?ativo=true` a cada 10 minutos (o
    `podeAdministrar` vem do perfil) e agora recebe 403; o menu de
    administração aparece e devolve 403. Configurar `PAINEL_CONTAS_IDS` não
    basta: o lembrete volta só com o id real da TV conferido e um FE novo
    que use a rota (não iniciado).
  - **A lista vale o inventário.** Um id errado de conta de serviço dá a ela
    só os títulos das tarefas do dia; quem tem a senha da TV lê de qualquer
    máquina (a TV não tem identidade de dispositivo).
  - **`SETORES_TI_IDS` com milhares de dígitos derruba a subida** (o `int()`
    recusa texto acima de 4300 dígitos). Achado durante a S1, anterior a ela
    (API-6), não corrigido; `PAINEL_CONTAS_IDS` não tem o problema.
  - **Sem administrador humano em produção, ninguém administra pela API
    depois do deploy.** Não verificado — ver a ação de deploy.
  - Sem trilha geral de `PUT` de chamado e de exclusão definitiva, e
    `GET /usuarios/` aberto a todo autenticado: fora do escopo (S6).
  - SQL direto (n8n com acesso ao banco, DBeaver) passa por fora da regra.

  Testes: `test_conta_de_servico_escritas.py` (80: 9 escritas de equipe ×
  as contas de serviço, recusa sem efeito, o que continua, pessoas que não
  mudam), `test_conta_de_servico_administradora.py` (74: 16 rotas só do
  administrador e 18 da equipe, o que continua, o administrador humano),
  `test_ultimo_administrador_humano.py` (21) e
  `test_ultimo_administrador_humano_postgres.py` (24, com 3 cenários de
  concorrência em PostgreSQL), `test_registro_sem_conta_de_servico.py` (11),
  `test_lembretes_do_dia.py` (39) e `test_contas_tecnicas_postgres.py` (204,
  os de S1, S2, S3 e S5 em PostgreSQL). Prova por mutação: sem a guarda,
  falham 21 dos 80 de escrita, 37 dos 74 de administração, os 3 de
  concorrência (sem o `FOR UPDATE`) e os 7 de registro. Testes anteriores
  mudaram de expectativa, de propósito: as classes de pendência de
  `test_conta_de_servico_rotas.py` viraram `TestAlcanceDePerfil` e
  `TestContaDeServicoAdministradora` (agora recusas), o caso
  `GET /eventos/?alvo=usuario` foi para a matriz de administração, e
  `test_conta_de_servico_equipe_ti.py` passou a usar administrador humano.

  Testes do painel: `test_painel_lembretes.py` (108: a leitura da variável,
  a matriz de 19 configurações × 20 contas, o que não vira identidade, a
  resposta só de leitura com o dia de Brasília, o contrato do OpenAPI e o
  diagnóstico), `test_painel_isolamento.py` (219: com todas as contas de
  serviço na lista, cada rota proibida continua proibida, e as matrizes de
  recusa da API-10, da S2, da S3 e da S1 sem lista rodam de novo) e
  `test_painel_postgres.py` (89, em PostgreSQL). `test_lembretes_do_dia.py`
  passa a fixar a lista ausente. Prova por mutação: sem a marca de serviço
  falham 12; sem o `ativo`, 4 (o `get_current_user` já barra o inativo);
  sem a lista, 50; com a lista aproveitando os itens válidos, 34; a
  dependência na listagem do módulo, 13; o painel dentro de
  `require_equipe_ti`, 78; a rota de volta só para a equipe, 40.

  Validação local: **9.370 testes únicos, igual à coleta** — 6.087 em
  SQLite e 3.283 em PostgreSQL 15.19 descartável, sobre o código final
  (`125170a`), serial, em lotes conferidos pelo junit, sem skip, sem
  repetição, sem falha. Inclui a matriz de concorrência T1–T14 (63 em
  PostgreSQL). Sobre os 8.954 da API-11 antes da S1 completa: +416 ids
  novos (219 + 108 + 89) e nenhum que saiu. Sobre os 8.503 da API-10, a
  conta anterior: +479 ids novos e 28 que saíram — das classes de pendência de
  `test_conta_de_servico_rotas.py`, 13 em SQLite e 13 em PostgreSQL (12
  renomeados em cada, e o de `alvo=usuario`, absorvido pela matriz de
  administração), e 2 ids de `test_trava_rotas_protegidas.py` que mudaram
  de nome porque `require_admin` virou função própria.

### Segurança — contas de serviço fora da equipe da TI (API-10, C1)
- **Decisão C1 (homologação FE-5 × API-9):** conta de serviço não integra a
  equipe da TI. A homologação achou o defeito: uma conta de serviço com
  perfil Técnico num setor de `SETORES_TI_IDS` recebia
  `integra_equipe_ti: true` no `/auth/me`, passava em `require_equipe_ti` e
  criava comentário interno (201). Era o risco residual registrado na API-7,
  na API-8 e na API-9; agora é fechado.

  **Onde:** só em `integra_equipe_ti` (`app/services/leitura_service.py`),
  a definição única da equipe. Nada foi repetido por rota, nenhuma segunda
  definição de equipe foi criada, e `SETORES_TI_IDS` não mudou. Sem
  migration, sem coluna nova, sem variável nova, versão inalterada. Só
  `conta_de_servico` igual a `False` conta como pessoa: `None` (o que o ORM
  deixa antes do flush) ou qualquer valor que não seja booleano não
  integra. No banco a coluna é `NOT NULL DEFAULT false`, então em produção
  o caso não existe; o tratamento é só defesa.

  **O que a conta de serviço perde** (todas as que não são administradoras;
  na prática, a técnica de setor da TI, a única que integrava):
  - `integra_equipe_ti: false` no `/auth/me`;
  - as rotas de `require_equipe_ti`: escrita de setor e de categoria,
    `PUT /sla-configs/{prioridade}`, as sete rotas de tarefas recorrentes,
    a trilha de setor (`GET /eventos/`) e `GET /chamados/responsaveis-ti` —
    403 `"Requer perfil: Administrador ou Técnico da TI"`, nada gravado;
  - o comentário interno: a listagem traz só os públicos, a busca por id
    dá 404 igual a id inexistente, criar dá 403 `CRIAR_INTERNO_NEGADO` sem
    gravar, e editar ou excluir dá 404 — **mesmo o interno que a própria
    conta escreveu antes**, que fica no banco e segue visível para a equipe;
  - o comentário público continua (201), nos chamados que ela lê.

  A regra de responsável (API-9) não muda: a conta de serviço já era
  recusada (400 `"Não é possível atribuir um chamado a uma conta de
  serviço"`), não aparecia na lista e não se autoatribuía.

  **O que fica, de propósito — riscos residuais, não aprovação:**
  - **Conta de serviço com perfil Administrador mantém tudo do perfil.** A
    C1 não muda o administrador: `is_admin` vale nas rotas antes de
    `integra_equipe_ti`, e a conta administradora de serviço ainda
    administra setores, categorias, SLA, tarefas, usuários e eventos, lê e
    cria comentário interno e pede a lista de responsáveis. Recebe
    `integra_equipe_ti: false` no `/auth/me`, então o FE-5 trata pelo
    `role` (`podeAdministrar` é `role === 'Administrador' ||
    integra_equipe_ti`). A migration de `conta_de_servico` cita "a conta
    compartilhada de administração" e o login via FortiPAM entre as contas
    de serviço reais: **pela migration, existe em produção** (não conferido
    no banco). Tirar dela o poder do perfil muda a semântica global do
    Administrador e exige decisão própria. Por isso, não é verdade que toda
    conta de serviço perdeu poder: só as não administradoras.
  - **A conta de serviço técnica da TI ainda lê e altera chamados pelo
    alcance do perfil.** A leitura (API-5) e a escrita de equipe (API-6:
    `PUT`, arquivar, desarquivar, cancelar chamado alheio) usam
    `setores_lidos_pelo_perfil`, que não passa por `integra_equipe_ti`. A
    leitura é a do painel de parede citado na migration, e foi mantida. A
    escrita não tem uso documentado: a decisão de tirá-la, mantendo a
    leitura, fica proposta. A técnica de serviço da Qualidade, da mesma
    forma, lê e altera os chamados da Qualidade.
  - **Dependência de produção não verificada:** não se sabe, daqui, se
    alguma conta de serviço técnica da TI é usada por pessoas (pelo
    FortiPAM, por exemplo) para administrar. Se for, ela perde a
    administração com a API-10. Conferir antes do deploy quais contas têm
    `conta_de_servico = true`, com qual perfil e setor; nenhuma exceção foi
    criada.

  **Compatibilidade com o FE-5:** nenhuma mudança no frontend. O FE-5 já
  decide pelo `/auth/me` (`podeAdministrar`) e só pede
  `/chamados/responsaveis-ti` a quem pode reatribuir: a conta de serviço
  técnica deixa de ver a administração e o interno, sem 403 na tela. Com o
  FE-5 ainda no ar contra a API-9, ela continua vendo — é o defeito, e a
  API-10 é que o fecha.

  Testes: `test_conta_de_servico_equipe_ti.py` (a regra à mão, 14 tipos de
  conta × 7 configurações de `SETORES_TI_IDS`, contra `integra_equipe_ti`,
  `require_equipe_ti`, `pode_acessar_comentario_interno` e
  `pode_ser_novo_responsavel`; marcar como serviço nunca concede; valor
  ambíguo não é pessoa), `test_conta_de_servico_rotas.py` (as rotas com
  token real, recusa sem escrita, comentários interno e público, ordem
  404 antes do 403, responsáveis, e as duas classes de pendência que
  descrevem o administrador de serviço e o alcance de perfil) e
  `test_conta_de_servico_rotas_postgres.py`, que roda as de rota em
  PostgreSQL real. Sem a guarda da C1, 29 dos 496 testes da matriz e 18 dos
  95 de rota falham. Testes anteriores mudaram de expectativa, de
  propósito: os conjuntos `TECNICOS_DA_TI`/`DA_TI` de
  `test_administracao_equipe_ti.py`, `test_comentarios_internos.py`,
  `test_me_equipe_ti.py` e `test_permissao_equipe_ti.py` perderam a conta
  de serviço técnica da TI (os que importam esses conjuntos seguem
  sozinhos), e
  `test_comentarios_internos.py::test_conta_de_servico_tecnico_da_ti_ve_o_interno`
  (o risco residual da API-8) virou
  `test_conta_de_servico_tecnico_da_ti_nao_ve_o_interno`.

  Validação local: 8.503 testes únicos, igual à coleta — 5.536 em SQLite e
  2.967 em PostgreSQL 15.19 descartável, serial, em lotes conferidos pelo
  junit, sem skip. Inclui a matriz de concorrência T1–T14 (63 em
  PostgreSQL). Sobre os 7.815 da API-9: +686 novos (496 da matriz, 95 de
  rota em SQLite e 95 em PostgreSQL), +2 do parâmetro
  `conta_de_servico_ti`, que entrou em
  `test_comentarios_internos.py::test_o_interno_nao_vaza_por_outra_resposta`
  (SQLite e PostgreSQL) ao sair da equipe, e 2 renomeados.

### Adicionado e corrigido — responsáveis elegíveis da TI (API-9, F5-1)
- **Decisão F5-1 (auditoria de compatibilidade FE-5 × API-8):** criar uma
  rota com os responsáveis elegíveis da TI e impedir novas atribuições a
  usuários inativos. A auditoria achou duas lacunas: o frontend não tinha
  como saber quem a API aceita como responsável de chamado da TI — montava o
  seletor com `GET /usuarios/` e um filtro de perfil, e oferecia técnico de
  outro setor, administrador de fora da TI e conta inativa, que o PUT
  recusava com 400 —, e a validação do responsável da TI não olhava
  `ativo`: o técnico desativado num setor da TI ainda recebia chamado novo,
  que ninguém atenderia, porque a conta inativa nem se autentica.

  **Regra única** (`app/services/responsavel_ti_service.py`), como a
  `qualidade_service` é para a Qualidade: a validação da mudança de
  responsável no `PUT` e a lista nova passam pela mesma função,
  `pode_ser_novo_responsavel`. Elegível para ser **novo** responsável de
  chamado da TI é a conta que:
  1. existe;
  2. não é conta de serviço;
  3. `integra_equipe_ti` diz ser da TI (API-6, D9) — perfil Administrador
     ou Técnico num setor de `SETORES_TI_IDS`, nunca o da Qualidade;
  4. está ativa (**novo**; `ativo` NULL conta como inativo).

  A regra é da conta atribuída, não de quem atribui. O administrador **não**
  entra na lista pelo poder administrativo: só se estiver num setor da TI,
  como a API-6 já exigia na atribuição. Nada foi ampliado.

  **`GET /api/v1/chamados/responsaveis-ti`** — `[{"id": int, "nome": str}]`,
  por nome e, no empate, por id (o `nome` é único no banco; o id é só
  defesa). Nenhum outro campo: nem senha, nem hash, nem setor, perfil ou
  estado. Nenhum parâmetro do cliente entra na lista — `?setor_id=`,
  `?ativo=false` e afins são ignorados. Autorização `require_equipe_ti`:
  administrador (de qualquer setor) e técnico da TI, os únicos que o `PUT`
  deixa reatribuir chamado da TI; técnico da Qualidade, de outro setor, sem
  setor e usuário comum recebem 403 `"Requer perfil: Administrador ou
  Técnico da TI"`; sem token, 401; conta inativa, o 403 `"Usuário inativo"`
  de sempre. Declarada antes de `/{chamado_id}`, como
  `/atendentes-qualidade`. A consulta estreita aos setores da TI no SQL,
  traz a role no mesmo SELECT (sem N+1) e deixa a decisão para a regra.

  | `SETORES_TI_IDS` | Lista | Quem pede |
  |---|---|---|
  | válida (`"1"`, `"1,1"`, `"1,999"`) | os elegíveis dos setores válidos | administrador e técnico da TI |
  | conflitando com a Qualidade (`"1,2"`) | só a do setor 1; a Qualidade nunca vale como TI | idem |
  | ausente, vazia, inválida, só a Qualidade, só setor inexistente | **vazia**, com aviso no log | só o administrador |

  Sem lista válida não há fallback para "todos os técnicos" nem id
  inventado: a lista vazia diz que ninguém pode receber chamado da TI, e é
  exatamente o que o `PUT` faria.

  **Inativo recusado na mudança de responsável:** 400 `"Técnico
  responsável está inativo"`, no lugar das outras recusas de responsável —
  depois do 404 de alcance e da conferência de versão (409 da TI quando
  `versao_esperada` vem e está velha; a ordem da API-6 não muda), antes de
  qualquer gravação. Nada é gravado numa recusa: nem o responsável, nem os
  outros campos do mesmo corpo, nem histórico, nem versão, nem webhook. A
  checagem vem depois da de equipe: o inativo de fora da TI continua
  recebendo `"Técnico responsável não é da equipe da TI"`, e nenhuma
  mensagem que já existia mudou.

  **Caminhos de atribuição conferidos:** o `PUT /chamados/{id}` é o único
  que muda o responsável de chamado da TI — reatribuição, autoatribuição e
  atribuição pela edição completa passam todos por ele. A abertura da TI
  continua **ignorando** `tecnico_responsavel_id` no corpo (o chamado nasce
  sem responsável). A conta inativa não se autoatribui: não se autentica. A
  Qualidade tem a regra dela, que já recusava o inativo (`eh_elegivel`), e
  não mudou. O atendimento (`PATCH .../atendimento`) não muda responsável.

  **Responsável antigo preservado (D9):** a regra vale na **mudança**.
  Omitir o campo, ou reenviar o responsável atual (a edição completa do
  frontend faz isso), não revalida nada: o chamado antigo atribuído a quem
  hoje está inativo ou fora da TI fica com essa pessoa e continua editável —
  status, prioridade, solução. Desatribuir (`null`) continua permitido.
  Nada troca o responsável sozinho, e nada no banco é alterado. Mas essa
  pessoa não aparece na lista, e escolhê-la de novo depois de trocar é
  mudança, e é recusada. (Exceção que já existia: conta de serviço é
  recusada mesmo como responsável atual.)

  **O FE-5 precisa:**
  - Chamar `GET /chamados/responsaveis-ti` só para quem pode reatribuir —
    `role === 'Administrador' || integra_equipe_ti === true` —; para os
    outros a rota dá 403, e o interceptor global mostraria o toast.
  - Montar o seletor da TI com essa lista (página e modal), no lugar de
    `usuariosService.listarTodos({ ativo: true })` filtrado por
    `podeSerResponsavel` (`ChamadosContext.carregarTecnicos`,
    `ChamadoModal.atribuiveis`).
  - Lista vazia: nenhuma opção além de "Sem atribuição"; com o
    administrador, avisar que não há responsável elegível configurado.
  - Responsável atual fora da lista: mostrar `"Nome (fora da equipe)"` como
    valor atual, só informativo — a opção não autoriza nada, e a API recusa
    se ela for escolhida de novo depois de trocada. O nome tem de vir de
    outro lugar: a lista não o traz, e `usuarios` carregado com
    `ativo: true` também não traz o inativo (hoje a tela mostra "Não
    encontrado"). Corrigir o `Seletor`, que mostra a primeira opção quando
    o valor não está na lista.
  - 400 do responsável (`"…está inativo"`, `"…não é da equipe da TI"`,
    `"…conta de serviço"`): mostrar o `detail`, manter o que foi digitado,
    e recarregar a lista — ela pode ter mudado.
  - Recarregar a lista ao abrir a edição, não só uma vez por sessão: a
    mudança de setor, de perfil ou de `ativo` vale no próximo pedido, sem
    cache.
  - Contra uma API sem a rota (API-8 ou anterior), `/chamados/responsaveis-ti`
    cai em `/chamados/{chamado_id}` e responde **422**. Não deve acontecer
    na implantação coordenada (F5-4: a API antes do front); se acontecer,
    tratar como lista indisponível — sem voltar ao filtro de perfil, que
    oferece quem a API recusa.

  **Riscos residuais:**
  - Conta de serviço com perfil Técnico num setor da TI pede a lista, como
    administra na API-7 — e não aparece nela.
  - A lista mostra nomes de toda a equipe da TI a quem já pode atribuir;
    `GET /usuarios/` segue aberto a qualquer autenticado (D7, A7-8),
    então nada novo é exposto.
  - Chamados antigos atribuídos a inativos continuam com eles até alguém
    reatribuir; a API-9 não os lista nem os altera.

  Testes: `test_elegibilidade_responsavel_ti.py` (a regra, 14 tipos de
  conta × 9 configurações × ativo/inativo/NULL, igual a `integra_equipe_ti`
  mais o `ativo`, e as mensagens), `test_responsavel_ti_inativo.py`
  (recusa sem escrita por quem atribui, ordem 404/409/400, chamado antigo,
  desatribuição, abertura, Qualidade), `test_responsaveis_ti_lista.py`
  (quem pede, por configuração; conteúdo, campos, ordem, parâmetros
  ignorados, número de consultas, rota estática, sonda D-6, OpenAPI, e a
  lista igual ao que o `PUT` aceita para toda conta em toda configuração) e
  `test_responsaveis_ti_postgres.py`, que roda os de rota em PostgreSQL
  real. Um teste anterior mudou de expectativa, de propósito:
  `test_reatribuicao_qualidade.py::TestTiInalterada::test_conta_inativa_da_equipe_continua_aceita_na_ti`
  travava o aceite do inativo na TI ("pendente" da D9) e virou
  `test_conta_inativa_da_equipe_e_recusada_na_ti`.

  Validação local: 7.815 testes únicos, igual à coleta — 4.944 em SQLite e
  2.871 em PostgreSQL 15.19 descartável, serial, em lotes conferidos pelo
  junit, sem skip. Inclui a matriz de concorrência T1–T14.

### Segurança — comentário interno só para administrador e TI (API-8)
- **Comentário interno deixa de ser de qualquer perfil Técnico.** O
  inventário da API-7 mostrou que os comentários decidiam o interno por
  `is_staff`: o técnico da Qualidade, o de outro setor e o sem setor viam e
  criavam comentário interno em todo chamado que liam — pelo perfil (o da
  Qualidade, nos chamados da Qualidade) ou pelo vínculo (o que abriram ou
  atendem). Regra aprovada: **só administrador e técnico da TI leem e criam
  comentário interno, e só nos chamados que leem.**

  **Nova função `pode_acessar_comentario_interno`**
  (`app/services/leitura_service.py`): o administrador, pelo perfil, em
  qualquer setor; e o técnico que `integra_equipe_ti` diz ser da TI — a
  mesma regra da API-6 e da `require_equipe_ti` da API-7, sem classificação
  paralela, sem configuração nova, sem campo no banco ou no token. Sem
  `SETORES_TI_IDS` válida, só o administrador; nenhum fallback para
  qualquer técnico.

  **Duas autorizações, as duas exigidas:** ler o chamado (API-5/API-6) e
  poder o interno. Ler o chamado vem antes, e a recusa dele é sempre o 404 de
  um chamado ou comentário que não existe (D6/D12).

  | Rota | Quem lê o chamado e pode o interno | Quem lê o chamado e não pode | Quem não lê o chamado |
  |---|---|---|---|
  | `GET /comentarios/chamado/{id}` | públicos e internos | só os públicos (200; lista vazia se só houver internos) | 404 |
  | `GET /comentarios/{id}` | 200 | interno: 404 igual ao de id inexistente | 404 |
  | `POST /comentarios/` interno | 201 | **403** `"Apenas administrador ou técnico da TI pode criar comentário interno"`, nada gravado | 404, antes de olhar o tipo |
  | `POST /comentarios/` público | 201 | 201 (inalterado) | 404 |
  | `PUT` / `DELETE /comentarios/{id}` de interno | autoria de sempre (autor ou administrador) | **404, mesmo sendo o autor** | 404 |
  | `PUT` marcando `is_interno: true` | autoria de sempre | **403** `"Apenas administrador ou técnico da TI pode marcar comentário como interno"` | 404 |

  Quem não pode o interno também não o torna público pela edição: nem chega
  a ele (404). O administrador mantém os poderes de sempre — edita e exclui
  o comentário alheio, interno incluído — e o técnico da TI não ganha
  autoria sobre o interno alheio (403 de sempre). As mensagens de 403 do
  interno mudaram de "administrador ou técnico" para "administrador ou
  técnico da TI"; status e formato (`{"detail"}`) são os de antes.

  **Defeito corrigido no caminho:** `PUT` com `"is_interno": null` gravava
  NULL (a coluna aceita) e respondia 500, e a busca por id tratava um NULL
  como público. Agora o `null` vale como não enviado, e a busca trata NULL
  como interno, como a listagem já fazia (`is_interno IS false`). Nenhum
  dado é migrado.

  Nenhuma outra resposta carrega texto de comentário: detalhe, listagem e
  histórico de chamado, eventos, webhook e diagnóstico foram conferidos, e
  um teste procura o texto dos internos nelas para cada perfil sem
  permissão. Comentários existentes — públicos e internos — ficam como
  estão: nenhum é apagado, convertido ou migrado.

  **Compatibilidade com o FE-4:** nenhum contrato quebra. O FE-4 só cria
  comentário público (`is_interno: false`), não edita nem exclui
  comentário, e mostra a lista que a API devolve, sem distinguir o
  interno. Com a API-8, o técnico de fora da TI simplesmente deixa de
  receber os internos. Até a API-8 a tela dele os mostrava misturados aos
  públicos, sem marca.

  **O FE-5 precisa:** oferecer a opção de comentário interno só a
  `role === 'Administrador' || integra_equipe_ti` (o mesmo critério da
  administração); não oferecê-la ao técnico da Qualidade nem ao usuário;
  marcar visualmente o comentário interno para quem o recebe; tratar o 403
  do interno sem perder o texto digitado; e, se um dia editar ou excluir
  comentário, tratar o 404 como "não está mais disponível". A API continua
  sendo quem decide.

  **Riscos residuais:**
  - Conta de serviço com perfil Técnico num setor da TI vê e cria interno,
    como administra na API-7: a regra é a do perfil e do setor.
  - Quem já leu um interno antes da API-8 pode ter guardado o texto; a
    API-8 fecha o acesso daqui em diante e não apaga o que já foi visto.
  - A lista de comentários não tem `ORDER BY` (inalterado): a ordem é a que
    o banco devolve.
  - Alteração de SLA e de categoria segue sem trilha (A7-7), e o diretório
    de usuários segue aberto (D7, A7-8).

  Testes: `test_permissao_comentario_interno.py` (a função, 13 tipos de
  conta × 8 configurações, igual a `integra_equipe_ti` e a
  `require_equipe_ti`), `test_comentarios_internos.py` (configuração ×
  perfil × chamado na leitura, criação por configuração, perfil e tipo,
  recusa sem escrita e sem requisição externa, vazamento por outras
  respostas, casos nomeados), `test_comentarios_internos_edicao.py` (edição
  e exclusão do próprio comentário por configuração, perfil, tipo e ação;
  mudança de visibilidade; o NULL; os poderes de sempre) e
  `test_comentarios_internos_postgres.py`, que roda os de rota em
  PostgreSQL real. `leitura_cenario.EQUIPE` virou `VEEM_INTERNO` (o técnico
  da Qualidade saiu) e a mensagem esperada do 403 de marcar interno mudou
  em `test_comentarios_edicao.py`.

### Segurança — administração global da equipe da TI (API-7, D13)
- **Setores, categorias, SLA, tarefas recorrentes e a trilha de setor
  deixam de ser de qualquer técnico.** A auditoria D13 (29/10/2026) mostrou
  que essas rotas seguiam com `require_staff` depois da API-6: técnico da
  Qualidade, de outro setor ou sem setor criava e renomeava setor, mudava o
  prazo de SLA dos dois setores, editava categoria, lia, editava, excluía e
  marcava como feita a rotina da TI, e lia a trilha de setores. Nenhuma
  escalada de privilégio (escrita em usuário já era só do administrador).
  Decisões A7-1 a A7-8, aprovadas em 29/10/2026.

  **Nova dependência `require_equipe_ti`** (`app/api/deps.py`): passa o
  administrador, pelo perfil, em qualquer setor; e o técnico que
  `integra_equipe_ti` diz ser da TI — a mesma regra da API-6 que decide o
  responsável de chamado da TI, sem algoritmo paralelo. Recusa com 403
  `{"detail": "Requer perfil: Administrador ou Técnico da TI"}`; sem token,
  401 como sempre. 403 e não 404: recursos globais, cuja existência não é
  segredo (a D6/D12 segue valendo para chamados e comentários).

  | Rota | Admin | Técnico da TI | Técnico da Qualidade, de outro setor, sem setor | Usuário, perfil desconhecido |
  |---|---|---|---|---|
  | `POST/PUT /setores`, `PATCH …/desativar`, `…/reativar` (A7-1) | sim | sim | 403 (era sim) | 403 |
  | `DELETE /setores/{id}` (A7-1) | sim | **403 (era sim)** | 403 (era sim) | 403 |
  | `POST/PUT/DELETE /categorias` | sim | sim | 403 (era sim) | 403 |
  | `PUT /sla-configs/{prioridade}` (A7-2) | sim | sim | 403 (era sim) | 403 |
  | `/tarefas-recorrentes`, as sete rotas, leitura incluída (A7-4) | sim | sim | 403 (era sim) | 403 |
  | `GET /eventos/` (A7-4) | todos os alvos | só `alvo=setor`, como antes | 403 (era só setor) | 403 |
  | GET de setores, categorias e SLA | sim | sim | sim | sim (inalterado) |
  | `/usuarios` (A7-8) | inalterado | inalterado | inalterado | inalterado |

  A exclusão de setor recusada ao técnico usa o 403 de `require_admin`, o
  mesmo das rotas de usuário (`"Requer perfil: Administrador"`).

  A Qualidade não recebe nenhuma permissão administrativa (A7-3): segue com
  a leitura, o atendimento e as escritas de chamado das decisões anteriores,
  e não administra nem o próprio setor por estas rotas. A exclusão de setor
  pelo administrador mantém as travas de sempre (vínculo com usuário, 400;
  sem cascata). As validações, os formatos de resposta, a trilha de setor e
  a identidade do executor da rotina (do token) não mudam. A recusa não
  grava nada: nem linha, nem evento, nem execução, nem avanço de
  `proxima_data`.

  **Sem `SETORES_TI_IDS` válida (A7-6)**, nenhum técnico administra; o
  administrador continua, e login, abertura de chamado e a Qualidade não
  dependem dela. O log da subida e o alerta do `GET /api/v1/diagnostico`
  passam a dizer isso.

  **`GET /auth/me` ganha `integra_equipe_ti: bool` (A7-5)**, calculado a
  cada pedido por `integra_equipe_ti` — o mesmo resultado da trava. Só de
  resposta: não está no cadastro (mandado no `PUT /usuarios`, é ignorado),
  no banco nem no token; muda no pedido seguinte a uma troca de setor ou de
  configuração. **Diz de qual equipe a conta é, não o que ela pode:** o
  administrador fora de setor da TI recebe `false` e administra assim mesmo.
  A tela combina os dois: `role === 'Administrador' || integra_equipe_ti`.
  Campo novo; os de antes não mudam, e o frontend atual o ignora.

  **Riscos residuais:**
  - **Alteração de SLA e de categoria continua sem trilha** (A7-7): quem
    mudou o prazo ou a categoria não fica registrado. Fora de escopo, sem
    tabela nova.
  - Conta de serviço com perfil Técnico num setor da TI administra, como
    antes: a regra é a do perfil e do setor, e a recusa da conta de serviço
    vale só como responsável de chamado.
  - **Comentário interno é de qualquer perfil Técnico** (fora da D13,
    achado no inventário): o técnico de outro setor, sem setor ou da
    Qualidade que lê um chamado pelo vínculo — que o abriu ou o atende — vê
    e cria comentário interno nele, porque "ser da equipe" ali é `is_staff`.
    Não é rota administrativa global. **Fechado na API-8 (acima).**
  - O diretório de usuários (`GET /usuarios`) segue aberto a qualquer conta
    autenticada (D7, A7-8).

  **Frontend:** nenhum contrato quebrado; o FE-4 funciona. Até o FE-5,
  técnico de fora da TI que abrir Cadastros, Tarefas Recorrentes ou
  Auditoria recebe o toast "Sem permissão" do 403. O FE-5 precisa: ler
  `integra_equipe_ti` no `AuthContext`; esconder ou bloquear as três áreas
  (`router.tsx`, `lib/navegacao.ts`) para quem não é administrador nem da
  TI; tirar o botão de excluir da `SetoresTab` para o técnico; travar a
  `SlaTab`, que hoje não confere perfil; e ajustar `TarefasRecorrentes`
  (`podeGerenciar`) e `Auditoria` ao mesmo critério.

  Testes: `test_permissao_equipe_ti.py` (a dependência, 13 tipos de conta ×
  8 configurações, e o aviso da subida), `test_administracao_equipe_ti.py`
  (perfil × configuração × as 17 rotas, recusa sem escrita e sem requisição
  externa, 401, leituras abertas, travas de sempre, eventos por alvo),
  `test_me_equipe_ti.py` (o campo por perfil e configuração, igual à trava,
  fora do cadastro e do token) e `test_administracao_equipe_ti_postgres.py`,
  que roda os dois de rota em PostgreSQL real (o da dependência não usa
  banco). `test_exclusao_de_setor.py`: o caso do técnico excluindo setor
  passou de 204 para 403 (A7-1).

### Segurança — escritas e segregação de setores (API-6)
- **A equipe só altera o que o perfil dela lê, e a TI passa a ser uma lista
  explícita de setores.** A auditoria complementar da API-5 (29/10/2026)
  achou o técnico da Qualidade editando, cancelando e arquivando chamado da
  TI pelas rotas da equipe — e recebendo na resposta o chamado que não podia
  ler, com a versão no 409 —, se atribuindo um chamado da TI para passar a
  lê-lo pelo vínculo, e qualquer conta descobrindo se um id existia pelas
  recusas de cancelar, avaliar e atender (o atendimento dizia até o setor).
  Pré-existentes, latentes enquanto ninguém tiver perfil Técnico no setor da
  Qualidade. Decisões D8–D13 e H1, aprovadas em 29/10/2026.

  **Quem é da TI (D10): `SETORES_TI_IDS`**, ids de setor separados por
  vírgula, sem valor padrão nem exemplo. Até a API-5, técnico de qualquer
  setor que não fosse o da Qualidade era da TI. Agora:

  | Conta | Lê por perfil | Altera pelas rotas da equipe | Pode ser responsável da TI |
  |---|---|---|---|
  | Administrador | tudo | tudo | se o setor estiver em `SETORES_TI_IDS` |
  | Técnico de setor em `SETORES_TI_IDS` (D1) | TI e Qualidade | TI e Qualidade | sim |
  | Técnico do setor de `SETOR_QUALIDADE_ID` (D2) | Qualidade | Qualidade | não |
  | Técnico de outro setor (D10) | nada | nada | não |
  | Técnico sem setor (H1) | nada | nada | não |
  | Usuário comum, qualquer setor | nada | nada | não |
  | Perfil desconhecido | nada | nada | não |

  Fora do perfil, o **vínculo** de sempre (solicitante ou responsável atual)
  dá a leitura — **não o poder de equipe**: o técnico da Qualidade que
  responde por um chamado da TI o lê, mas recebe 403 ao editá-lo.

  Sem lista válida — ausente, vazia ou com algum item que não é id —
  **nenhum técnico é da TI**: cada um fica só com o vínculo. A API sobe assim
  mesmo e avisa no log; login, abertura de chamado, a Qualidade e o
  administrador não dependem dela. Repetidos valem uma vez; o id da
  Qualidade nunca vale como TI. Lista e não "o que não é Qualidade", para que
  um técnico de Laboratório ou Diretoria não leia tudo por exclusão.

  **Escritas de chamado (D8, D12):**

  | Rota | Quem não lê o chamado | Quem lê só pelo vínculo | No alcance da equipe |
  |---|---|---|---|
  | `PUT /chamados/{id}` | 404 (era 200 para técnico) | 403 "Este chamado não é da sua equipe" | como antes |
  | `PATCH …/arquivar`, `…/desarquivar` | 404 | 403 | como antes |
  | `PATCH …/cancelar` | 404 (era 403/200) | o próprio: 200; senão 403 | como antes |
  | `PATCH …/avaliar` | 404 (era 403) | só o solicitante, como antes | — |
  | `PATCH …/atendimento` | 404 (era 403 com o setor no texto) | as recusas de antes | — |
  | `PUT`/`DELETE /comentarios/{id}` (D11) | 404 (era 200/204 para o autor, 403 para os outros) | as de antes | — |

  O perfil Usuário continua com 403 no PUT, arquivar e desarquivar antes de
  qualquer busca (não distingue ids). O 404 é o mesmo de um id inexistente —
  status e corpo —, vem antes da versão (428/409), do estado ("já está
  arquivado") e das recusas do atendimento, e nada é gravado: nem campo, nem
  histórico, nem webhook, nem versão. Para quem altera, 409, 428, `FOR
  UPDATE`, histórico atômico da Qualidade e webhook da TI ficam como estavam.
  A sonda D-6 (`GET /chamados/0/atendimento` → 405) não muda.

  **Responsável de chamado da TI (D9):** só conta da equipe da TI — perfil de
  equipe num setor de `SETORES_TI_IDS` —, pela conta atribuída e não por quem
  atribui: nem o administrador entrega chamado da TI a quem é de fora. 400
  "Técnico responsável não é da equipe da TI". Vale na **mudança**: o chamado
  antigo com responsável de fora continua editável e ninguém é trocado
  sozinho. Conta de serviço e id inexistente mantêm as mensagens;
  desatribuir continua permitido; a Qualidade mantém a elegibilidade dela. O
  `ativo` do responsável da TI segue sem conferência (pendente).

  **Comentários (D11):** editar e excluir passam pela visibilidade do `GET
  /comentarios/{id}` — chamado legível e, se interno, perfil de equipe —, e
  depois a autoria de sempre. O ex-responsável, o autor de comentário de
  antes da API-5 e o técnico da Qualidade num chamado da TI deixam de mexer
  no que escreveram lá.

  **D13 — PARCIALMENTE atendida na API-6; fechada na API-7 (acima).** As
  operações de chamado e de comentário
  respeitam o alcance. **Os cadastros administrativos não:** o perfil Técnico
  de qualquer setor — Qualidade, outro, sem setor — continua com
  `require_staff` em:

  | Rotas | Classificação | Risco para a Qualidade |
  |---|---|---|
  | `POST/PUT/PATCH/DELETE /setores` | D — sem regra definida | desativar o setor da Qualidade fecha a Qualidade (503); renomear ou excluir setor mexe no cadastro de que `SETORES_TI_IDS` depende |
  | `POST/PUT/DELETE /categorias` | B — da TI (só chamado da TI tem categoria) | altera a classificação da TI |
  | `PUT /sla-configs/{prioridade}` | D — o SLA vale para os dois setores | muda prazo da TI |
  | `/tarefas-recorrentes` (todas) | B — rotinas da TI | lê e executa as rotinas da TI |
  | `GET /eventos?alvo=setor` | segue setores | lê a trilha de setores |

  Administrador-só e já fechados: usuários (escrita), `/auth/registro`,
  `/diagnostico`, eventos de conta, `DELETE /chamados`. Restringir os de
  cima a "administrador ou técnico da TI" é uma troca de dependency por rota,
  sem migration, mas muda quem administra cadastro: decisão pendente. **Até
  lá, a Qualidade não deve ser ativada com contas de perfil Técnico no setor
  dela** — a mitigação é cadastrar a equipe da Qualidade com perfil Usuário,
  que já atende pela elegibilidade de setor.

  **Diagnóstico:** `GET /api/v1/diagnostico` (administrador) ganha o bloco
  `equipes`: o estado de `SETORES_TI_IDS`, ids inexistentes ou inativos no
  cadastro, o conflito com a Qualidade e quantos técnicos ativos ficam sem
  alcance. Para escolher os ids, `diagnosticos/api6_setores_ti.sql`
  (somente leitura, `BEGIN READ ONLY … ROLLBACK`) — ver "Ação necessária no
  deploy".

  **Frontend:** contratos `versao`/`versao_esperada` e formatos de resposta
  inalterados; o FE-4 funciona. Com a lista configurada, a TI opera como
  antes. Pendências para um FE-5: o seletor de responsável da TI oferece todo
  administrador e técnico ativo, e escolher alguém de fora dá o toast do 400
  (filtrar exige a API expor quem é elegível — não existe rota para isso
  hoje); o 404 da releitura e da edição de comentário aparece como erro
  genérico; no modal do Kanban, o chamado antigo e as ações seguem visíveis
  depois do 404; os menus de cadastro aparecem para técnico de qualquer
  setor.

  Testes: `test_setores_ti.py` (variável, classificação, rotas com a lista
  ausente, vazia, inválida, em conflito; diagnóstico),
  `test_escritas_por_alcance.py` (matriz conta × chamado × operação com o
  esperado escrito à mão, recusa sem gravar nada e 404 igual ao de
  inexistente; os seis estados), `test_responsavel_ti.py`,
  `test_comentarios_edicao.py`, e `test_escritas_por_alcance_postgres.py`,
  que roda os quatro em PostgreSQL real.

### Segurança — leitura por chamado (API-5, correção do O-1)
- **Chamado passa a ser lido só por quem tem relação com ele ou leitura pelo
  perfil.** Até aqui a leitura só exigia token: qualquer conta ativa lia o
  detalhe, a listagem inteira — arquivados e cancelados inclusive, até 500
  por página —, o histórico e os comentários públicos de qualquer chamado, e
  comentava em qualquer um. O "só os meus chamados" do perfil Usuário era o
  filtro que o frontend escolhia mandar. Achado O-1 da homologação da
  API-4c, anterior à API-4; auditoria de 29/10/2026.

  A regra mora em `app/services/leitura_service.py`, em duas formas que os
  testes comparam chamado a chamado — `pode_ler_chamado` para um chamado
  carregado e `escopo_de_leitura` como filtro SQL da listagem. Decisões
  D1–D7, aprovadas em 29/10/2026:

  | Quem | TI | Qualidade |
  |---|---|---|
  | Administrador | lê | lê |
  | Técnico da TI (D1) | lê | lê |
  | Técnico da Qualidade (D2) | só pelo vínculo | lê |
  | Solicitante | o próprio | o próprio |
  | Responsável atual | o atribuído | o atribuído |
  | Ex-responsável sem outro vínculo (D4) | não | não |
  | Mesmo setor do solicitante (D5) | não | não |
  | Qualquer outro autenticado | não | não |

  Técnico da Qualidade é o de perfil Técnico no setor de
  `SETOR_QUALIDADE_ID`; técnico de qualquer outro setor é da TI; técnico sem
  setor só lê pelo vínculo. Sem `SETOR_QUALIDADE_ID`, como em produção hoje,
  todo técnico com setor continua lendo tudo. **Substituído pela API-6
  (acima):** técnico da TI passa a ser só o de setor em `SETORES_TI_IDS`.

  | Rota | Antes | Agora |
  |---|---|---|
  | `GET /chamados/{id}` | qualquer autenticado | pela regra; senão 404 |
  | `GET /chamados/` | tudo, filtrado pelo que o cliente pedisse | só o permitido; os filtros estreitam, a paginação corta o permitido |
  | `GET /historico/chamado/{id}` | qualquer autenticado; id inexistente dava `[]` | pela regra; senão 404, inexistente também |
  | `GET /historico/{id}` | qualquer autenticado | segue o chamado do registro |
  | `GET /comentarios/chamado/{id}` | qualquer autenticado (internos só equipe) | pela regra; senão 404; internos como antes |
  | `GET /comentarios/{id}` | qualquer autenticado (internos só equipe) | segue o chamado do comentário; internos como antes |
  | `POST /comentarios/` | qualquer autenticado, em qualquer chamado, até inexistente | só em chamado que existe e que a pessoa lê; senão 404 |

  **A recusa é o 404 de um chamado que não existe (D6)**, com o mesmo corpo:
  tentar ids não diz quais existem, e a recusa não traz versão nem dado do
  chamado.

  **O que não muda:** as escritas (PUT, atendimento, cancelar, arquivar,
  desarquivar, avaliar, excluir), a versão e a concorrência da API-4, quem lê
  e cria comentário interno (só equipe; a responsável de perfil Usuário
  continua sem, D3), editar e excluir comentário, o SLA, o formato das
  respostas. **`GET /usuarios/` e `GET /usuarios/{id}` continuam abertos
  (D7)**: o frontend monta os nomes da tela com eles em todos os perfis; a
  revisão do diretório fica para uma etapa própria.

  **Frontend:** nenhuma mudança necessária. Os pedidos que o FE-4 faz para o
  perfil Usuário (`solicitante_id` = ele; `tecnico_id` = ele com
  `setor_destino=QUALIDADE`) devolvem o mesmo de antes, e a equipe da TI
  segue vendo os dois setores. Quem perde a atribuição e relê o chamado
  aberto na tela recebe 404, que o FE-4 mostra como erro genérico de
  carregamento — aceitável, mas pede mensagem própria num FE-5.

  **Riscos que ficam**, fora do escopo de leitura (os três primeiros
  corrigidos pela API-6, acima):
  - As escritas por perfil devolvem o chamado no corpo. O técnico da
    Qualidade continua com `require_staff` — PUT, cancelar, arquivar e
    desarquivar — também em chamado da TI, e a resposta traz o chamado que
    ele não lê. Restringir é mudar regra de escrita: decisão pendente.
  - Quem deixou de ler um chamado ainda edita e exclui os próprios
    comentários nele pelo id, e a resposta da edição traz o comentário.
  - Técnico sem setor deixa de ler os chamados que não tem vínculo. Ver
    "Ação necessária no deploy".
  - O diretório de usuários segue aberto (D7).

  Testes: `test_politica_de_leitura.py` (predicado × escopo SQL),
  `test_leitura_por_chamado.py` e `test_comentarios_por_chamado.py` (matriz
  perfil × chamado × rota, listagem com filtros e paginação, ex-responsável
  pela reatribuição real), e `test_leitura_por_chamado_postgres.py`, que roda
  os três em PostgreSQL real.

### Alterado — permissões
- **Técnico passa a administrar setores, categorias e prazos de SLA**, e a
  auditar o cadastro que administra. Antes tudo isso exigia administrador.

  | Rota | Antes | Agora |
  |---|---|---|
  | `POST`/`PUT`/`PATCH`/`DELETE` `/setores/…` | admin | admin **ou técnico** |
  | `POST`/`PUT`/`DELETE` `/categorias/…` | admin | admin **ou técnico** |
  | `PUT /sla-configs/{prioridade}` | admin | admin **ou técnico** |
  | `GET /eventos` | admin | admin, **e técnico só com `alvo=setor`** |

  **Contas de usuário continuam exclusivas do administrador**, e não é
  hierarquia: editar usuário inclui editar `role_id`, então um técnico com
  `PUT /usuarios/{id}` se promove a administrador em uma requisição. É o mesmo
  escalonamento que o passo 0 fechou por outro caminho — uma rota que parece de
  edição comum carregando o poder de mudar quem manda.

  **`GET /eventos` para técnico é limitado por `alvo`, não liberado inteiro.**
  A restrição pedida era manter `GET /usuarios/{id}/eventos` com o
  administrador, "porque ela diz quem redefiniu a senha de quem" — mas
  `GET /eventos?alvo=usuario` devolve exatamente os mesmos eventos, de todas as
  contas de uma vez. Liberar um e proteger o outro deixaria a proteção
  decorativa, com a informação saindo pela porta ao lado. A separação passou a
  ser por **tipo de alvo**, que é o que de fato distingue o sensível do resto:
  técnico vê eventos de setor, administrador vê tudo.

  Omitir `alvo` como técnico devolve só os de setor, em vez de 403: o pedido é
  legítimo, e recusá-lo obrigaria a tela a saber o perfil só para montar a
  query.

  A dependency saiu do router e foi para o handler, exceção deliberada ao
  padrão de `main.py` — dependency de router só sabe dizer "entra ou não
  entra", e aqui a decisão depende de um parâmetro da requisição.

  `/api/v1/diagnostico/` **não** entrou na liberação: enumera contas e diz
  quais estão sem senha, o que é mapa de onde entrar, não ferramenta de
  cadastro.

  24 testes em `tests/test_politica_de_perfis.py`, cada permissão com o par
  "pode" e "não pode" — uma trava verificada só pelo lado da recusa passaria
  também com uma API que recusa tudo.

- **Rotinas recorrentes passam a exigir administrador ou técnico no módulo
  inteiro.** A escrita já exigia — `POST`, `PUT` e `DELETE` estavam com
  `require_staff` desde a entrega original. O que estava aberto a qualquer
  autenticado era `POST /{id}/realizar` e as três leituras.

  **`POST /{id}/realizar` era o furo sério, e não parece um por não ser CRUD:**
  a rota não só registra quem fez, ela **avança `proxima_data`**. Qualquer
  usuário autenticado marcava "Backup semanal" como realizado e o cronograma da
  equipe pulava uma semana — sem backup nenhum ter acontecido, com a execução
  gravada em nome de quem chamou, e nada parecendo errado na tela.

  As leituras (listar, buscar, execuções) foram fechadas depois de confirmado
  que nenhuma tela lista rotinas para usuário comum. É trabalho interno da
  equipe, e o histórico de execuções diz quem fez o quê e quando.

  A divergência era a mesma dos itens acima, na direção oposta: ali a API era
  mais estrita que a interface, aqui era mais frouxa. **A segunda é a que
  importa, porque interface não é proteção.**

### Alterado — mudança de contrato
- **`DELETE /api/v1/setores/{id}` passou a EXCLUIR o setor.** Até aqui ele
  desativava, e essa era a última distância entre o que o verbo diz e o que o
  corpo faz. Quem quer o comportamento antigo usa `PATCH /{id}/desativar`.

  É a **única mudança do plano que altera o contrato de uma rota existente**, e
  por isso veio isolada no fim, depois de o frontend migrar na 1.4.2 e de estar
  confirmado que ele é o único cliente da API. Se algum consumidor tiver ficado
  para trás chamando `DELETE` esperando desativação, ele passa a apagar.

  **A trava conta TODOS os usuários vinculados, não só os ativos** — é uma
  checagem diferente da de desativação, apesar do nome parecido. A FK
  `usuarios.setor_id` não tem `ON DELETE` e não distingue conta ativa de
  inativa: um único ex-funcionário faz o banco recusar. Checar antes é o que
  transforma isso em 400 com explicação, em vez de 500 do driver.

  O contraste é proposital e ambos os lados têm teste: o ex-funcionário de um
  setor extinto **não** impede desativar (é histórico, e contá-lo tornaria todo
  setor antigo indesativável) e **impede** apagar. A mensagem do 400 aponta as
  duas saídas: mover as contas para outro setor, ou desativar em vez de apagar.

  A rota **não** desvincula contas por conta própria. Mexer no cadastro de
  pessoas como efeito colateral de apagar um setor é o tipo de coisa que
  ninguém espera de um `DELETE`.

  **A trilha sobrevive ao setor apagado**, e é aqui que a decisão do passo
  anterior deixa de ser teórica: `eventos_de_setor` não tem FK para `setores`
  justamente para que o evento de exclusão possa ser gravado na mesma transação
  que apaga o alvo. Com FK, essa transação seria impossível e a trilha perderia
  o evento mais importante que um setor pode ter. A história anterior — criação,
  renomeações, desativações — continua legível depois da exclusão, com o nome
  congelado em cada linha.

  Ação nova no vocabulário: `exclusao`, em `eventos_de_setor`. Não há
  equivalente em `eventos_de_conta`, e não deve haver: conta que sai vira
  inativa, e a trilha impede apagá-la.

  15 testes em `tests/test_exclusao_de_setor.py`.

- **Escritas em chamado da Qualidade exigem a versão (API-4b).** O PUT, o
  atendimento e as três marcas (cancelar, arquivar, desarquivar) de um chamado
  da Qualidade passam a recusar escrita sem `versao_esperada` (**428**) ou com
  uma versão que não é mais a gravada (**409**). É o controle otimista sobre
  a coluna `versao` da API-4a: quem salvou por cima de uma mudança que não viu
  recebe 409 e recarrega, em vez de apagá-la em silêncio.

  **Isto é a parte da API.** Até o frontend mandar a versão (FE-4), um cliente
  da Qualidade recebe 428 em toda escrita — por isso a Qualidade continua
  desligada (`SETOR_QUALIDADE_ID` vazio). O M-1 (ação rápida desfazendo o
  status gravado pelo atendente) e o B-1 **não estão resolvidos**: dependem do
  FE-4 enviar a versão e da matriz de concorrência da API-4c.

  | Rota (chamado da Qualidade) | Sem `versao_esperada` | Versão diferente da gravada | Versão certa |
  |---|---|---|---|
  | `PUT /api/v1/chamados/{id}` | 428 | 409 | grava, versão +1 |
  | `PATCH /{id}/atendimento` | 428 | 409 | grava, versão +1 |
  | `PATCH /{id}/cancelar`, `/arquivar`, `/desarquivar` | 428 (sem corpo também) | 409 | grava, versão +1 |

  Corpos:

  - `versao_esperada`: inteiro **≥ 1**, estrito. `0`, negativo, `true`,
    `"5"`, `5.0` e `null` explícito são **422** — `null` é corpo errado, não
    versão faltando. A versão a mandar é a `versao` da última resposta lida.
  - PUT e atendimento: o campo entra no corpo de sempre. O atendimento segue
    com `extra="forbid"`.
  - Marcas: corpo **opcional** `{"versao_esperada": N}`; campo desconhecido é
    ignorado. Sem corpo, a TI segue como sempre.

  O 409 de versão tem corpo próprio, com o código para distingui-lo dos
  outros 409 (transição, cancelado, arquivado), que não mudaram:

  ```json
  {
    "detail": "Este chamado foi alterado por outra pessoa. Atualize e tente de novo.",
    "codigo": "versao_desatualizada",
    "versao_atual": 8
  }
  ```

  O 428 é `{"detail": "Informe a versão do chamado"}`.

  **Ordem das recusas:** 401/403 do token e do perfil → 422 do corpo → 404 →
  403/503 da autorização pelo chamado (atendimento: elegível e responsável;
  cancelar: solicitante ou equipe) → **428** → **409 de versão** → recusas de
  estado (400 "já está cancelado/arquivado", 400 de responsável, 409 de
  transição). Quem não pode escrever no chamado recebe o 403 e **nunca** a
  `versao_atual`.

  **Como a conferência é feita.** Na Qualidade a linha é relida com
  `SELECT … FOR UPDATE` antes de conferir, e a escrita sai na mesma
  transação: duas escritas simultâneas com a mesma versão não passam as duas —
  a segunda espera o lock, vê a versão nova e recebe 409. Recusa (428/409) não
  executa UPDATE nenhum e não deixa a linha travada. No PUT e nas marcas da
  Qualidade, chamado e histórico passam a sair **num commit só** (antes eram
  dois), com o status anterior lido sob o lock; o atendimento já era assim.
  Nenhum webhook na Qualidade, como antes.

  **TI: sem mudança para quem não manda a versão.** Sem trava nova, sem campo
  obrigatório, histórico com o commit próprio de sempre. Se `versao_esperada`
  vier, é conferida (409 se diverge) — mas **sem lock**, então isso na TI é
  aviso de dado velho, não controle de concorrência: uma escrita que entre
  entre a conferência e o UPDATE passa.

  **Outras escritas sobem a versão sem exigi-la:** `PATCH /avaliar` (do
  solicitante) e qualquer escrita da TI. Um formulário da Qualidade aberto
  enquanto o solicitante avalia recebe 409 ao salvar — é o comportamento
  certo, e o FE-4 precisa tratá-lo recarregando. Comentário não toca na linha
  do chamado e não sobe a versão. `DELETE` apaga a linha.

  Sem migration nova: a coluna e o trigger são os da API-4a, sem alteração.
  Testes: `tests/test_versao_service.py` (função, handler, schemas),
  `tests/test_precondicao_de_versao.py` (PUT e atendimento),
  `tests/test_precondicao_de_versao_marcas.py` (marcas) e
  `tests/test_precondicao_de_versao_postgres.py` (PostgreSQL: contagem,
  recusa sem UPDATE, falha de chave estrangeira no commit desfazendo chamado e
  histórico, um caso pontual de concorrência por rota, o PUT da TI sem lock e
  a linha destravada depois de 428/409 no PUT). Os testes antigos da Qualidade passam a
  escrever com a versão lida (`tests/versao_do_cliente.py`).

- **Concorrência da API-4 validada em PostgreSQL real (API-4c).** Só testes:
  nenhuma rota, regra de SLA, permissão ou migration mudou. Duas requisições
  correm ao mesmo tempo, cada uma com a sua sessão e conexão; a ordem entre
  elas é imposta por uma pausa logo depois da conferência da versão, com a
  linha já travada, e a espera da segunda é a que o próprio PostgreSQL mostra
  em `pg_blocking_pids`. Nada sincroniza por sleep.

  Matriz executada em PostgreSQL 15.19, local e descartável
  (`tests/test_concorrencia_versao_postgres.py`, 63 testes; suíte completa no
  mesmo banco: 1043 aprovados, nenhum pulado):

  | Caso | O que se prova |
  |---|---|
  | T1 | dois PUTs com a mesma versão: um grava, o outro recebe 409 com a versão nova — com a ordem imposta e também largando juntos de uma barreira |
  | T2 | PUT com a versão de antes da resolução: 409, status e solução preservados |
  | T3 | atendimento com a versão de antes de um PUT: 409, sem webhook |
  | T4 | duas reatribuições: só a primeira vale |
  | T5 | PUT espera o lock do atendimento e recusa com a versão dele |
  | T6 | resolução concorrente inteira (status, solução, data, histórico); SLA da resposta, do GET e do cálculo direto iguais; `status_anterior` do histórico é o lido sob o lock |
  | T7 | cancelar/arquivar × atendimento nas duas ordens, desarquivar × PUT |
  | T8 | falha depois do flush: chamado e histórico desfeitos juntos, lock solto (PUT, arquivar, atendimento) |
  | T9 | PUT de vários campos com versão velha: nenhum campo gravado; a versão vem antes da validação do responsável |
  | T10 | +1 por escrita efetiva em cada rota; nada sem mudança de dado |
  | T11 | TI sem versão, sem `FOR UPDATE` e com webhook; um lock externo bloqueia a Qualidade e não a TI |
  | T12 | 428 nas cinco rotas, sem gravar |
  | T13 | 422 para versão nula, booleana, texto, zero, negativa ou fracionária; versão de outro chamado é 409 |
  | T14 | UPDATE por SQL direto sobe a versão e espera o lock da API; as duas mudanças ficam |

  E também: reatribuição × atendimento nas duas ordens (o antigo responsável
  recebe 403, sem a versão), marcas × PUT, avaliação × atendimento, transações
  que não atualizam nada (versão parada) e a versão atual fora de toda
  resposta 401/403, mesmo para quem esperou o lock.

  Cada lock (PUT, atendimento, marcas), o commit do histórico junto do
  chamado e a ordem "autorização antes da versão" do atendimento foram
  retirados, um por vez, numa cópia descartável do código: a matriz falha em
  todos os casos.

  Os testes de concorrência da API-4b deixam de depender do relógio: a TI é
  provada pela ausência de `FOR UPDATE` no SQL emitido, e a espera da
  Qualidade por `pg_blocking_pids`, e não mais pelo `lock_timeout` estourar.

  **Comportamento registrado, não alterado:** a avaliação não trava nem
  confere versão. Concorrente com uma reabertura, as duas gravam — sem perda
  de escrita, mas a nota fica num chamado já reaberto. Decidir se isso é
  aceitável fica para uma etapa própria.

  **O que isto não prova:** o M-1 e o B-1 continuam **não resolvidos** —
  dependem do FE-4 mandar a versão lida e tratar 428/409. A matriz rodou num
  PostgreSQL local, não no de homologação, e o `TestClient` não é o servidor
  de produção (uvicorn com vários workers).

### Adicionado
- **Setor de destino do chamado — primeira etapa.** Coluna nova
  `chamados.setor_destino` (`TI` | `QUALIDADE`, NOT NULL, padrão `TI`, CHECK
  `chk_setor_destino`). Não é o setor de quem abre — esse continua em
  `usuarios.setor_id`, intocado.

  | Rota | Antes | Agora |
  |---|---|---|
  | Respostas de chamado (`GET`, `POST`, `PUT`, `PATCH`) | sem o campo | **`setor_destino`** |
  | `POST /chamados` sem o campo | TI implícito | TI |
  | `POST /chamados` com `"TI"` | campo ignorado | TI |
  | `POST /chamados` com `"QUALIDADE"` | ignorado, virava TI | corpo da Qualidade (ver segunda etapa) |
  | `POST /chamados` com valor fora da lista | ignorado | **422** |
  | `GET /chamados?setor_destino=TI\|QUALIDADE` | parâmetro ignorado | filtra |
  | `GET /chamados?setor_destino=<outro>` | ignorado | **422** |
  | `PUT /chamados/{id}` com `setor_destino` | — | ignorado; o setor não muda |

  Nada muda para a TI: o frontend atual não manda o campo e recebe TI, e o
  `tecnico_responsavel_id` enviado na criação continua sendo ignorado, como
  sempre foi. Chamados existentes ficam TI pelo `DEFAULT` da coluna.

  22 testes em `tests/test_setor_destino.py`.

- **Setor de destino do chamado — segunda etapa: abertura para a Qualidade.**
  `POST /chamados` com `"setor_destino": "QUALIDADE"` passa a seguir o corpo
  `ChamadoCreateQualidade`: descrição e prioridade com as regras de hoje,
  **`tecnico_responsavel_id` obrigatório**, sem título e sem categoria. O
  título é gerado da descrição (primeira linha com ao menos 10 caracteres, ou o
  começo da descrição inteira; até 80, com "…" no corte) e a categoria fica
  nula. Mandar `titulo` ou `categoria_id` para a Qualidade é 422
  (`nao_se_aplica`), **mesmo com `null`**: o formulário dela não tem esses
  campos, e recebê-los é sinal de cliente montando o corpo errado.

  | Situação na abertura da Qualidade | Resposta |
  |---|---|
  | responsável ausente, nulo ou não inteiro; descrição ou prioridade inválida | **422** |
  | responsável inexistente | **400** `Atendente não encontrado` |
  | responsável inativo, conta de serviço ou de outro setor | **400** `Atendente não é elegível para a Qualidade` |
  | `SETOR_QUALIDADE_ID` vazio, inválido, ou setor inexistente/inativo | **503** |

  Elegível é a conta ativa, que não é conta de serviço e pertence ao setor da
  Qualidade — **com qualquer perfil**. A regra mora num lugar só,
  `app/services/qualidade_service.py`, e serve à criação e à rota nova
  `GET /chamados/atendentes-qualidade` (qualquer autenticado; só `id` e `nome`;
  503 sem configuração), para o seletor nunca oferecer quem a gravação recusa.

  Toda recusa acontece antes do INSERT. Chamado da Qualidade **não dispara o
  webhook da TI**. O histórico de abertura ganha o destino no texto, nos dois
  setores: `… | Setor de destino: TI` e
  `… | Setor de destino: Qualidade | Responsável: <nome>`.

  **A TI não muda**: o corpo dela é validado pela mesma classe `ChamadoCreate`,
  e os erros 422 conferem campo a campo com os de antes (testado). O corpo de
  criação agora é validado à mão — o FastAPI não escolhe classe pelo valor de
  um campo —, e por isso o schema dele no `/docs` é declarado à mão também
  (`oneOf` das duas classes). `ChamadoCreate` deixa de aparecer em
  `components/schemas` do OpenAPI; o frontend não gera tipos de lá.

  Atender chamado da Qualidade (status, solução, reatribuição só entre
  elegíveis) é a terceira etapa, logo abaixo. **Até o frontend estar no ar,
  `SETOR_QUALIDADE_ID` fica vazio em produção** — ver ação no deploy.

  88 testes novos em `tests/test_criacao_qualidade.py` e
  `tests/test_atendentes_qualidade.py`; em `tests/test_setor_destino.py`, os 2
  que travavam a Qualidade foram substituídos por 4 que garantem que ela nunca
  vira TI.

- **Setor de destino do chamado — terceira etapa: atendimento da Qualidade.**

  **`PATCH /chamados/{id}/atendimento`, rota nova.** O responsável atual de um
  chamado da Qualidade muda o status e registra a solução, **com qualquer
  perfil** — quem atende a Qualidade costuma ter perfil Usuario, e o `PUT`
  continua da equipe. A autorização é pelo chamado e por quem pede, relidos do
  banco a cada requisição, e **perfil não dá passe**: administrador e técnico
  só atendem por aqui se forem da Qualidade e responsáveis; fora disso, usam o
  `PUT` como sempre.

  O corpo tem só `status` (`Em Andamento`, `Aguardando` ou `Resolvido`) e
  `solucao` — obrigatória ao resolver (mínimo de 10, como no resto do sistema)
  e recusada nos outros status, até como `null`. **Qualquer outro campo é 422
  `extra_forbidden`**: a rota não muda responsável, prioridade, categoria nem
  campo administrativo, e o responsável nunca vem do corpo.

  As transições são as das ações rápidas do frontend: Aberto → Em Andamento;
  Em Andamento → Aguardando ou Resolvido; Aguardando → Em Andamento ou
  Resolvido; Resolvido ou Fechado → Em Andamento (reabrir). O `PUT` da equipe
  continua sem restrição de transição.

  | Situação no atendimento | Resposta |
  |---|---|
  | corpo inválido, campo extra, destino Aberto/Fechado, solução ausente/curta/fora de Resolvido | **422** |
  | chamado inexistente | **404** |
  | chamado da TI | **403** `Esta rota atende só chamados da Qualidade` |
  | `SETOR_QUALIDADE_ID` vazio, inválido, ou setor inexistente/inativo | **503** |
  | quem pede não é elegível (inativo, conta de serviço, outro setor) | **403** `Você não atende a Qualidade` |
  | elegível, mas o chamado está com outra pessoa | **403** `Só o responsável atual pode atender este chamado` |
  | chamado cancelado ou arquivado | **409** |
  | transição fora da tabela, inclusive para o mesmo status | **409** `Transição de X para Y não permitida` |
  | atendimento válido | **200** com o chamado (e o SLA) |

  Resolução e histórico seguem exatamente o `PUT`: `data_resolucao` e
  `tempo_resolucao_minutos` são os da primeira resolução e reabrir não os
  apaga; o histórico grava `Alteração de status` / `Status alterado de X para
  Y` com `status_anterior` e `status_novo`, que é de onde o SLA tira pausas,
  primeira resposta e resolução. **SLA e dashboards não mudam.** Diferente do
  `PUT`, chamado e histórico vão **no mesmo commit**: uma falha antes dele
  desfaz os dois (testado com falha injetada). Sem webhook.

  **Concorrência:** a rota lê o chamado com `SELECT … FOR UPDATE`, para o
  responsável anterior não conseguir atender depois de a equipe reatribuir o
  chamado. Os testes rodam em SQLite, que ignora a cláusula: eles provam que a
  consulta pede o lock e que a autorização usa o responsável atual, **não a
  disputa real entre duas transações** — ela precisa de ensaio em PostgreSQL.

  **Reatribuição pelo `PUT`, só no chamado da Qualidade.** Trocar o
  responsável passa pela mesma regra da abertura: 400 `Atendente não
  encontrado`, 400 `Atendente não é elegível para a Qualidade`, 503 sem
  configuração, e **400 `Chamado da Qualidade precisa de responsável`** para
  desatribuir. Tudo antes de gravar qualquer campo do corpo. Só a mudança é
  validada: reenviar o responsável atual — o que a edição completa do
  frontend faz em todo salvamento — passa sem revalidar, para o chamado não
  ficar ineditável quando o responsável sai da Qualidade. A reatribuição da
  Qualidade **não dispara o webhook da TI** e, como em qualquer setor, não
  grava histórico. `require_staff` não muda: a atendente com perfil Usuario
  continua sem `PUT`.

  **A TI não muda**: mesmo validador de responsável (que segue aceitando conta
  inativa, como antes — não é escopo corrigir), mesmo webhook, mesmas
  mensagens, sem depender da configuração da Qualidade. Testado.

  124 testes novos em `tests/test_atendimento_qualidade.py` e
  `tests/test_reatribuicao_qualidade.py`; fixture `chamado_qualidade` em
  `tests/conftest.py`. Sem migration e sem variável nova.

- **Versão do chamado (API-4a): a infraestrutura do controle otimista.**
  Coluna nova `chamados.versao` (`INTEGER NOT NULL DEFAULT 1`, CHECK
  `chk_chamados_versao`, `>= 1`), mantida pelo trigger
  `trigger_chamados_versao` (`BEFORE INSERT OR UPDATE`, função
  `chamados_versao()`), e exposta em toda resposta de chamado.

  **Sozinha, esta etapa não protege nada.** A conferência — `versao_esperada`,
  409 com `codigo` e `versao_atual`, 428 na Qualidade sem versão — veio na
  API-4b (ver "Alterado — mudança de contrato").

  **O que conta como mudança:** a versão sobe exatamente 1 a cada `UPDATE`
  que muda alguma coluna persistida — status, responsável, prioridade,
  solução, cancelado, arquivado, avaliação, datas de resolução, qualquer uma —,
  venha do SQLAlchemy, de SQL direto ou de uma imagem antiga da API. **Não
  contam** `updated_at` (reescrito pelo `trigger_chamados_updated_at` em todo
  `UPDATE`, até no vazio), `data_atualizacao` (reescrito pelo ORM) e a própria
  `versao`. Um `UPDATE` que não muda nada além disso não sobe; um que muda
  vários campos sobe uma vez. Comentário e histórico são outras tabelas e não
  sobem a versão do chamado.

  **A versão não vem do cliente nem do comando.** No `INSERT` é 1; no `UPDATE`
  é derivada de `OLD.versao`. `UPDATE chamados SET versao = 999` não muda
  nada. O ORM não incrementa (`server_onupdate=FetchedValue()` só faz o objeto
  reler a coluna depois do flush), e mandar `versao` no corpo do `PUT` é
  ignorado como qualquer campo desconhecido.

  | Rota | Antes | Agora |
  |---|---|---|
  | Respostas de chamado (`GET`, `POST`, `PUT`, `PATCH`) | sem o campo | **`versao`**, a já gravada |
  | Corpos de escrita | — | **sem mudança** |

  Testes: 14 de contrato em SQLite (`tests/test_versao_na_resposta.py`, onde a
  versão é sempre 1 — lá não há trigger) e 66 em **PostgreSQL real** e
  descartável (`tests/test_versao_chamados_postgres.py`: migration, estados
  parciais, reversão e trigger; `tests/test_versao_api_postgres.py`: contagem
  pelas rotas e pelo ORM, e schema e migration instalando o mesmo trigger).
  Os de PostgreSQL rodam com `CHAMADOSHS_TESTE_PG_URL` (ver `SETUP.md`) e são
  pulados sem ela; foram executados em PostgreSQL 16.2 local, não no 15 do
  Easypanel.

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
- **Migration `migrations/2026-10-26-add-setor-destino.sql`**: **backup antes**
  (`pg_dump -Fc`), e aplicar **antes** de subir a imagem — o model declara a
  coluna, e com o banco antigo todo `/api/v1/chamados` cai. Aditiva; rollback
  da imagem depois dela é seguro. Repetível: já aplicada, só avisa; em estado
  parcial (coluna sem o CHECK, tipo ou default diferente), para com erro sem
  alterar nada. Rodar como script inteiro (DBeaver: Alt+X). Termina com as
  consultas de verificação. Ainda não foi ensaiada em PostgreSQL real — fazer
  em homologação ou num banco restaurado do backup antes de produção.
- **Migration `migrations/2026-10-28-add-versao-chamados.sql`** (API-4a):
  **backup antes**, e aplicar **antes** de subir a imagem que traz a versão — o
  model declara a coluna, e com o banco antigo todo `/api/v1/chamados` cai.
  Aditiva: a API-3 (ou anterior) continua funcionando com a coluna e o trigger,
  então o rollback da imagem é seguro, e o trigger segue contando as escritas
  dela. Repetível: já aplicada, só avisa; qualquer estado parcial ou
  divergente (coluna sem trigger, função com outro corpo, trigger `AFTER`, um
  segundo trigger usando a mesma função) para com erro sem alterar nada.
  Rodar como script inteiro (DBeaver: Alt+X); termina com as consultas de
  verificação. Ensaiada só em PostgreSQL 16.2 local e descartável — repetir em
  homologação (15) antes de produção.

  **Reversão** (só se imprescindível, e só depois de a imagem no ar voltar a
  ser uma que não declara `versao`): os três `DROP` do cabeçalho do arquivo —
  trigger, função, coluna. Perde só as versões. O caminho preferido é o
  backup. Restore **só de dados** (`pg_restore --data-only`) com o trigger
  instalado zera as versões para 1; usar `--disable-triggers` nesse caso. Um
  restore completo preserva.

- **ORDEM DO DEPLOY: três migrations pendentes.**

  1. `migrations/2026-08-12-add-eventos-de-setor.sql`
  2. `migrations/2026-10-26-add-setor-destino.sql` (backup antes)
  3. `migrations/2026-10-28-add-versao-chamados.sql` (backup antes; só junto
     com a imagem da API-4a ou posterior — antes dela é inofensiva)
  4. subir a imagem
  5. apontar o healthcheck do Easypanel para `/health`

  As três são independentes entre si. A de `eventos_de_conta` já foi aplicada
  em 12/08 (ver acima). Subir a imagem sem a de setor quebra a edição de setor
  na primeira gravação, e sem a de `setor_destino` ou a de `versao` quebra o
  CRUD de chamados; os três arquivos terminam com as consultas de verificação.

- **`SETOR_QUALIDADE_ID`: deixar VAZIO (ou ausente) em produção.** Variável
  nova, opcional; sem ela a API sobe normal, a TI funciona igual e a abertura
  para a Qualidade responde 503. Só preencher — com o id conferido por
  `SELECT id, nome, ativo FROM setores WHERE nome ILIKE 'qualidade';` — depois
  que o frontend da Qualidade (abertura e atendimento) estiver no ar. Antes
  disso, um atendente com perfil Usuario receberia chamados sem tela para
  atendê-los. Valor inválido não derruba a API: desliga a Qualidade e avisa no log.

- **API-4b (versão obrigatória na Qualidade): sem migration, mas só com o
  FE-4.** A imagem não exige nada do banco além da migration da API-4a. Com a
  Qualidade desligada (`SETOR_QUALIDADE_ID` vazio, como hoje), ela é
  inofensiva para a TI: nenhuma rota da TI mudou para quem não manda a
  versão. O que ela quebra é o cliente da Qualidade que não manda a versão —
  o frontend atual (FE-3) recebe 428 em toda escrita da Qualidade. Ordem:

  1. migration da API-4a
  2. imagem da API-4b
  3. frontend que manda `versao_esperada` e trata 428/409 (FE-4)
  4. só então `SETOR_QUALIDADE_ID`

  **Réplicas mistas:** API-4a (ou 3) e API-4b no ar ao mesmo tempo não se
  protegem entre si — a antiga grava sem conferir, e o trigger conta a escrita
  dela, então a 4b passa a recusar quem leu antes. Não há corrupção, mas a
  proteção só vale com todas as réplicas na 4b. Subir uma imagem só.

  **Rollback da imagem para API-4a/API-3** é seguro para o banco (nada mudou
  nele). Mas, com o FE-4 no ar, o atendimento da 4a/3 recusa `versao_esperada`
  como campo a mais (**422**): voltar a API exige voltar o frontend junto, ou
  o atendimento da Qualidade para. PUT e marcas da 4a/3 ignoram o campo.

- **API-5 (leitura por chamado): sem migration, sem variável nova, sem
  frontend novo.** Usa só colunas que já existem. Pode subir com o frontend
  em produção ou com o FE-4; na ordem da Qualidade, entra junto da imagem da
  API-4: migrations → API (4c + 5) → FE-4 → só então `SETOR_QUALIDADE_ID`.
  **Não ligar a Qualidade sem a API-5**: sem ela, todo chamado da Qualidade
  seria legível por qualquer conta.

  Antes de subir, conferir quem perde leitura — técnico ativo sem setor:

  ```sql
  SELECT u.id, u.nome FROM usuarios u JOIN roles r ON r.id = u.role_id
  WHERE r.nome = 'Tecnico' AND u.ativo AND u.setor_id IS NULL;
  ```

  Se vier alguém que deva continuar vendo os chamados da TI, pôr o setor
  certo no cadastro antes do deploy.

  **Rollback:** voltar a imagem anterior da API, a que estava no ar. Nada no banco a desfazer:
  migrations, trigger de versão e dados ficam como estão, e o frontend não
  precisa voltar. **Mas o rollback reabre o O-1**: a leitura volta a ser de
  qualquer autenticado. É rollback funcional, não de confidencialidade — e,
  com `SETOR_QUALIDADE_ID` ligado, expõe também a Qualidade. Voltar a API-5
  com a Qualidade ligada pede desligar a Qualidade junto, ou aceitar o risco
  por escrito.

- **API-6 (escritas e segregação de setores): sem migration e sem frontend
  novo, mas com variável nova — `SETORES_TI_IDS` — que tem de estar
  configurada ANTES de a imagem subir.** Sem ela, nenhum técnico é da TI: o
  quadro da equipe fica vazio, o PUT, o arquivamento e o cancelamento de
  chamado alheio passam a dar 404, e ninguém pode ser atribuído a chamado da
  TI. O administrador não é afetado.

  1. **Diagnóstico, por operador autorizado, no banco do ambiente:**
     `psql "$DATABASE_URL" -v setores_ti='{}' -f diagnosticos/api6_setores_ti.sql`.
     Somente leitura (transação `READ ONLY`, termina em `ROLLBACK`). Lista
     setores, técnicos e seus setores, técnicos sem setor, responsáveis por
     chamado da TI e contas de serviço envolvidas. Não colar o resultado —
     tem nomes de pessoas — em chamado, documento ou commit.
  2. **Escolher os ids com quem conhece a equipe.** É decisão humana: o nome
     do setor não diz quem é da TI ("Suporte" pode ser ou não ser). Rodar de
     novo com a lista escolhida (`-v setores_ti='{1,7}'`, com os ids reais) e
     conferir as consultas 5 (chamados da TI com responsável de fora — ficam
     com ele; nada é trocado sozinho) e 8 (técnicos que passam a ler e
     alterar só pelo vínculo).
  3. **Regularizar o cadastro antes de subir** (H1): técnico ativo sem setor,
     ou em setor fora da lista, que deva continuar sendo da TI, recebe o
     setor certo. `setor_id` segue opcional no banco.
  4. **Configurar `SETORES_TI_IDS` no Easypanel** (variável de ambiente do
     back, formato `1,7`), depois subir a imagem.
  5. **Conferir:** sem o aviso `SETORES_TI_IDS` no log da subida, e o bloco
     `equipes` de `GET /api/v1/diagnostico` sem alertas de id inexistente ou
     inativo.

  Ordem da Qualidade: migrations → API (4c + 5 + 6, com `SETORES_TI_IDS`) →
  FE-4 → **decisão e correção da D13** (ou equipe da Qualidade só com perfil
  Usuário) → só então `SETOR_QUALIDADE_ID`.

  **Rollback:** voltar a imagem anterior; nada no banco a desfazer, e o
  frontend não precisa voltar. `SETORES_TI_IDS` pode ficar: a API-5 a ignora.
  **Mas o rollback reabre o que a API-6 fechou** — o técnico da Qualidade
  volta a editar, cancelar e arquivar chamado da TI recebendo o corpo, a se
  atribuir chamado da TI para lê-lo, as recusas voltam a dizer se o id existe
  e o setor, o autor sem leitura volta a editar o comentário, e técnico de
  qualquer setor volta a ser da TI. Com a Qualidade ligada, desligar
  `SETOR_QUALIDADE_ID` **antes** de voltar a imagem, ou aceitar o risco por
  escrito.

- **API-7 (administração global da TI): sem migration, sem variável nova,
  sem frontend novo — mas depende da `SETORES_TI_IDS` da API-6 configurada
  e conferida.** Sem ela, além do que a API-6 já perde, **nenhum técnico
  administra setores, categorias, SLA, tarefas recorrentes nem lê a trilha
  de setor**: só o administrador. É o comportamento seguro, não um defeito.

  1. Os mesmos passos 1–5 da API-6, acima: ids reais escolhidos por quem
     conhece a equipe, técnicos sem setor regularizados.
  2. **Conferir quem perde a administração:** todo técnico ativo fora dos
     setores da lista deixa de ver Cadastros, Tarefas Recorrentes e
     Auditoria (o diagnóstico de `diagnosticos/api6_setores_ti.sql` já lista
     os técnicos e seus setores). Quem deva continuar administrando recebe o
     setor certo antes de subir.
  3. Depois de subir: `GET /api/v1/auth/me` de um técnico da TI devolve
     `"integra_equipe_ti": true`; o bloco `equipes` do diagnóstico, sem
     alertas.

  Ordem da Qualidade: migrations → API (4c + 5 + 6 + 7, com
  `SETORES_TI_IDS`) → FE-4 → FE-5 (recomendado, para a tela não oferecer o
  que a API recusa) → só então `SETOR_QUALIDADE_ID`. Ligar a Qualidade
  continua dependendo da política de SLA dela, ainda não aprovada.

  **Rollback:** voltar a imagem da API-6; nada no banco a desfazer, e o
  frontend não precisa voltar (o campo novo do `/auth/me` só some). **Mas o
  rollback reabre a D13:** técnico de qualquer setor volta a administrar
  setores, categorias, SLA e rotinas e a ler a trilha de setor. Com a
  Qualidade ligada, avaliar desligar `SETOR_QUALIDADE_ID` **antes** de
  voltar a imagem, ou aceitar o risco por escrito.

- **API-8 (comentário interno): sem migration, sem variável nova, sem
  frontend novo — mas depende da `SETORES_TI_IDS` da API-6 configurada e
  conferida.** Sem ela, **nenhum técnico vê nem cria comentário interno**:
  só o administrador. É o comportamento seguro, não um defeito.

  1. Os passos da API-6 e da API-7, acima.
  2. Depois de subir: um técnico da TI vê os internos de um chamado que lê;
     um técnico da Qualidade, no mesmo chamado da Qualidade, só os públicos.

  **Rollback:** voltar a imagem da API-7; nada no banco a desfazer, e o
  frontend não precisa voltar. **Mas o rollback não é seguro para a
  confidencialidade:** volta a deixar o técnico da Qualidade, o de outro
  setor e o sem setor ver e criar comentário interno nos chamados que leem
  pelo perfil ou pelo vínculo. Com a Qualidade ligada, avaliar desligar
  `SETOR_QUALIDADE_ID` **antes** de voltar a imagem, ou aceitar o risco por
  escrito.

- **API-9 (responsáveis da TI): sem migration, sem variável nova — depende
  da `SETORES_TI_IDS` da API-6 configurada e conferida, e vem antes do
  FE-5 (F5-4).** Sem a lista, a rota responde vazia e nenhum técnico a
  pede: só o administrador. É o comportamento seguro, não um defeito.

  1. Os passos da API-6, da API-7 e da API-8, acima.
  2. Depois de subir: um técnico da TI recebe a lista; um técnico da
     Qualidade recebe 403; atribuir chamado da TI a uma conta desativada dá
     400.

  **Rollback:** voltar a imagem da API-8; nada no banco a desfazer. Mas o
  rollback **remove a rota** e volta a **aceitar técnico inativo** como
  novo responsável. Com o FE-5 no ar, que monta o seletor da TI com a
  rota, o rollback tem de ser coordenado: voltar o front junto, ou aceitar
  o seletor sem opções (a rota passa a responder 422).

- **API-10 (contas de serviço): sem migration, sem variável nova, sem
  frontend novo — depende da `SETORES_TI_IDS` da API-6 e vem com a API-9,
  antes do FE-5 (F5-4).**

  1. Os passos da API-6 à API-9, acima.
  2. **Antes de subir**, conferir no banco de produção (só leitura) quais
     contas são de serviço: `SELECT id, nome, role_id, setor_id, ativo FROM
     usuarios WHERE conta_de_servico;`. A de perfil Técnico num setor de
     `SETORES_TI_IDS` **perde a administração e o comentário interno**. Se
     alguma for usada por pessoas para administrar (pelo FortiPAM, por
     exemplo), decidir antes — o código não tem exceção. A de perfil
     Administrador não muda (pendência registrada).
  3. Depois de subir: a conta de serviço técnica da TI recebe
     `integra_equipe_ti: false` no `/auth/me` e 403 em
     `GET /tarefas-recorrentes/`; um técnico da TI de verdade continua.

  **Rollback:** voltar a imagem da API-9; nada no banco a desfazer, e o
  frontend não precisa voltar. **Mas o rollback reabre o defeito:** a conta
  de serviço técnica da TI volta a administrar, a ver e criar comentário
  interno e a receber `integra_equipe_ti: true` — e o FE-5 volta a mostrar a
  ela a administração. Avaliar desativar essas contas antes de voltar a
  imagem, ou aceitar o risco por escrito.

- **API-11 (menor privilégio das contas de serviço): sem migration, uma
  variável nova (`PAINEL_CONTAS_IDS`, opcional), sem frontend novo — vem
  depois da API-10. Implantação bloqueada enquanto o inventário (e, nele, o
  id real da TV) estiver pendente.**

  1. Os passos da API-6 à API-10, acima.
  2. **Antes de subir**, o inventário de
     [docs/contas-de-servico.md](docs/contas-de-servico.md), só leitura.
     **Contar os administradores humanos ativos** (`role` Administrador,
     `ativo`, `NOT conta_de_servico`): **se der zero, não subir** — a conta
     compartilhada perde a administração e ninguém mais administra pela API.
     Recuperar antes, pelo procedimento do documento (conta nominativa por
     `criar_usuario_inicial.sql`, com registro de mudança). Se der um,
     criar o segundo antes, pelo plano de migração nominativa.
  3. Saber quem usa cada conta de serviço: as administradoras perdem toda a
     administração e o comentário interno; as técnicas, a escrita de
     equipe. Pessoas que administravam por elas precisam da conta
     nominativa antes do deploy. Nenhuma conta é alterada pelo deploy.
  4. Painel de parede: o lembrete "tarefas do dia" some (e, se a TV for
     administradora de serviço, o quadro recebe 403 a cada 10 minutos em
     `GET /tarefas-recorrentes/`) até haver um FE que use
     `lembretes-do-dia`. Aceitar por escrito, ou esperar esse FE.
     **`PAINEL_CONTAS_IDS` pode ficar vazia** (o padrão: ninguém lê como
     painel). Para preenchê-la, o id da TV sai do procedimento
     "Identificar e validar a conta da TV" do documento — conta ativa, de
     serviço, confirmada por quem cuida da TV — e vai na env var da API no
     Easypanel, com reinício. Nunca os ids dos testes (70 a 79).
  5. Depois de subir, se a variável foi preenchida: `GET /api/v1/diagnostico/`
     (administrador humano) mostra `painel.painel_contas_ids.estado: "valida"`
     e o id em `autorizadas`, nenhum em `inexistentes`, `inativas` ou
     `nao_sao_de_servico`.
  6. Depois de subir: a conta de serviço administradora recebe 403
     `"Conta de serviço não executa administração"` em `GET /usuarios/{id}/eventos`
     e continua lendo `GET /chamados/`; uma conta de serviço técnica recebe
     403 `"Conta de serviço não altera chamado como equipe"` num `PUT`;
     `POST /auth/registro` com `conta_de_servico` dá 422; um administrador
     humano continua administrando.

  **Rollback:** voltar a imagem da API-10; nada no banco a desfazer, e o
  frontend não precisa voltar. **Mas o rollback reabre R1, R2 e S4:** a
  conta de serviço administradora volta a administrar tudo (senha alheia,
  perfil, exclusão de chamado sem evento), a técnica volta a alterar
  chamados como equipe, a conta compartilhada volta a contar como último
  administrador, o registro volta a descartar `conta_de_servico` calado, e
  a rota `lembretes-do-dia` sai (o FE-5 não a usa). **Só a liberação da
  TV:** esvaziar `PAINEL_CONTAS_IDS` e reiniciar tem o mesmo efeito de
  voltar à imagem anterior à S1 completa (`fea8f7e`), sem trocar imagem; a TV
  perde os lembretes. Se já houver FE usando a rota, subir e voltar os dois
  juntos.

- **Antes de ligar a Qualidade: concorrência em PostgreSQL.** A API-4b já
  prova em PostgreSQL local, um caso por rota, que a escrita da Qualidade
  espera o lock de outra transação e recusa com a versão gravada por ela, e
  que o PUT da TI não pede o lock. A matriz completa de duas sessões (API-4c,
  T1–T14 mais reatribuição × atendimento, marcas × PUT e avaliar ×
  atendimento) passou num PostgreSQL 15.19 local e descartável. Falta rodá-la
  no PostgreSQL de homologação, com a versão de lá, antes de ligar a
  Qualidade.

- **Pendência n8n, antes de ligar a Qualidade:** conferir se algum fluxo do
  n8n lê a tabela `chamados` direto do banco, em vez de só receber o webhook.
  O webhook já não dispara para a Qualidade, mas um fluxo que consulte o banco
  passaria a ver chamados da Qualidade como se fossem da TI, e precisaria do
  filtro `setor_destino = 'TI'`. Não verificado — o n8n fica fora deste
  repositório.

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
