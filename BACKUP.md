# Backup e recuperação — ChamadosHS

Registro de 11/11/2026. Decisão do responsável pelo projeto: manter a
proteção existente e não contratar armazenamento independente por ora.
**Trata-se de aceitação provisória de riscos, não de comprovação de
recuperação completa do servidor.**

Este arquivo é público. Não registrar aqui senhas, tokens, endereços,
identificadores de servidor, caminhos internos nem detalhes de contas.

## Estratégia atual

| Camada | Frequência | Retenção | Local | Restauração comprovada |
|---|---|---|---|---|
| Dump automático do PostgreSQL, feito pelo painel que hospeda os serviços | Diária | 30 arquivos | Disco do próprio servidor | Não |
| Imagem automática do servidor, feita pelo provedor de hospedagem | Diária | 4 pontos (2 diários + 2 semanais) | Fora do servidor, na mesma conta do provedor | Não |
| Dumps manuais | Pontuais | Preservados | Volume de dados do banco | Sim |

## Dumps manuais validados

Dois dumps manuais, no formato custom do `pg_dump` e com soma SHA-256
guardada ao lado, foram restaurados com sucesso em banco temporário em
11/11/2026:

- **Anterior à 1.8.0** (10/11/2026), tirado antes das migrations dessa
  versão.
- **Esquema da 1.8.1** (11/11/2026): 185 chamados, 13 tabelas, colunas
  `setor_destino` e `versao` presentes. As contagens do banco restaurado
  foram idênticas às da produção no momento da captura.

Não excluir nem substituir esses arquivos sem decisão do responsável.

## Restauração isolada do PostgreSQL

Uma restauração de teste nunca tem o banco de produção como destino.

1. Conferir a integridade do arquivo com `sha256sum -c`.
2. Criar um banco temporário vazio, com nome que deixe claro que é teste.
3. Antes de restaurar, conferir explicitamente o destino: o nome do banco
   no comando é o temporário, e ele está vazio.
4. Restaurar com `pg_restore --no-owner --no-privileges`, apontando para o
   banco temporário. Não usar opções que apaguem ou recriem objetos
   (`--clean`, `--create`).
5. Validar por contagem de linhas das tabelas e pela presença das colunas,
   restrições e gatilhos das migrations.
6. Remover o banco temporário e conferir que só ele foi removido.

O ideal é que o banco temporário fique em uma instância separada da
produção. Quando estiver na mesma instância, o isolamento depende só do
nome do banco de destino, e por isso a conferência do passo 3 é
obrigatória.

A função "Restaurar" do painel é destrutiva e age sobre o serviço que
estiver aberto: não usar no serviço de produção.

## Riscos de restaurar o servidor inteiro

- Sobrescreve todo o conteúdo atual e não pode ser cancelado nem
  revertido.
- Afeta todos os sistemas hospedados no mesmo servidor, não só o
  ChamadosHS.
- Perda de até cerca de 24 horas de dados.
- Nunca foi ensaiado: não há como testar sem sobrescrever a produção.
- A imagem é do disco, não um backup consistente do PostgreSQL; a
  recuperação do banco a partir dela não foi comprovada.

## Limitações conhecidas

- Os backups automáticos, tanto o dump diário do painel quanto a imagem
  do provedor, **ainda não tiveram restauração comprovada**. Só os dois
  dumps manuais foram testados.
- Servidor e backups externos dependem da mesma conta no provedor de
  hospedagem.
- Os dumps, automáticos e manuais, ficam no mesmo servidor que o banco.
- Não existe cópia em fornecedor independente.

## Recomendações futuras

- Cópia diária cifrada em armazenamento de outro fornecedor, com
  restauração ensaiada em PostgreSQL descartável.
- Variáveis de ambiente da aplicação guardadas fora do servidor, em cofre
  de senhas.
- Teste de restauração isolada a cada migration e, no mínimo, a cada
  trimestre.
- Comprovar a restauração de um dos backups automáticos diários.
- Rever esta decisão antes da renovação do servidor ou quando o volume e
  a sensibilidade dos dados aumentarem.
