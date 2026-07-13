# SLA de atendimento + correção do delete de categoria

**Data:** 2026-07-13
**Repos:** `chamadoshs-api` (FastAPI) e `chamadoshs-sistema` (React/TS)

## Contexto

O ChamadosHS não tem SLA. O Rickelme definiu uma tabela de prazos por prioridade e
queremos que o sistema calcule, exiba e meça o cumprimento desses prazos.

Aproveitamos a mesma leva para corrigir o botão "Excluir categoria", que hoje não
funciona da forma que o usuário espera.

## Decisões tomadas

| Questão | Decisão |
|---|---|
| Relógio do SLA | Só corre em horário comercial, para **todas** as prioridades |
| Expediente | Seg–sex, 8h–17h, com pausa 12h–13h → **8 horas úteis/dia** |
| Feriados | Ignorados nesta versão (só fim de semana é não-útil) |
| O que é "resposta" | Primeira saída do status `Aberto` (registrada no `historico_chamados`) |
| Status `Aguardando` | **Pausa** o relógio de resolução |
| Faixas da tabela | Teto da faixa, exceto Alta (ver "Empate" abaixo) |
| Alerta de "Atenção" | Percentual: **≥80%** do prazo consumido |
| Prazos configuráveis | Sim, editáveis por admin em Cadastros Básicos |
| Alertas por webhook | **Fora de escopo** nesta versão |

### Tabela de prazos (em minutos úteis)

| Prioridade | Resposta | Resolução |
|---|---|---|
| Baixa | 480 (8h úteis) | 1440 (3 dias úteis) |
| Média | 240 (4h) | 480 (1 dia útil) |
| Alta | 60 (1h) | 240 (4h) |
| Crítica | 15 | 120 (2h) |

**Empate resolvido:** com expediente de 8h/dia, "1 dia útil" (Média) e o teto de "4 a 8h"
(Alta) davam ambos 480 min, tornando Média e Alta indistinguíveis na resolução. Adotamos o
piso da faixa da Alta (4h = 240 min), preservando a escala: Baixa > Média > Alta > Crítica.

## Arquitetura

**SLA é derivado, não armazenado.** Nenhuma coluna nova em `chamados`. O backend calcula a
situação do SLA no momento da resposta, a partir de `data_abertura` + as transições já
gravadas em `historico_chamados`, e devolve campos prontos no `ChamadoResponse`.

Consequências:
- Chamados antigos já nascem com SLA calculado — sem migração nem backfill.
- Editar os prazos na tela **recalcula** o SLA dos chamados antigos (a régua muda para todos).
  Aceito conscientemente: é um sistema interno e corrigir a régua deve valer para o histórico.
- Custo: a listagem faz 2 queries (chamados + histórico deles), agrupadas em memória.

### Componentes

**Backend**

1. `app/services/sla_service.py` — o motor. Duas funções puras:
   - `somar_minutos_uteis(inicio: datetime, minutos: int) -> datetime` — devolve o prazo final.
   - `contar_minutos_uteis(inicio: datetime, fim: datetime) -> int` — consumo entre duas datas.

   São o coração da feature e onde mora o risco (virada de dia, fim de semana, chamado aberto
   16h50, chamado aberto dentro do almoço, chamado aberto no domingo).

2. `app/models/sla_config.py` + tabela `sla_configs` — uma linha por prioridade:
   `prioridade` (PK), `minutos_resposta`, `minutos_resolucao`. Semeada via migração com a
   tabela acima.

3. `app/api/endpoints/sla_configs.py` — `GET /` e `PUT /{prioridade}` (só admin).

4. `ChamadoResponse` ganha um bloco `sla`:
   ```
   sla: {
     prazo_resposta: datetime | null,
     prazo_resolucao: datetime | null,
     minutos_resposta_consumidos: int,
     minutos_resolucao_consumidos: int,
     percentual_resolucao: int,        # 0..100+ (pode passar de 100)
     situacao: "No prazo" | "Atenção" | "Estourado",
     resposta_cumprida: bool
   }
   ```

**Cálculo da situação**

- Relógio de resposta: de `data_abertura` até a primeira saída de `Aberto`; se ainda está
  `Aberto`, até agora.
- Relógio de resolução: de `data_abertura` até `data_resolucao`; se não resolvido, até agora.
  Descontam-se os períodos em `Aguardando`, reconstruídos do `historico_chamados`.
- `situacao`: `Estourado` se consumido > prazo; `Atenção` se ≥80% do prazo; senão `No prazo`.
  **`situacao` refere-se ao relógio de resolução.** Um chamado que furou o prazo de resposta
  mas ainda está dentro do de resolução aparece como `No prazo`, com `resposta_cumprida: false`
  — são dois indicadores independentes, e o badge mostra o de resolução.
- Chamados `Resolvido`/`Fechado` congelam a situação no momento da resolução.

**Frontend**

5. Badge de SLA nos cards da página de Chamados e no `ChamadoDetalhes` — verde (No prazo),
   amarelo (Atenção), vermelho (Estourado), com o prazo em tooltip.
6. Bloco no Dashboard, em cima dos chamados que a listagem já carrega (agora paginada por
   completo). Três números, com denominadores explícitos:
   - **% dentro do SLA**: chamados *já resolvidos* que fecharam dentro do prazo ÷ total de
     chamados resolvidos. Mede desempenho passado.
   - **Estourados em aberto**: chamados *não resolvidos* cuja `situacao` é `Estourado`.
     Mede a dor de agora.
   - Quebra por prioridade das duas métricas acima.
7. Nova aba "SLA" em Cadastros Básicos, no molde de `CategoriasTab.tsx`, para editar os prazos.

## Correção: delete de categoria

**Causa raiz:** `DELETE /categorias/{id}` faz soft delete (`ativo = false`), mas
`CadastrosContext.fetchData` carrega a lista sem o filtro `ativo`, então a API devolve a
categoria desativada de volta. A linha some na hora (estado local) e reaparece no reload.
O frontend já trata um 400 "categoria com chamados vinculados" que o backend nunca emite —
sinal de que o delete real era a intenção original.

**Correção:** `DELETE /categorias/{id}` passa a apagar de verdade quando a categoria não tem
chamados vinculados. Se tiver, devolve **400** com `"Não é possível excluir categoria com N
chamados vinculados"` — mensagem que o frontend já sabe exibir. Nenhuma mudança de frontend
é necessária além de exibir o erro (já implementado).

## Fora de escopo

- Alertas/webhook de SLA prestes a estourar.
- Feriados (nacionais ou municipais).
- SLA por categoria ou por cliente — só por prioridade.
- Congelar o prazo no momento da abertura (ver "Arquitetura").

## Verificação

Não há infraestrutura de testes nos repos e o Erick optou por não introduzir pytest agora.
No lugar disso:

- O motor de horas úteis será exercitado por um script descartável cobrindo as bordas
  (abertura 16h50, sexta 16h, sábado, domingo, dentro do almoço, prazo que cruza vários dias),
  com a tabela de resultados conferida antes de seguir.
- A stack sobe local via Docker em portas alternativas (8001/5433) para não conflitar com o
  TaskHS, que ocupa a 8000.
- O delete de categoria é verificado nos dois caminhos: categoria sem chamados (apaga) e
  categoria com chamados (400 + mensagem).
