# Guia de Deploy - Easypanel

## Pré-requisitos

1. Conta no Easypanel configurada
2. Repositório Git (GitHub, GitLab, etc.)
3. Banco de dados PostgreSQL configurado

## Configuração no Easypanel

### 1. Criar Novo Projeto

1. Acesse o Easypanel
2. Clique em **Create Project**
3. Dê um nome: `chamadoshs-api`

### 2. Adicionar Banco de Dados PostgreSQL

1. No projeto, clique em **Add Service**
2. Selecione **PostgreSQL**
3. Configure:
   - **Name**: `chamadoshs-db`
   - **PostgreSQL Version**: 15
   - **Database Name**: `chamados_db`
   - **Username**: `postgres`
   - **Password**: [gere uma senha segura]

4. Clique em **Create**

5. Após criar, entre no serviço PostgreSQL e vá em **Console**

6. Execute o schema do banco:
   - Copie o conteúdo do arquivo `schema_chamados.sql`
   - Cole no console SQL e execute

### 3. Adicionar Aplicação FastAPI

1. No projeto, clique em **Add Service**
2. Selecione **App**
3. Configure:

#### Build Settings
- **Source**: GitHub
- **Repository**: `seu-usuario/chamadoshs-api`
- **Branch**: `main`
- **Build Type**: `Dockerfile`

#### Environment Variables

Adicione as seguintes variáveis de ambiente:

```env
DATABASE_URL=postgresql://postgres:[SUA_SENHA]@chamadoshs-db:5432/chamados_db
SECRET_KEY=[GERE UMA CHAVE SEGURA]
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
ALLOWED_ORIGINS=https://seu-frontend.com,https://app.seu-dominio.com
ENVIRONMENT=production
API_VERSION=v1
API_TITLE=ChamadosHS API
API_DESCRIPTION=API de gerenciamento de chamados de suporte técnico
```

**IMPORTANTE**: Para gerar uma SECRET_KEY segura, use:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

#### Port Configuration
- **Port**: `8000`

#### Domain (Opcional)
- Configure seu domínio customizado se desejar
- Exemplo: `api.chamadoshs.com`

#### Health Check
- **Path**: `/health`
- **Port**: `8000`

### 4. Deploy

1. Clique em **Deploy**
2. Aguarde o build e deploy
3. Verifique os logs em **Logs**

## Testando o Deploy

### 1. Health Check

```bash
curl https://seu-app.easypanel.host/health
```

Resposta esperada:
```json
{
  "status": "healthy"
}
```

### 2. Documentação

Acesse: `https://seu-app.easypanel.host/docs`

### 3. Testar Endpoint

```bash
curl https://seu-app.easypanel.host/api/v1/categorias/
```

## Configurações Adicionais

### Volumes (Opcional)

Se precisar de upload de arquivos:

1. Em **Volumes**, adicione:
   - **Mount Path**: `/app/uploads`
   - **Size**: `5GB` (ou conforme necessário)

### Scaling (Opcional)

Para alta demanda:

1. Em **Scaling**, configure:
   - **Instances**: `2` ou mais
   - **Memory**: `512MB` (mínimo) ou `1GB` (recomendado)
   - **CPU**: `0.5` (mínimo) ou `1` (recomendado)

## Estrutura de Conexão

```
Internet
   ↓
[Easypanel Load Balancer]
   ↓
[ChamadosHS API Container] ←→ [PostgreSQL Container]
   ↓
[Network Bridge]
```

## Variáveis de Ambiente - Referência Completa

| Variável | Descrição | Exemplo | Obrigatório |
|----------|-----------|---------|-------------|
| DATABASE_URL | URL de conexão do PostgreSQL | `postgresql://user:pass@host:5432/db` | ✅ Sim |
| SECRET_KEY | Chave secreta para JWT | `abc123...` | ✅ Sim |
| ALGORITHM | Algoritmo de criptografia | `HS256` | ❌ Não (padrão: HS256) |
| ACCESS_TOKEN_EXPIRE_MINUTES | Tempo de expiração do token | `30` | ❌ Não (padrão: 30) |
| ALLOWED_ORIGINS | Origens permitidas (CORS) | `https://app.com,https://web.com` | ✅ Sim |
| ENVIRONMENT | Ambiente de execução | `production` | ❌ Não (padrão: development) |
| API_VERSION | Versão da API | `v1` | ❌ Não (padrão: v1) |
| API_TITLE | Título da API | `ChamadosHS API` | ❌ Não |
| API_DESCRIPTION | Descrição da API | `API de chamados...` | ❌ Não |

## Comandos Úteis

### Ver logs em tempo real

No Easypanel, vá em **Logs** e ative **Live Logs**

### Reiniciar a aplicação

1. Vá em **Deployments**
2. Clique em **Restart**

### Rebuild da aplicação

1. Vá em **Deployments**
2. Clique em **Redeploy**

## Troubleshooting

### Erro: "Can't connect to database"

1. Verifique se o PostgreSQL está rodando
2. Verifique a `DATABASE_URL` nas variáveis de ambiente
3. Certifique-se que o host é `chamadoshs-db` (nome do serviço)

### Erro: "Module not found"

1. Verifique se o `requirements.txt` está correto
2. Force um rebuild: **Redeploy**

### Erro 500 na API

1. Verifique os logs: **Logs**
2. Verifique se todas as variáveis de ambiente estão configuradas
3. Verifique se o schema do banco foi executado

### CORS Error no Frontend

1. Adicione a origem do frontend em `ALLOWED_ORIGINS`
2. Exemplo: `ALLOWED_ORIGINS=https://meu-frontend.com`
3. Redeploy a aplicação

## Backup do Banco de Dados

### Criar backup manual

1. Acesse o serviço PostgreSQL no Easypanel
2. Vá em **Console**
3. Execute:

```bash
pg_dump -U postgres chamados_db > backup.sql
```

### Agendar backups automáticos

Configure no próprio Easypanel em **Backups**:
- **Frequency**: Daily
- **Retention**: 7 days (ou conforme necessário)

## Monitoramento

### Métricas disponíveis no Easypanel

- CPU Usage
- Memory Usage
- Network I/O
- Request Count
- Response Time

### Alertas (Configurar se necessário)

1. Vá em **Monitoring**
2. Configure alertas para:
   - CPU > 80%
   - Memory > 80%
   - Application Down

## Próximos Passos

- [ ] Configurar domínio customizado
- [ ] Configurar SSL/TLS (Let's Encrypt)
- [ ] Configurar backups automáticos
- [ ] Implementar CI/CD com GitHub Actions
- [ ] Configurar monitoramento avançado
- [ ] Implementar rate limiting
- [ ] Adicionar autenticação JWT

## Suporte

Para problemas de deploy:
- Email: ti@healthsafetytech.com
- Documentação Easypanel: https://easypanel.io/docs
