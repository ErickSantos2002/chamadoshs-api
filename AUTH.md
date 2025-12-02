# Guia de Autenticação - ChamadosHS API

## Visão Geral

A API utiliza autenticação JWT (JSON Web Tokens) com Bearer Token. O usuário faz login com seu **nome de usuário** e **senha**, recebe um token JWT que deve ser enviado no header de todas as requisições protegidas.

## Migration do Banco de Dados

Antes de usar a autenticação, execute a migration:

```sql
-- Execute no PostgreSQL
\i migrations/add_auth_fields.sql
```

Ou copie e execute o conteúdo do arquivo `migrations/add_auth_fields.sql` diretamente no banco.

## Endpoints de Autenticação

### 1. Login

**Endpoint:** `POST /api/v1/auth/login`

**Request:**
```json
{
  "nome": "joao.silva",
  "senha": "senha123"
}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": 1,
  "nome": "joao.silva",
  "role": "Tecnico"
}
```

**Erros:**
- `401 Unauthorized`: Usuário ou senha incorretos
- `403 Forbidden`: Usuário inativo

### 2. Registro

**Endpoint:** `POST /api/v1/auth/registro`

**Request:**
```json
{
  "nome": "maria.santos",
  "senha": "senha123",
  "setor_id": 2,
  "role_id": 3,
  "ativo": true
}
```

**Response (201 Created):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": 2,
  "nome": "maria.santos",
  "role": "Usuario"
}
```

**Erros:**
- `400 Bad Request`: Nome de usuário já cadastrado

### 3. Obter Usuário Logado

**Endpoint:** `GET /api/v1/auth/me`

**Headers:**
```
Authorization: Bearer {seu_token_jwt}
```

**Response (200 OK):**
```json
{
  "id": 1,
  "nome": "joao.silva",
  "setor_id": 1,
  "role_id": 2,
  "ativo": true
}
```

**Erros:**
- `401 Unauthorized`: Token inválido ou expirado

### 4. Alterar Senha

**Endpoint:** `POST /api/v1/auth/alterar-senha`

**Headers:**
```
Authorization: Bearer {seu_token_jwt}
```

**Request:**
```json
{
  "senha_atual": "senha123",
  "senha_nova": "novaSenha456"
}
```

**Response (200 OK):**
```json
{
  "message": "Senha alterada com sucesso"
}
```

**Erros:**
- `400 Bad Request`: Senha atual incorreta
- `401 Unauthorized`: Token inválido

### 5. Renovar Token

**Endpoint:** `POST /api/v1/auth/refresh`

**Headers:**
```
Authorization: Bearer {seu_token_jwt}
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user_id": 1,
  "nome": "joao.silva",
  "role": "Tecnico"
}
```

## Como Usar em Requisições

### 1. Fazer Login

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "nome": "joao.silva",
    "senha": "senha123"
  }'
```

Guarde o `access_token` retornado.

### 2. Usar o Token em Requisições Protegidas

```bash
curl -X GET "http://localhost:8000/api/v1/chamados/" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

## Proteção de Rotas

### Rotas Públicas (sem autenticação)

- `POST /api/v1/auth/login` - Login
- `POST /api/v1/auth/registro` - Registro
- `GET /` - Root
- `GET /health` - Health check

### Rotas Protegidas (requerem autenticação)

Todas as outras rotas da API requerem autenticação. Para proteger um endpoint, use a dependency `get_current_user`:

```python
from app.api.deps import get_current_user
from app.models.usuario import Usuario

@router.get("/exemplo")
def exemplo_protegido(current_user: Usuario = Depends(get_current_user)):
    return {"usuario": current_user.nome}
```

## Configuração do Token JWT

As configurações do JWT estão no arquivo `.env`:

```env
SECRET_KEY=sua_chave_secreta_aqui
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

**IMPORTANTE:**
- Gere uma `SECRET_KEY` segura: `python -c "import secrets; print(secrets.token_hex(32))"`
- Em produção, use uma chave forte e mantenha em segredo
- Tokens expiram em 30 minutos por padrão (ajuste conforme necessário)

## Fluxo de Autenticação

```
1. Cliente faz POST /api/v1/auth/login com credenciais
   ↓
2. API valida usuário e senha
   ↓
3. API gera token JWT com validade de 30 minutos
   ↓
4. Cliente recebe token e armazena (localStorage, sessionStorage, etc)
   ↓
5. Cliente envia token no header Authorization: Bearer {token}
   ↓
6. API valida token em cada requisição protegida
   ↓
7. Se token expirar, cliente faz novo login ou refresh
```

## Exemplo Frontend (JavaScript)

### Login

```javascript
async function login(nome, senha) {
  const response = await fetch('http://localhost:8000/api/v1/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ nome, senha })
  });

  if (response.ok) {
    const data = await response.json();
    // Salvar token
    localStorage.setItem('token', data.access_token);
    localStorage.setItem('user_id', data.user_id);
    localStorage.setItem('user_name', data.nome);
    return data;
  } else {
    throw new Error('Login falhou');
  }
}
```

### Fazer Requisição Autenticada

```javascript
async function getChamados() {
  const token = localStorage.getItem('token');

  const response = await fetch('http://localhost:8000/api/v1/chamados/', {
    method: 'GET',
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });

  if (response.ok) {
    return await response.json();
  } else if (response.status === 401) {
    // Token expirado, redirecionar para login
    window.location.href = '/login';
  }
}
```

### Logout

```javascript
function logout() {
  localStorage.removeItem('token');
  localStorage.removeItem('user_id');
  localStorage.removeItem('user_name');
  window.location.href = '/login';
}
```

## Criar Primeiro Usuário (Seed)

Após executar a migration, você pode criar um usuário inicial:

```sql
-- Criar usuário admin (senha: admin123)
-- Hash gerado com bcrypt
INSERT INTO usuarios (nome, senha_hash, role_id, ativo)
VALUES (
  'admin',
  '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5FS2B2c5ymNSm',
  1,
  true
);
```

Ou via API após deploy:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/registro" \
  -H "Content-Type: application/json" \
  -d '{
    "nome": "admin",
    "senha": "admin123",
    "role_id": 1,
    "ativo": true
  }'
```

## Segurança

### Boas Práticas

1. **Nunca compartilhe a SECRET_KEY**
2. **Use HTTPS em produção**
3. **Tokens expiram automaticamente** (30 minutos padrão)
4. **Senhas são hasheadas com bcrypt**
5. **Validação de token em cada requisição**
6. **Usuários inativos não podem fazer login**

### Validações

- Senha mínima: 6 caracteres
- Nome de usuário único
- Token expira automaticamente
- Verificação de usuário ativo

## Troubleshooting

### "Token inválido ou expirado"

- Token expirou (>30 minutos)
- SECRET_KEY diferente entre ambientes
- Token malformado
- **Solução:** Fazer novo login

### "Usuário ou senha incorretos"

- Credenciais erradas
- Usuário não existe
- **Solução:** Verificar credenciais

### "Usuário inativo"

- Campo `ativo` = false no banco
- **Solução:** Ativar usuário no banco ou via admin

## Próximas Implementações

- [ ] Refresh token de longa duração
- [ ] Rate limiting no login
- [ ] Bloqueio após N tentativas falhas
- [ ] Log de acessos
- [ ] 2FA (autenticação de dois fatores)
- [ ] OAuth2 (Google, Microsoft)
