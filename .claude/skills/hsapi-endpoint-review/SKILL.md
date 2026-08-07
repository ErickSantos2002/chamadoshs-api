---
name: hsapi-endpoint-review
description: Revisão de endpoints FastAPI do ChamadosHS — contrato Pydantic, status codes, autenticação, paginação, N+1 e sincronia com o front. Usar ao criar ou alterar endpoint, ou quando front e back divergem.
---

# Skill: Endpoint Review — chamadoshs-api

## Objetivo

Revisar endpoints verificando design, segurança e **consistência com o que o
front realmente consome**. Este último ponto é o que mais gera bug: os dois
repositórios evoluem separados e o contrato sai de sincronia.

## Contexto

- Routers por recurso em `app/api/endpoints/`, registrados em `main.py` sob `/api/v1/`
- Contratos em `app/schemas/` (Pydantic), models em `app/models/` (SQLAlchemy)
- Regra de negócio pesada em `app/services/` (SLA, recorrência, horas úteis)
- Consumidor único: `chamadoshs-sistema`, via `src/services/chamadoshsapi.ts`
- OpenAPI em `/openapi.json`

## O que analisar

### 1. Autenticação (bloqueante)

Todo router precisa ser registrado com `dependencies=[Depends(get_current_user)]`.
A trava em `main.py` impede a aplicação de subir se faltar — **entender o erro,
nunca contorná-lo** adicionando a rota a `ROTAS_PUBLICAS` sem justificativa.

Operação administrativa usa `require_roles(...)`.

### 2. Autoria e auditoria

Quem praticou a ação vem de `current_user`, **nunca** de `?usuario_id=` ou do
body. Em endpoint que grava histórico, isso é requisito, não preferência.

### 3. Alinhamento com o front

Ao alterar um endpoint, abrir o serviço correspondente no outro repositório:

- O tipo em `src/types/api.ts` bate campo a campo com o schema Pydantic?
- Campo `Optional[...]` no back está `?` no TS?
- As listagens devolvem **array puro**, não envelope — manter
- Não há versionamento além do `/v1`: toda alteração de campo é breaking na prática

> Precedente: `d8d24b9 fix(cadastros): alinha leitura de campos ao contrato real
> da API` no front corrigiu exatamente esse tipo de divergência.

### 4. Design e nomenclatura

- Recurso no plural: `/chamados`, `/usuarios`, `/tarefas-recorrentes` ✅
- Verbos:
  - `GET` leitura sem efeito colateral
  - `POST` criação e ação (`/tarefas-recorrentes/{id}/realizar`)
  - `PUT` substituição completa
  - `PATCH` mudança de estado pontual (`/chamados/{id}/cancelar`, `/arquivar`)
  - `DELETE` remoção
- Ação de estado como sub-recurso é o padrão do projeto — manter consistente

### 5. Status codes

| Código | Quando |
|---|---|
| `200` | sucesso com body |
| `201` | criação — `status_code=status.HTTP_201_CREATED` |
| `204` | sucesso sem body (DELETE) |
| `400` | erro de requisição |
| `401` | não autenticado |
| `403` | autenticado sem permissão |
| `404` | não encontrado |
| `409` | conflito — **já em uso**: categoria com chamados vinculados |
| `422` | validação Pydantic (automático) |

No `409`, o `detail` deve dizer **por quê** e trazer o dado que permite ao front
montar a mensagem (ex.: quantidade de vínculos).

### 6. Paginação

A listagem de chamados tem teto no `limit` (commit `2983ad5`). O front compensa
com `listarTodos()`, varrendo em lotes de 200.

- Endpoint novo que pode crescer tem `skip`/`limit`?
- O teto está documentado no schema?
- Mudar o teto quebra a varredura do front?

### 7. Performance

- **N+1**: listagem que acessa `chamado.solicitante`, `.categoria`,
  `.tecnico_responsavel` sem `joinedload`/`selectinload` dispara uma query por
  registro — com 200 por página, 600+ queries
- SLA percorre todo o histórico do chamado: verificar se está sendo calculado
  dentro de um loop de listagem
- Campo pesado (`descricao`, `solucao`) devolvido em listagem que só monta card

## Formato de resposta

```
ENDPOINT REVIEW — POST /api/v1/chamados/
========================================
✅ Autenticação: router com Depends(get_current_user)
✅ Autoria: usa current_user.id
❌ Status code: retorna 200 na criação — deveria ser 201
⚠️  Contrato: `urgencia` é Optional aqui mas obrigatório em types/api.ts
💡 Performance: sem joinedload — N+1 na listagem
🔗 Front: src/services/chamadoshsapi.ts:168 precisa mudar junto
```

## Observações

- Revisar **todos os endpoints do mesmo recurso juntos** — inconsistência entre
  irmãos é o defeito mais comum
- Toda mudança de contrato deve listar o que muda no front, arquivo e linha
- Deploy é manual: se front e back mudam juntos, informar a **ordem** de subida
