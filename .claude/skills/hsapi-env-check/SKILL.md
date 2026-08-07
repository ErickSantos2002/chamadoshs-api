---
name: hsapi-env-check
description: Verifica variáveis de ambiente da API ChamadosHS (pydantic-settings) e a configuração do container no Easypanel. Usar antes de deploy, ao alterar config.py, ou quando a API sobe apontando para o ambiente errado.
---

# Skill: Env Check — chamadoshs-api

## Objetivo

Garantir que as variáveis estejam corretas em cada ambiente, sem valor de
desenvolvimento vazando para produção e sem segredo exposto.

> Não usar checagens de `NODE_ENV` — este projeto usa `ENVIRONMENT`, lido por
> `pydantic-settings` em `app/core/config.py`.

## Mapa de variáveis

| Variável | Obrigatória | Padrão | Risco do padrão |
|---|---|---|---|
| `DATABASE_URL` | ✅ sim | — | app não sobe sem |
| `SECRET_KEY` | ✅ sim | — | app não sobe sem |
| `ALGORITHM` | não | `HS256` | ok |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | não | `30` | ok |
| `ALLOWED_ORIGINS` | não | `http://localhost:5173` | ⚠️ **dev** |
| `ENVIRONMENT` | não | `development` | ⚠️ **dev** |

As duas últimas são o risco silencioso: **se não forem definidas no Easypanel, a
API sobe com valor de desenvolvimento e ninguém percebe.** As duas obrigatórias
pelo menos falham alto.

## O que verificar

### 1. `SECRET_KEY` 🔴

- É o valor de exemplo (`sua-chave-secreta-aqui-use-openssl-rand-hex-32`)?
- É o do `docker-compose.yml` (`dev-secret-key-change-in-production`)?
- Está versionada em algum arquivo commitado?

Qualquer um dos três é crítico: quem conhece a chave **forja qualquer token** e
se passa por qualquer usuário, inclusive administrador.

Gerar com `openssl rand -hex 32`. Trocar a chave **invalida todas as sessões
ativas** — avisar antes.

### 2. Vazamento de ambiente

- `ENVIRONMENT=development` em produção → ❌
- `ALLOWED_ORIGINS` com `localhost` em produção → ❌
- `DATABASE_URL` de produção usado em desenvolvimento → ❌ risco de escrever em
  dado real

### 3. Runtime vs build

Diferente do front, aqui as variáveis são lidas **em runtime**. Mudar no
Easypanel + restart do container basta — **não precisa rebuild**.

(No front é o oposto: `VITE_*` é embutido no bundle e exige rebuild. Se a dúvida
for sobre o front, usar `hsweb-env-check` no outro repositório.)

### 4. Secrets no código

- Chave, token ou connection string hardcoded fora de variável
- `WEBHOOK_URL` está fixo em `app/services/webhook_service.py` — não é segredo
  forte, mas é configuração que deveria ser variável de ambiente 🔵

### 5. Consistência com `.env.example`

- Variável usada no código e ausente do `.env.example` → ⚠️ não documentada
- Variável no `.env.example` e nunca usada → ℹ️ pode remover

### 6. Higiene do repositório

- `.env` está no `.gitignore` e no `.dockerignore`? (hoje: **sim, nos dois** ✅)
- ⚠️ O `.gitignore` cobre `venv/` mas **não** `.venv/` — ambiente virtual com
  ponto aparece como untracked e pode ser commitado por acidente

## Formato de saída

```
ENV CHECK — chamadoshs-api
==========================
✅ Presença: DATABASE_URL e SECRET_KEY definidas
🔴 Secret: SECRET_KEY igual ao valor do docker-compose
❌ Vazamento: ENVIRONMENT=development na imagem de produção
⚠️  Git: .venv/ não está no .gitignore (só venv/)
🔵 Config: WEBHOOK_URL hardcoded — considerar variável
```

## Observações

- **Nunca logar o valor** de uma variável, só presença/ausência
- Ao reportar secret exposto, citar caminho e linha, nunca o valor
- Deploy é manual: mudança de variável exige o usuário aplicar no Easypanel e
  reiniciar o container
