---
name: hsapi-deploy-check
description: Checklist pré-deploy da API ChamadosHS para Easypanel + Docker, incluindo migrations SQL manuais e ordem de subida com o front. Usar antes de subir qualquer alteração para produção. Nunca executa o deploy.
---

# Skill: Deploy Check — chamadoshs-api

## Objetivo

Checklist completo antes de subir para produção: código, ambiente, banco,
container e rollback.

> Este projeto **não usa Vercel nem CI/CD**. A API sobe como container Docker no
> **Easypanel**, e **o deploy é sempre manual, feito pelo usuário**. Nunca
> executar deploy — apenas preparar e verificar.

## Infraestrutura

| Item | Valor |
|---|---|
| Base | `python:3.11-slim` |
| Runtime | `uvicorn main:app --host 0.0.0.0 --port 8000` |
| Porta | 8000 |
| Usuário | `appuser` não-root ✅ |
| Healthcheck | `GET /health`, no Dockerfile |
| Config | env vars em **runtime** — restart basta, sem rebuild |
| Migrations | arquivos `.sql` **aplicados à mão** |

## Sequência de verificação

### 1. Código

- [ ] Branch correto — **`main` é produção**. Verificar se a feature branch foi
      mergeada; é fácil subir de uma branch achando que é `main`
- [ ] `git status` limpo — nada não commitado que devesse subir
- [ ] A aplicação **importa e sobe** localmente (`uvicorn main:app`)
- [ ] Nenhum `print()` de debug ou dado sensível (vai para o log do container)
- [ ] Nenhum `TODO` crítico esquecido

### 2. Trava de rotas

O `main.py` levanta `RuntimeError` na inicialização se alguma rota `/api/v1`
estiver sem `get_current_user`.

- [ ] A aplicação sobe sem erro (se não subir, **é a trava** — ler a mensagem,
      não contornar)
- [ ] Nenhuma rota foi adicionada a `ROTAS_PUBLICAS` sem justificativa

### 3. Variáveis de ambiente

> Executar `hsapi-env-check` e incorporar o resultado aqui.

- [ ] `DATABASE_URL` e `SECRET_KEY` definidos no serviço do Easypanel
- [ ] `SECRET_KEY` **diferente** do valor do `docker-compose.yml`
- [ ] `ENVIRONMENT=production`
- [ ] `ALLOWED_ORIGINS` com o domínio real do front, sem `localhost`

Os dois últimos têm padrão de desenvolvimento — se esquecer, sobe errado em silêncio.

### 4. Banco de dados

> Executar `hsapi-migration-check` para cada `.sql` novo.

- [ ] Há migration para aplicar? Qual arquivo, e em que ordem?
- [ ] **Backup feito antes** — não há down migration
- [ ] Migration é idempotente (`IF NOT EXISTS`)
- [ ] Ordem correta: **migration antes** do código que depende dela

### 5. Ordem de subida (dois repositórios)

| Tipo de mudança | Ordem |
|---|---|
| Campo novo na API (aditivo) | back → front |
| Campo removido ou renomeado | front → back |
| Endpoint novo consumido pelo front | back → front |
| **Ligar/endurecer autenticação** | **front primeiro** ⚠️ |

> A última linha é específica: se o back passar a exigir token e o front não
> souber renovar a sessão, o usuário é expulso quando o token vencer. O front
> precisa estar pronto **antes**.

- [ ] A ordem foi decidida e comunicada ao usuário?
- [ ] Se o back subir primeiro, o front atual continua funcionando?

### 6. Container

- [ ] Imagem buildada do commit certo
- [ ] `/health` respondendo depois de subir
- [ ] Log do container sem exceção na inicialização
- [ ] `requirements.txt` mudou? Então a camada de dependências rebuilda — conferir
      se subiu sem erro de compilação

### 7. Verificação pós-deploy

Não há teste automatizado — esta etapa é obrigatória:

- [ ] `GET /health` → 200
- [ ] `POST /api/v1/auth/login` com usuário real → token
- [ ] `GET /api/v1/chamados/` **sem** token → **401**
- [ ] `GET /api/v1/chamados/` **com** token → 200
- [ ] Abrir chamado de teste → webhook do n8n disparou
- [ ] Se mexeu em SLA ou recorrência: conferir um registro conhecido

### 8. Rollback

- [ ] Sabe qual commit/imagem anterior restaurar?
- [ ] Se aplicou migration, o rollback do banco é o **backup** do item 4
- [ ] Alguém usando o sistema agora? Restart derruba as requisições em voo

## Formato de resposta

Para cada seção: ✅ OK · ⚠️ Atenção — [detalhe] · ❌ Bloqueante — [não suba até resolver]

## Observações

- **Nunca executar o deploy** — quem sobe é o usuário, pelo Easypanel
- Qualquer ❌ bloqueia
- Se o front mudar junto, dizer explicitamente a ordem e o motivo
