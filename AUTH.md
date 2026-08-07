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

**Endpoint:** `POST /api/v1/auth/registro` — **exige token de administrador**

O corpo aceita `role_id`, então enquanto este endpoint foi público bastava
uma requisição sem credencial nenhuma para criar uma conta Administrador.
Duplica `POST /api/v1/usuarios/`, e é mantido só por compatibilidade.

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
- `GET /` - Root
- `GET /health` - Health check (usado pelo HEALTHCHECK do Docker e pelo EasyPanel)

Essas são as únicas. Toda rota sob `/api/v1` exige token.

### Como a autenticação é aplicada

A dependency entra no `include_router`, em `main.py`, e não endpoint a
endpoint — assim a política inteira cabe numa tela e um endpoint novo já
nasce protegido:

```python
app.include_router(
    chamados.router,
    prefix="/api/v1/chamados",
    tags=["Chamados"],
    dependencies=[Depends(get_current_user)],
)
```

O `main.py` tem uma trava de inicialização que percorre as rotas registradas
e levanta `RuntimeError` se alguma rota `/api/v1` não exigir
`get_current_user`. Esquecer a proteção de um endpoint novo impede a
aplicação de subir, em vez de virar um buraco silencioso em produção. Se a
rota for pública de propósito, registre-a em `ROTAS_PUBLICAS`.

### Restrições por perfil

Perfis: `Administrador` (role_id 1), `Tecnico` (2), `Usuario` (3).

Use as dependencies de `app/api/deps.py`:

```python
from app.api.deps import require_admin, require_staff

@router.delete("/{item_id}")
def excluir(item_id: int, _admin: Usuario = Depends(require_admin)):
    ...
```

- `require_admin` — só Administrador
- `require_staff` — Administrador ou Técnico
- `require_roles("A", "B")` — fábrica, para combinações fora dessas duas
- `is_admin(u)` / `is_staff(u)` — predicados, para regras de dono-ou-admin
  dentro do handler

O perfil é lido do banco, não da claim do JWT: a claim fica congelada até o
token expirar, então rebaixar alguém só surtiria efeito na renovação.

**Administrador:** criar, editar e desativar usuários; criar, editar e
excluir setores e categorias; alterar prazos de SLA; excluir chamado;
`POST /api/v1/auth/registro`; `/api/v1/diagnostico`.

**Administrador ou Técnico:** atualizar, arquivar e desarquivar chamados;
criar, editar e excluir tarefas recorrentes; criar e enxergar comentário
interno.

**Qualquer usuário autenticado:** leitura em geral; abrir chamado; cancelar
o próprio chamado; comentar; registrar execução de tarefa recorrente.

### Contrato de erro

- **401** — token ausente, inválido ou expirado. O frontend redireciona para
  o login.
- **403** — token válido, perfil insuficiente. O frontend deve exibir erro de
  permissão e **não** redirecionar.

O `HTTPBearer` é construído com `auto_error=False` justamente por isso: no
padrão, header ausente produz 403, que o frontend interpretaria como
problema de permissão em vez de sessão expirada.

### Identidade e trilha de auditoria

O autor de qualquer ação vem sempre do token, nunca do corpo ou da query
string. Os campos `usuario_id` em chamados, comentários e execução de tarefa
recorrente estão **depreciados**: continuam sendo aceitos e ignorados, com
`logger.warning` a cada uso, apenas para o frontend atual não quebrar na
janela entre os deploys dos dois repositórios. Remover assim que o aviso
parar de aparecer nos logs.

### Documentação interativa

`/docs`, `/redoc` e `/openapi.json` só existem quando `ENVIRONMENT` é
`development`. O padrão de `ENVIRONMENT` é `production`, para que esquecer a
variável no deploy não deixe a documentação exposta.

O `/api/v1/diagnostico` continua registrado em todos os ambientes, porque
serve justamente para investigar problema de deploy, mas exige administrador.
Ressalva de bootstrap: num banco onde ninguém tem senha não há como
autenticar, e portanto não há como consultá-lo — nesse caso a verificação é
por SQL direto no banco.


## Configuração do Token JWT

As configurações do JWT estão no arquivo `.env`:

```env
SECRET_KEY=sua_chave_secreta_aqui
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
```

**IMPORTANTE:**
- Gere uma `SECRET_KEY` segura: `python -c "import secrets; print(secrets.token_hex(32))"`
- Em produção, use uma chave forte e mantenha em segredo
- Tokens expiram em 8 horas por padrão, para cobrir um turno de trabalho.
  Era 30 minutos, o que passava despercebido enquanto quase nenhuma rota
  validava o token; com a API inteira exigindo token, 30 minutos
  desconectaria o usuário no meio do expediente. Para sessão curta, use
  `POST /api/v1/auth/refresh` antes de reduzir esse valor.

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

Esse SQL é o **único** caminho para o primeiro administrador de um banco
vazio. `POST /api/v1/auth/registro` e `POST /api/v1/usuarios/` exigem um
administrador já autenticado, então não servem para o bootstrap — e não
devem ser reabertos para isso.

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
