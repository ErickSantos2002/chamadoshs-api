---
name: hsapi-changelog-update
description: Gera ou atualiza o CHANGELOG.md da API ChamadosHS a partir dos commits, destacando migrations e mudanças de contrato. Usar ao fechar um conjunto de entregas. Nunca sobrescreve versões já publicadas.
---

# Skill: Changelog Update — chamadoshs-api

## Objetivo

Manter um `CHANGELOG.md` no formato [Keep a Changelog](https://keepachangelog.com),
com base nos commits do período.

## Estado atual

**Não há `CHANGELOG.md` neste repositório** e **não há tags de versão**. Na
primeira execução, criar o arquivo do zero.

Sem tags, a fonte é sempre o log por período:

```bash
git log --since="2026-01-01" --oneline
git log -20 --oneline
```

O histórico segue conventional commits (`feat`/`fix`/`docs` com escopo), o que
permite categorizar automaticamente.

## Mapeamento de commit → categoria

| Commit | Categoria |
|---|---|
| `feat(...)` | **Added** (ou **Changed** se altera comportamento existente) |
| `fix(...)` | **Fixed** |
| `fix(auth)` / correção de vulnerabilidade | **Security** |
| `feat(db)` com migration | **Added** + seção de ação no deploy |
| remoção de endpoint | **Removed** |
| `docs(...)` | normalmente não entra |

## Estrutura

```markdown
# Changelog

## [Não publicado]

## [1.1.0] - 2026-08-07

### Security
- Todos os endpoints da API passam a exigir token de autenticação
- Operações administrativas restritas por perfil

### Added
- Tarefas recorrentes: endpoints, schemas e cálculo da próxima data
- Configuração de prazos de SLA por prioridade

### Fixed
- Relógio de resolução do SLA estável sob reabertura de chamado
- Prioridade sem configuração deixa de ser tratada como "No prazo"

### ⚠️ Requer ação no deploy
- Backup do banco antes de aplicar
- Migration: `migrations/add_tarefas_recorrentes.sql`
- Subir o front **antes** do back (mudança de autenticação)
```

A seção **"Requer ação no deploy"** não faz parte do Keep a Changelog padrão.
Existe porque o deploy é manual e as migrations são aplicadas à mão — sem esse
aviso, a informação se perde entre quem escreve e quem sobe.

## Regras de escrita

- Escrever para quem **usa** o sistema (equipe de TI da HS), não para quem programou
- Evitar jargão: "Refatorou o service de SLA" → "Cálculo de SLA passa a descontar
  o tempo em Aguardando"
- Ser específico: "correção de bug" não diz nada — qual bug, qual impacto
- Manter em **português**
- Mudança de contrato deve aparecer nos changelogs dos **dois** repositórios
- Mudança de segurança merece destaque próprio, não diluída em "Fixed"

## Observações

- **Nunca sobrescrever versão já publicada** — só adicionar em `[Não publicado]`
  ou criar seção nova
- Perguntar o número da versão antes de criar uma release
