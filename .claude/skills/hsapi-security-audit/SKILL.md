---
name: hsapi-security-audit
description: Auditoria de segurança da API ChamadosHS (FastAPI/PostgreSQL). Usar ao mexer em autenticação, registrar router novo, alterar CORS/configuração, ou quando o usuário pedir auditoria. Acionada também pela hsapi-code-review em arquivos críticos.
---

# Skill: Security Audit — chamadoshs-api

## Objetivo

Encontrar vulnerabilidades antes de irem para produção. O ChamadosHS atende
**ISO 27001** — falha de rastreabilidade aqui é achado de auditoria, não só bug.

## Contexto

- FastAPI 0.110, SQLAlchemy 2.0, Pydantic 2.5, PostgreSQL (psycopg2)
- JWT via `python-jose`, hash via `passlib[bcrypt]`
- Deploy em container Docker no **Easypanel**, manual, feito pelo usuário
- API exposta na internet em `chamadoshsapi.healthsafetytech.com`
- O n8n **recebe** webhook de saída; **não consome** a API. O front
  `chamadoshs-sistema` é o único cliente

> Não aplicar checagens de Node.js/Express/MongoDB/Vercel — não é a stack deste projeto.

## A trava de rotas (proteger acima de tudo)

O `main.py` tem uma verificação que roda na **inicialização**: percorre as rotas
`/api/v1` e levanta `RuntimeError` se alguma não exigir `get_current_user`.
Rotas públicas de propósito ficam declaradas em `ROTAS_PUBLICAS`.

Isso é a defesa mais valiosa do projeto — vale mais que qualquer teste, porque
um endpoint desprotegido **impede a aplicação de subir** em vez de virar buraco
silencioso.

Ao auditar, verificar:

- 🔴 A trava foi removida, comentada ou enfraquecida?
- 🔴 Alguma rota foi adicionada a `ROTAS_PUBLICAS` sem justificativa explícita?
      Cada entrada ali é uma decisão de segurança — exigir o porquê
- 🟠 `_exige_autenticacao` continua percorrendo dependências aninhadas?
- Router novo foi registrado com `dependencies=[Depends(get_current_user)]`?
      (se não, a app nem sobe — mas o erro precisa ser entendido, não contornado)

## Categorias de análise

### 1. Autenticação e autorização

- **Identidade vinda do cliente**: parâmetro `?usuario_id=` ou campo no body
  definindo quem praticou a ação. É falsificável — a autoria tem que sair de
  `current_user.id`. Em sistema com trilha de auditoria isso é 🔴
- **Autorização por perfil**: operação administrativa usa `require_roles(...)`?
  Esconder o botão no React não é controle de acesso
- **`SECRET_KEY`**: valor de exemplo, curto, versionado, ou igual ao do
  `docker-compose.yml` (`dev-secret-key-change-in-production`) → 🔴, quem conhece
  a chave forja qualquer token
- **Expiração**: `ACCESS_TOKEN_EXPIRE_MINUTES` (padrão 30). Existe refresh que o
  front realmente usa, ou o usuário é expulso no meio do trabalho?
- **Rate limiting** em `/auth/login` — sem isso, brute force é livre
- **Enumeração de usuário**: `/auth/login` responde diferente para "não existe" e
  "senha errada"?

### 2. Injeção

- `db.execute(text(...))` com f-string ou concatenação de input → SQL injection.
  `text()` com string literal fixa é seguro; o perigo é a interpolação
- Queries via ORM (`.filter(Model.campo == valor)`) são parametrizadas — seguras
- Nome de arquivo do usuário usado direto ao salvar anexo → path traversal

### 3. Exposição de dados

- `response_model` ausente devolve o objeto ORM inteiro — conferir se `senha_hash`
  ou campo interno vaza
- Endpoint de diagnóstico/debug acessível sem autenticação
- `/docs` e `/redoc` abertos em produção entregam o mapa completo da API
- `HTTPException(detail=str(e))` vazando stack trace ou erro do banco
- `print()` de payload com dado pessoal — fica no log do container

### 4. Configuração

- `allow_origins=["*"]` com `allow_credentials=True`
- `ALLOWED_ORIGINS` com `localhost` em produção (padrão do `config.py` é dev)
- `ENVIRONMENT=development` em produção (mesmo problema)
- **CORS não protege API** — é regra que o navegador respeita voluntariamente.
  `curl` ignora. Nunca tratar como controle de acesso

### 5. Dependências

- `pip-audit` ou `pip list --outdated` (**não** `npm audit`)
- Versões pinadas no `requirements.txt` — facilita rastrear CVE

## Verificação externa

Confirmar da perspectiva de quem está fora:

1. `GET /openapi.json` para listar a superfície
2. Chamar cada rota **sem** header `Authorization`
3. Esperado: `401` em tudo, exceto `/`, `/health` e o que estiver em `ROTAS_PUBLICAS`

Complementa a trava de inicialização: ela garante o código, isto garante o que
está **de fato no ar** — versões diferentes podem estar rodando.

## Severidade

🔴 **Crítico** — autenticação ausente, dado sensível exposto, auditoria falsificável
🟠 **Alto** — impacto real mediante encadeamento
🟡 **Médio** — configuração ruim, boa prática violada
🔵 **Informativo** — hardening

## Formato de saída

```
SECURITY AUDIT — chamadoshs-api
===============================
🔴 CRÍTICO: usuario_id na query define autoria — app/api/endpoints/chamados.py:88
   → usar current_user.id; a query permite forjar o histórico
🟠 ALTO: sem rate limiting em /auth/login
🟡 MÉDIO: /docs público em produção
🔵 INFO: WEBHOOK_URL hardcoded em app/services/webhook_service.py
```

## Observações

- **Não corrigir automaticamente** — listar, explicar, decisão do usuário
- Para cada 🔴, incluir o trecho da correção
- Nunca imprimir valor de secret, só o caminho
- **O deploy é manual**: toda correção aqui exige o usuário subir pelo Easypanel
- Se a correção afetar o contrato, o `chamadoshs-sistema` precisa mudar junto —
  dizer a ordem de subida
