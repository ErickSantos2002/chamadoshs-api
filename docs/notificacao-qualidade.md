# Notificação da Qualidade (API-15)

Aviso por WhatsApp aos técnicos da Qualidade, por um fluxo do n8n **separado
do da TI**: outra URL, outro segredo, outro workflow. O fluxo da TI
(`WEBHOOK_TECNICO_*`, `enviar_webhook_tecnico`) não muda.

Nenhum valor real de URL, token ou telefone entra neste repositório.

## O que avisa

| Situação | Evento | Quem é avisado |
|---|---|---|
| Chamado aberto sem responsável | `chamado_aberto` | técnicos elegíveis da Qualidade, menos quem abriu |
| Chamado aberto já com responsável (corpo do cliente antigo) | `responsavel_atribuido` | o responsável, se não foi ele quem abriu |
| Atribuição feita por outra pessoa | `responsavel_atribuido` | o novo responsável |
| Redistribuição | `responsavel_atribuido` | o novo responsável, se não foi ele quem fez |
| Assumir (o técnico se atribui) | — | ninguém |
| Status, comentário, cancelamento, arquivamento | — | ninguém |

"Elegível" é a regra de `qualidade_service.eh_elegivel`: a mesma lista de
`GET /chamados/atendentes-qualidade`. Técnico novo da Qualidade passa a ser
destinatário sem mudança na API; falta só o contato dele no n8n.

Quem faz a ação nunca é avisado dela. Sem destinatário, nada é enviado.

Quem decide os destinatários é a API, a cada evento. O workflow do n8n não
tem lista fixa de pessoas e não decide quem pode atender chamado: ele recebe
os ids, procura o contato de cada um e envia. Técnico elegível sem contato
ativo na tabela do n8n não recebe mensagem, e o aviso dele fica registrado
como `sem_contato`.

Contatos cadastrados em 18/11/2026: Hyago e Gustavo. Os telefones ficam só
na tabela do n8n.

## Configuração

| Variável | Padrão | Efeito |
|---|---|---|
| `WEBHOOK_QUALIDADE_URL` | vazio | vazio desliga o envio |
| `WEBHOOK_QUALIDADE_TOKEN` | vazio | obrigatório quando há URL: sem ele nada é enviado, com erro no log |
| `WEBHOOK_QUALIDADE_HEADER` | `X-Webhook-Token` | nome do header do token |
| `WEBHOOK_TIMEOUT_SEGUNDOS` | 5 | o mesmo timeout do webhook da TI |

URL e token valem como credencial: só no painel do ambiente.

## Contrato

`POST` na URL configurada, com o token no header, corpo JSON:

```json
{
  "evento": "responsavel_atribuido",
  "id_evento": "9001:2:responsavel_atribuido",
  "setor": "QUALIDADE",
  "chamado": { "id": 9001, "protocolo": "CHAM-2026-9999", "versao": 2 },
  "responsavel_id": 902,
  "responsavel_anterior_id": null,
  "autor_id": 901,
  "destinatarios_ids": [902]
}
```

- `evento`: `chamado_aberto` ou `responsavel_atribuido`.
- `id_evento`: `<id do chamado>:<versão>:<evento>`. A versão sobe uma vez a
  cada mudança gravada no chamado, então o valor é único por escrita e o
  mesmo se o corpo for entregue de novo.
- `destinatarios_ids`: ids de `usuarios`, sem repetição, em ordem crescente,
  nunca vazio e nunca com o `autor_id`.
- `responsavel_id` é `null` em `chamado_aberto`; `responsavel_anterior_id` é
  `null` quando o chamado aguardava atribuição.
- Não há título, descrição, nome, solicitante nem telefone.

## Como a API envia

- Depois do commit da abertura ou da atribuição, e fora da requisição
  (tarefa de fundo): n8n lento ou fora do ar não atrasa nem desfaz a escrita.
- **Uma tentativa, sem repetição.** Timeout é entrega incerta — o n8n pode
  ter recebido —, e repetir poderia virar mensagem duplicada. A falha fica
  no log com o `id_evento`; URL e token nunca são registrados.
- Qualquer resposta 2xx conta como entregue; o corpo da resposta não é lido.

## Deduplicação e os limites dela

A chave de um aviso é `<id_evento>:<destinatario_id>`. O workflow mantém uma
tabela de envios com essa chave e um estado:

| Estado | Quando é gravado | Reenvio automático |
|---|---|---|
| `pendente` | ao registrar a chave, antes de procurar o contato; permanece assim se a execução morrer no meio | não |
| `enviado` | a Evolution API aceitou a mensagem | não |
| `incerto` | o envio falhou ou a resposta se perdeu | não |
| `sem_contato` | o destinatário não tem contato ativo na tabela | não |

`enviado` registra que a Evolution API aceitou a mensagem, não que o
WhatsApp a entregou ao aparelho.

A chave é registrada como `pendente` **antes** do envio, e chave já
registrada, em qualquer estado, não é enviada de novo. Reentregar o mesmo
evento (reexecução manual, por exemplo) só alcança quem ainda não tem chave.

**Não há garantia de entrega exatamente uma vez**, e não há como tê-la:

- Se a Evolution API recebe a mensagem e a resposta se perde, não dá para
  distinguir de uma falha. O estado fica `incerto` e nada é reenviado: o
  desenho prefere **um aviso a menos a um aviso em dobro**.
- Se o POST da API não chega ao n8n, o evento não existe para o workflow. A
  API registra a falha e não repete.
- A tabela do n8n não impõe unicidade à chave e não há exclusão mútua entre
  execuções: duas execuções simultâneas do **mesmo** evento podem as duas
  passar pela conferência e enviar a mensagem em dobro. A API não gera esse
  caso (um POST por escrita, sem repetição); ele só existe em reenvio manual
  simultâneo. A deduplicação foi homologada apenas em sequência; o risco da
  concorrência foi aceito provisoriamente para a implantação atual.

Recuperar um aviso `incerto` ou `pendente` é decisão humana: conferir com o
técnico, e só então apagar a linha da chave e reentregar o evento.

## Workflow no n8n

`[CHAMADOSHS] Notificação Qualidade`, sem nenhum nó em comum com o da TI:

1. **Webhook** — POST, Header Auth, responde ao receber.
2. **Evento válido?** — setor `QUALIDADE`, evento conhecido, destinatários.
3. **Um item por destinatário** — monta a chave de cada um.
4. **Já registrado?** — segue só a chave que ainda não existe.
5. **Registrar pendente** — grava a chave antes do envio.
6. **Buscar contato** — pelo `usuario_id`, só contato ativo.
7. **Enviar WhatsApp** — sem nova tentativa; a falha de um destinatário não
   interrompe o outro.
8. **Marcar enviado / incerto / sem contato** — o detalhe da falha é texto
   fixo, porque a mensagem de erro do envio pode trazer o telefone.

Tabelas (Data Tables do n8n, no projeto de quem administra o fluxo):

- `chamadoshs_qualidade_contatos`: `usuario_id` (número), `telefone`
  (texto), `ativo` (booleano). O telefone vai só com dígitos, com o código
  do país.
- `chamadoshs_qualidade_envios`: `chave`, `id_evento`, `estado`,
  `protocolo`, `detalhe_erro` (texto) e `usuario_id` (número). `estado`
  guarda um dos quatro estados acima; `detalhe_erro` só é preenchido no
  `incerto`.

As duas têm ainda as colunas que o n8n cria sozinho (identificador e datas
de criação e de atualização da linha).

Mensagens:

- Abertura: `Novo chamado da Qualidade aguardando atribuição: {protocolo}.
  Acesse o ChamadosHS para visualizar.`
- Atribuição: `Um chamado da Qualidade foi atribuído a você: {protocolo}.
  Acesse o ChamadosHS para visualizar.`

## Homologação (13 a 17/11/2026)

Feita no n8n pela URL de teste do Webhook, com eventos fictícios e o
workflow não publicado. Os números são os das execuções do n8n.

| Cenário | Execuções | Resultado |
|---|---|---|
| Webhook autenticado por Header Auth | — | aprovado: validado nas execuções de teste que percorreram o Webhook autenticado |
| Destinatário sem contato (`sem_contato`) | 115712, 115779 | aprovado |
| Falha de envio (`incerto`, sem reenvio) | 115720 | aprovado |
| Evento repetido em sequência (deduplicação) | 115781, 115782 | aprovado: pararam em "Já registrado?", sem linha nova e sem mensagem |
| Envio real a um técnico (`enviado`) | 115783 | aprovado: recebimento confirmado pelo Hyago em 17/11/2026 |
| — | 115780 | inconclusiva: só o nó Webhook rodou; sem efeito na tabela nem mensagem |

O que **não** foi homologado:

- envio individual ao Gustavo;
- envio aos dois técnicos no mesmo evento;
- eventos simultâneos com a mesma chave (concorrência);
- o POST real da API na URL de produção do Webhook.

As execuções de teste foram apagadas depois. As quatro linhas que elas
gravaram em `chamadoshs_qualidade_envios` foram mantidas.

## Segurança e retenção

Configuração do workflow da Qualidade, aplicada em 17/11/2026:

| Opção | Valor |
|---|---|
| Save failed production executions | Save |
| Save successful production executions | Do not save |
| Save manual executions | Do not save |
| Available in MCP | desativado |

Execução com sucesso não deixa registro no n8n: o que se sabe de um aviso
entregue está na tabela de envios. Teste manual também não fica salvo.

Riscos em aberto:

- A retenção global de execuções do n8n (prazo e limite da limpeza
  automática) ainda não foi verificada.
- Execução com falha fica salva e pode guardar o cabeçalho com o token e o
  telefone do destinatário, até ser apagada.
- A instalação atual não tem o recurso de ocultar dados de execução
  (Redact).
- A instância tem uma única conta, Owner, aparentemente compartilhada: quem
  entra com ela vê execuções e altera credenciais, sem trilha de autoria.
- O MCP da instância está habilitado para outros workflows.

Estas configurações reduzem a exposição; não a eliminam.

### Rotação do token

1. Gerar um segredo criptograficamente aleatório (32 bytes ou mais).
2. Guardá-lo em gerenciador de senhas.
3. Atualizar o valor na credencial Header Auth que o Webhook já usa, sem
   criar outra.
4. Pôr o mesmo valor em `WEBHOOK_QUALIDADE_TOKEN` e reiniciar a API.
5. Não registrar o segredo em Git, Markdown, logs ou conversas.

Numa rotação com a integração ativa, entre os passos 3 e 4 os dois lados
têm segredos diferentes: o n8n recusa os envios da API, e um aviso gerado
nesse intervalo pode falhar, sem nova tentativa. Fazer os dois passos em
seguida. Na ativação inicial isso não ocorre: a API ainda não envia nada,
e não há notificação da Qualidade a interromper.

Rotacionar sempre que o token puder ter sido exposto, por exemplo numa
execução com falha vista por terceiros.

## Ativação

A API já está publicada com as variáveis vazias, e as tabelas, a credencial
e o workflow já existem no n8n. Falta, cada passo com autorização própria:

1. Concluir as verificações de segurança pendentes (acima).
2. Confirmar a URL de produção do Webhook (não a de teste).
3. Publicar o workflow da Qualidade.
4. Preencher `WEBHOOK_QUALIDADE_URL` e `WEBHOOK_QUALIDADE_TOKEN` no painel
   da API.
5. Reiniciar a API, para ela ler as variáveis.
6. Conferir o `/health` e, no log do primeiro envio, que o webhook foi
   entregue e não recusado (recusa indica token diferente do n8n).
7. Acompanhar o primeiro chamado legítimo da Qualidade.
8. Confirmar com os técnicos que a mensagem chegou a quem a regra indica.

## Rollback

- Esvaziar `WEBHOOK_QUALIDADE_URL` e reiniciar a API: ela para de enviar.
- Ou despublicar o workflow: a API registra o 404 e segue.

Nenhum dos dois toca a integração da TI. Mensagem já enviada não é
desfeita, e as linhas da tabela de envios não são apagadas pelo rollback.
