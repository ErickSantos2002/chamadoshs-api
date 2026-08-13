---
name: hsapi-migration-check
description: Revisa migrations SQL da API ChamadosHS, que são aplicadas manualmente (sem Alembic). Usar ao criar ou alterar arquivo .sql, ao mudar um model SQLAlchemy, ou antes de aplicar migration em produção.
---

# Skill: Migration Check — chamadoshs-api

## Objetivo

Garantir que uma alteração de schema seja segura de aplicar em produção, num
projeto onde **não há ferramenta de migration automatizada**.

## Realidade do projeto ⚠️

O `alembic` está no `requirements.txt` mas **não está em uso**. As migrations são
arquivos `.sql` **aplicados à mão** contra o banco:

```
migrations/add_auth_fields.sql
migrations/add_sla_configs.sql
migrations/add_tarefas_recorrentes.sql
migrations/add_urgencia_field.sql
migrations/add_cancelado_arquivado_fields.sql
migrations/2026-08-10-add-conta-de-servico.sql
migrations/2026-08-12-add-eventos-de-conta.sql
migrations/2026-08-12-add-eventos-de-setor.sql
schema_chamados.sql                 (schema COMPLETO e atual — banco novo)
criar_usuario_inicial.sql

As duas primeiras `add_*` estiveram na raiz até 13/08/2026 e foram movidas para
`migrations/`. Toda migration mora lá; na raiz ficam só o schema completo e o
bootstrap, que não são incrementos.
```

**Banco novo roda só `schema_chamados.sql`; banco existente roda só o que falta
de `migrations/`.** Misturar falha: o schema já contém tudo, e parte das
migrations não é idempotente. Desde 11/08/2026 o `schema_chamados.sql` está
completo, e `tests/test_schema_sql_bate_com_os_models.py` falha se ele divergir
dos models — toda coluna nova em `app/models/` precisa entrar lá também.

Consequências que mandam nesta skill:

- **Não há rollback automático.** O "down" é restaurar backup
- **Não há controle de o-que-já-rodou.** Só a memória de quem aplicou
- Arquivos ficam em dois lugares (`migrations/` e a raiz) — inconsistente
- A ordem de aplicação não está registrada em lugar nenhum

## O que verificar

### 1. Idempotência (obrigatório)

Sem controle de versão, a migration **vai** ser rodada duas vezes em algum
momento. Ela precisa sobreviver a isso:

```sql
ALTER TABLE chamados ADD COLUMN IF NOT EXISTS urgencia VARCHAR(20);
CREATE TABLE IF NOT EXISTS tarefas_recorrentes (...);
CREATE INDEX IF NOT EXISTS idx_chamados_status ON chamados(status);
```

Sem `IF NOT EXISTS` → ⚠️ apontar e sugerir a correção.

### 2. Sincronia com o model SQLAlchemy

Toda coluna nova precisa existir nos **dois** lados:

- `app/models/*.py` — o model
- o arquivo `.sql` — o banco

Divergência causa erro em runtime, não no boot. Verificar tipo, `nullable`,
`default` e `CheckConstraint` batendo entre os dois.

### 3. Segurança do dado existente

- `ADD COLUMN NOT NULL` sem `DEFAULT` **falha** se a tabela tiver linhas
- `DROP COLUMN` é irreversível — exigir confirmação explícita
- Mudança de tipo pode truncar dado silenciosamente
- `UPDATE` sem `WHERE` — conferir duas vezes

### 4. Ordem e dependência

- A migration depende de outra que ainda não foi aplicada?
- Foreign key referenciando tabela que ainda não existe?
- O código que usa a coluna sobe **depois** da migration, nunca antes

### 5. Documentação da aplicação

Como não há registro automático, o arquivo deve dizer, em comentário no topo:

```sql
-- Migration: adiciona campos de cancelamento e arquivamento
-- Aplicar ANTES de subir a versão X do código
-- Reversão: não há; restaurar backup
```

## Sequência antes de aplicar em produção

1. [ ] **Backup do banco** — é o único rollback que existe
2. [ ] Migration é idempotente
3. [ ] Model SQLAlchemy sincronizado
4. [ ] Testada num banco de cópia primeiro
5. [ ] Ordem definida: migration → deploy do código
6. [ ] Ninguém usando o sistema no momento (ou impacto aceito)

## Formato de resposta

```
MIGRATION CHECK — migrations/add_campo_x.sql
============================================
❌ Idempotência: ALTER TABLE sem IF NOT EXISTS — quebra se rodar 2x
⚠️  Model: coluna existe no .sql mas falta em app/models/chamado.py
⚠️  Dado existente: NOT NULL sem DEFAULT falha com a tabela populada
✅ Ordem: não depende de outra migration
📋 Aplicar: backup → migration → deploy do código
```

## Observações

- **Nunca aplicar a migration** — quem executa é o usuário
- Sempre lembrar do backup, mesmo que pareça óbvio
- Se a migration for destrutiva (`DROP`, mudança de tipo), pedir confirmação
  explícita antes de sequer detalhar
- Sugerir padronizar novos arquivos em `migrations/` com prefixo de data
  (`2026-08-07-descricao.sql`) — resolve ordem e localização de uma vez
