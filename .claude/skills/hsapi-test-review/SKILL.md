---
name: hsapi-test-review
description: Revisa testes da API ChamadosHS com pytest e identifica cenários sem cobertura. Usar após implementar endpoint ou regra de negócio, antes de refatorar, ou ao decidir por onde começar a testar.
---

# Skill: Test Review — chamadoshs-api

## Objetivo

Analisar testes de um módulo, apontar gaps e sugerir casos ausentes — sem gerar
código a menos que solicitado.

## Estado atual ⚠️

**Não há teste automatizado neste repositório.** Não existe `pytest` no
`requirements.txt`, nem diretório `tests/` (embora o `.dockerignore` já o exclua,
antecipando um).

Enquanto não houver testes, esta skill opera em modo **"por onde começar"**.

## Stack recomendada

| Necessidade | Ferramenta |
|---|---|
| Runner | `pytest` |
| HTTP | `TestClient` do FastAPI (ou `httpx.AsyncClient`) |
| Banco | SQLite em memória, ou Postgres descartável via fixture |
| Fixtures | `pytest` fixtures para `db`, `usuario`, `chamado_com_historico` |
| Congelar tempo | `freezegun` — indispensável aqui |

> **Nunca apontar a suíte para o banco de produção.** Se a fixture não conseguir
> subir um banco isolado, o teste deve falhar — falhar é melhor que escrever em
> dado real da HS.

## Prioridade: por onde começar

Ordenado por risco × esforço:

1. **`app/services/sla_service.py`** — função pura, sem banco, com muitos casos
   de borda e regra sutil. Melhor custo-benefício do repositório
2. **`app/services/recorrencia_service.py`** — também pura, casos de borda
   óbvios (dia 31 em fevereiro, virada de ano, intervalo > 1)
3. **`app/services/horario_util.py`** — horas úteis, pausa de almoço, fim de
   semana. Alimenta o SLA, então erro aqui contamina tudo
4. **Autenticação e autorização** — cada rota com e sem token; `require_roles`
   negando perfil errado
5. **Endpoints de chamados** — CRUD e transições de status

Os três primeiros são funções puras: entrada e saída determinísticas, **zero
setup de banco**. É onde começar.

## O que analisar (quando houver testes)

### 1. Cobertura de cenários, não de linhas

Casos de borda reais deste domínio:

- Chamado sem `data_abertura`
- Prioridade **sem** config de SLA → deve devolver `None`, não "No prazo"
- Chamado cancelado → sem SLA aplicável
- `minutos_resolucao <= 0` → divisão por zero
- Chamado reaberto depois de Resolvido — o relógio usa a **última** transição
- Período em "Aguardando" cruzando fim de semana ou noite
- Tarefa mensal dia 31 caindo em fevereiro (clamp)
- Tarefa realizada com atraso — a próxima data não pode ficar no passado
- Webhook do n8n retornando 500 ou timeout → **a criação do chamado não pode falhar**

### 2. Autenticação

- Rota protegida sem token → `401`
- Token expirado → `401`
- Token válido de perfil errado → `403`
- A trava de `main.py` continua barrando rota nova desprotegida

### 3. Fuso horário ⚠️

O sistema opera em horário de Brasília (`app/utils/timezone.py`) e o container
roda em UTC. Teste que passa na máquina do dev e quebra em produção é a armadilha
mais provável aqui. Congelar o relógio sempre — teste que depende de "hoje" real
quebra sozinho com o passar do tempo, especialmente em recorrência e SLA.

### 4. Qualidade dos testes existentes

- `assert result` sem especificar o quê não prova nada
- Teste dependente de ordem de execução
- Mock que esconde o comportamento em vez de isolá-lo
- Estado compartilhado por falta de teardown

### 5. Nomenclatura

O projeto é em português — manter os nomes de teste também:

```
✅ def test_prioridade_sem_config_devolve_none()
✅ def test_tarefa_mensal_dia_31_cai_em_28_em_fevereiro()
❌ def test_sla()
```

## Formato de resposta

```
TEST REVIEW — app/services/sla_service.py
=========================================
✅ Coberto: happy path, prioridade sem config
❌ Ausente: chamado reaberto, pausa cruzando fim de semana, divisão por zero
⚠️  Frágil: usa agora_brasilia() sem congelar — quebra sozinho
💡 Sugestão: fixture de chamado com histórico de transições, reutilizável
```

Ao final, perguntar: **"Quer que eu escreva os casos ausentes?"**

## Observações

- Não reescrever teste que funciona, só o incorreto
- Se o módulo não tem teste nenhum, sugerir de 3 a 5 casos concretos — não uma
  suíte inteira de uma vez
- Ver `hsapi-refactor`: refatoração sem teste é só reorganizar o risco
