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

| Estado | Significado | Reenvio automático |
|---|---|---|
| `pendente` | registrado, envio não concluído (ou a execução morreu no meio) | não |
| `enviado` | a Evolution API confirmou | não |
| `incerto` | o envio falhou ou a resposta se perdeu | não |
| `sem_contato` | destinatário sem contato ativo na tabela | não |

A chave é registrada como `pendente` **antes** do envio, e chave já
registrada, em qualquer estado, não é enviada de novo. Reentregar o mesmo
evento (reexecução manual, por exemplo) só alcança quem ainda não tem chave.

**Não há garantia de entrega exatamente uma vez**, e não há como tê-la:

- Se a Evolution API recebe a mensagem e a resposta se perde, não dá para
  distinguir de uma falha. O estado fica `incerto` e nada é reenviado: o
  desenho prefere **um aviso a menos a um aviso em dobro**.
- Se o POST da API não chega ao n8n, o evento não existe para o workflow. A
  API registra a falha e não repete.
- A tabela do n8n não tem restrição de unicidade: duas execuções simultâneas
  do **mesmo** evento podem as duas passar pela conferência. A API não gera
  esse caso (um POST por escrita, sem repetição); ele só existe em reenvio
  manual simultâneo.

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

- `chamadoshs_qualidade_contatos`: `usuario_id`, `telefone`, `ativo`.
- `chamadoshs_qualidade_envios`: `chave`, `id_evento`, `evento`,
  `usuario_id`, `status`, `detalhe`.

Mensagens:

- Abertura: `Novo chamado da Qualidade aguardando atribuição: {protocolo}.
  Acesse o ChamadosHS para visualizar.`
- Atribuição: `Um chamado da Qualidade foi atribuído a você: {protocolo}.
  Acesse o ChamadosHS para visualizar.`

## Ativação e rollback

1. n8n: criar as tabelas, a credencial Header Auth e o workflow; publicar.
2. API: subir a imagem com as variáveis vazias — nada muda.
3. Painel: preencher `WEBHOOK_QUALIDADE_URL` e `WEBHOOK_QUALIDADE_TOKEN` e
   reiniciar a API.

Rollback: esvaziar `WEBHOOK_QUALIDADE_URL` e reiniciar, ou despublicar o
workflow (a API registra o 404 e segue). Nenhum dos dois toca a TI.
