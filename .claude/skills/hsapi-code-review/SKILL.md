---
name: hsapi-code-review
description: Revisão de código Python/FastAPI da API ChamadosHS. Usar ao revisar arquivo, função ou alteração antes de commitar. Delega para hsapi-security-audit, hsapi-endpoint-review e hsapi-migration-check conforme o tipo de arquivo.
---

# Skill: Code Review — chamadoshs-api

## Objetivo

Revisão detalhada e contextualizada, aproveitando o histórico da sessão para não
repetir sugestão já discutida nem contrariar decisão já tomada.

## Contexto

Python 3.11 · FastAPI 0.110 · SQLAlchemy 2.0 · Pydantic 2.5 · PostgreSQL

```
app/
├── api/endpoints/   entrada HTTP
├── api/deps.py      get_db, get_current_user, require_roles
├── schemas/         contratos Pydantic
├── models/          tabelas SQLAlchemy
├── services/        regra de negócio (sla, recorrencia, horario_util, webhook)
├── core/            config, database, security
└── utils/timezone.py
```

Convenções: código, comentários, commits e domínio em **português**. Deploy
manual pelo usuário via Easypanel — nada sobe sozinho.

## Delegação por tipo de arquivo

| Arquivo | Delegar para |
|---|---|
| `app/api/endpoints/*.py` | `hsapi-endpoint-review` |
| `main.py`, `deps.py`, `security.py`, `config.py`, `auth.py` | `hsapi-security-audit` |
| `migrations/*.sql`, `*.sql` na raiz | `hsapi-migration-check` |
| `.env*`, `Dockerfile`, `docker-compose.yml` | `hsapi-env-check` |
| arquivo de teste | `hsapi-test-review` |

Incorporar o resultado na seção correspondente em vez de duplicar a análise.

## Categorias de análise

**Qualidade**
- O código faz o que se propõe?
- Lógica duplicada que caberia extrair para `app/services/`?
- Nomes comunicam intenção? Domínio em português (`chamado`, `solicitante`,
  `tarefa recorrente`) — evitar mistura com inglês no mesmo escopo

**Banco e sessão**
- Sessão obtida fora do `Depends(get_db)`
- `commit()` sem `rollback()` no caminho de erro
- N+1 query em listagem — falta `joinedload`/`selectinload`
- Query dentro de loop que poderia ser um `IN`
- Alteração de model **sem** o `.sql` correspondente (não há Alembic em uso)

**Datas e fuso** ⚠️
- Usar `agora_brasilia()` de `app/utils/timezone.py`, **nunca** `datetime.now()`
  puro — o sistema opera em horário de Brasília e o container roda em UTC
- Cálculo de prazo deve passar por `app/services/horario_util.py` (horas úteis),
  não por subtração direta de `timedelta`

**Erros**
- `except Exception: pass` engolindo erro real
- `HTTPException(detail=str(e))` vazando detalhe interno
- Falha de integração externa (webhook n8n) derrubando a operação principal —
  o webhook precisa falhar em silêncio, como já faz em `webhook_service.py`

**Contrato**
- `response_model` ausente devolve o objeto ORM inteiro
- Schema de resposta expondo campo interno ou `senha_hash`
- Mudança de schema sem verificar `src/types/api.ts` no front

**Segurança**
- Ver delegação. Nunca aprovar endpoint novo sem verificar autenticação e autoria

**Manutenibilidade**
- Regra de negócio no endpoint em vez de em `app/services/`
- Está testável? (ver `hsapi-test-review`)

## Formato da resposta

1. **Resumo geral** — 1 a 2 linhas
2. **Pontos críticos** — precisa corrigir
3. **Sugestões** — recomendado, não obrigatório
4. **Positivos** — o que está bem feito (não pular)

## Observações

- Direto, mas construtivo
- Sempre incluir exemplo de correção quando aplicável
- Alteração aqui **exige deploy manual do usuário** — e se o front muda junto,
  dizer a ordem
- Não introduzir dependência nova sem necessidade real
