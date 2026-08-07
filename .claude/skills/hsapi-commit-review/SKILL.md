---
name: hsapi-commit-review
description: Revisa um commit da API ChamadosHS antes de finalizar — conventional commits em português, escopo coeso, migration acompanhando o model e arquivos indevidos. Usar antes de git commit ou push.
---

# Skill: Commit Review — chamadoshs-api

## Objetivo

Revisar um commit antes de finalizar: mensagem clara, escopo coeso, nenhum
arquivo indevido, e nada que quebre o repositório irmão.

## Convenção do projeto

**Conventional commits com descrição em português.** Exemplos reais:

```
fix(auth): exige token em todos os routers e fecha /registro e /diagnostico
feat(auth): restringe operações administrativas por perfil
fix(sla): relogio de resolucao estavel sob reabertura, e cancelado sem SLA
feat(db): tabelas de tarefas recorrentes (migração SQL + models)
fix(chamados): teto no limit da listagem
```

Regras derivadas do histórico:

- **Tipos em uso**: `feat`, `fix`, `docs`
- **Escopos em uso**: `auth`, `sla`, `api`, `db`, `schemas`, `service`,
  `chamados`, `categorias`, `deploy`
- **Descrição em português, minúscula, sem ponto final**
- Descreve **o efeito**, não o arquivo mexido
- Commits do projeto são granulares por camada (`feat(schemas)`, `feat(service)`,
  `feat(api)` separados) — manter esse padrão em vez de um commit gigante

> ⚠️ Não sugerir imperativo em inglês ("Add", "Fix", "Update") — contraria a
> convenção adotada.

## O que analisar

### 1. Mensagem

- Segue `tipo(escopo): descrição em português`?
- O escopo bate com a camada realmente alterada?
- A descrição diz o efeito, e não "mexi no arquivo X"?
- Subject com no máximo ~72 caracteres
- Mudança de regra de negócio tem corpo explicando o **porquê**?

Apontar: mensagem vaga ("ajustes", "wip"), tipo errado (`feat` para bug fix),
escopo que não existe no projeto.

### 2. Escopo das mudanças

- O commit faz **uma coisa só**?
- Arquivo indevido: `.env`, `__pycache__/`, `.venv/`, `*.log`, `*.db`
  ⚠️ o `.gitignore` cobre `venv/` mas **não** `.venv/` — conferir manualmente
- `print()` de debug esquecido
- O diff é proporcional à mensagem?

### 3. Coerência estrutural

- **Mudou um model?** A migration `.sql` correspondente está no mesmo commit ou
  num commit imediatamente anterior? Model sem SQL quebra em runtime
- **Mudou um schema Pydantic?** O contrato mudou — o front pode precisar de
  commit correspondente em `chamadoshs-sistema`
- **Endpoint novo?** Foi registrado com `dependencies=[Depends(get_current_user)]`?
  Sem isso a aplicação nem sobe (trava do `main.py`)
- Regra de negócio nova está em `app/services/`, não dentro do endpoint?

### 4. Sinalização

- Breaking change de contrato sinalizada?
- Migration destacada — ela precisa ser aplicada à mão antes do deploy

## Formato da resposta

```
✅ Mensagem: aprovada
📦 Escopo: coeso — só autenticação
🔍 Arquivos: ⚠️ .venv/ aparece no staged — remover e adicionar ao .gitignore
🗄️  Migration: model alterado sem .sql correspondente
🔗 Repo irmão: contrato mudou, chamadoshs-sistema precisa de commit junto
💬 Sugestão: fix(auth): exige perfil administrador para excluir usuário
```

## Observações

- **Nunca executar o commit** — a decisão é do usuário
- Se o commit tiver múltiplas responsabilidades, sugerir como dividir
- Tom objetivo: agilizar, não bloquear
