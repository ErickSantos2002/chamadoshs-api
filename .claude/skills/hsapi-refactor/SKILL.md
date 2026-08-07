---
name: hsapi-refactor
description: Propõe refatorações na API ChamadosHS (Python/FastAPI) com foco em legibilidade e manutenção. Usar em código que funciona mas é difícil de entender, ou antes de adicionar feature sobre código problemático. Nunca altera sem aprovação.
---

# Skill: Refactor — chamadoshs-api

## Objetivo

Identificar e propor melhorias estruturais sem alterar comportamento externo.
Mais fácil de ler, testar e manter — não apenas mais "elegante".

## Princípio fundamental

> Refatoração sem teste é apenas reorganizar o risco.

**Este repositório não tem nenhum teste automatizado.** Toda proposta precisa
começar reconhecendo isso e escolher uma rota:

1. **Escrever teste de caracterização antes** — obrigatório para `sla_service`,
   `recorrencia_service`, `horario_util` e qualquer coisa de autenticação. São
   funções puras, então o teste é barato (ver `hsapi-test-review`)
2. **Passos pequenos e verificáveis**, um commit por passo — aceitável para
   reorganização estrutural sem regra de negócio

Nunca propor refatoração grande e sem rede em SLA, recorrência ou autenticação.
Essas três concentram a regra sutil do sistema.

## O que analisar

### Camadas
- Regra de negócio dentro do endpoint em vez de `app/services/`
- Endpoint acessando model direto quando já existe service para aquilo
- Service importando `HTTPException` — acoplamento indevido da camada de negócio
  com a de transporte
- Query complexa repetida entre endpoints — candidata a função de repositório

### Duplicação
- Bloco de escrita de histórico/auditoria repetido entre endpoints
- Validação "existe e está ativo?" copiada em vários lugares
- Montagem do bloco de SLA repetida entre endpoints de leitura e escrita
  (há precedente: `f0f0972 fix(sla): anexar bloco sla tambem nos endpoints de escrita`)
- Tratamento de `404` idêntico repetido — candidato a dependência

### Complexidade
- Função com mais de 30 linhas fazendo mais de uma coisa
- Condicional aninhada além de 3 níveis
- Endpoint com muitos parâmetros de query — considerar objeto de filtro Pydantic
- Loop com query dentro (N+1) — quase sempre vira `joinedload` ou `IN`

### Nomenclatura
- Variável `data`, `result`, `temp`, `obj` sem contexto
- Mistura de português e inglês no mesmo escopo — o domínio é em português
- Booleano sem prefixo (`is/has/tem/pode/esta`)

### Específico deste projeto
- `datetime.now()` puro em vez de `agora_brasilia()`
- Cálculo de prazo por `timedelta` direto em vez de `horario_util`
- Model alterado sem migration correspondente
- `except Exception` genérico escondendo erro real

## Formato de resposta

```
📍 app/api/endpoints/chamados.py — atualizar_chamado (linhas 120-215)
🔍 Problema: 95 linhas misturando validação, escrita de histórico,
   cálculo de SLA e disparo de webhook
💡 Sugestão: mover para chamado_service.atualizar(), deixando o endpoint
   só com transporte e tradução de erro
⚠️  Pré-requisito: sem teste cobrindo — escrever caracterização antes
📊 Impacto: alto (arquivo alterado com frequência)
```

Ao final, perguntar: **"Por qual quer começar?"**

## Regras

- **Nunca alterar código diretamente** — propor, explicar, aguardar aprovação
- Priorizar por impacto: complexidade alta em código frequentemente alterado
- Nada por gosto estético — todo item precisa de justificativa objetiva
- Refatoração que muda schema Pydantic **muda o contrato** e afeta o
  `chamadoshs-sistema` — sinalizar sempre
- Nunca enfraquecer a trava de rotas do `main.py` em nome de simplificação
- Usar o contexto da sessão para não repropor o que já foi descartado
