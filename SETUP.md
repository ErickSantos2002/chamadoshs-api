# Guia de Instalação e Configuração

## 1. Pré-requisitos

- Python 3.11 ou superior
- PostgreSQL 15 ou superior
- Git

## 2. Configurar o Banco de Dados

### 2.1. Criar o banco de dados

```bash
# Acesse o PostgreSQL
psql -U postgres

# Crie o banco de dados
CREATE DATABASE chamados_db;

# Saia do psql
\q
```

### 2.2. Executar o schema

```bash
psql -U postgres -d chamados_db -f schema_chamados.sql
```

Ou se preferir, conecte-se ao banco e execute o script:

```bash
psql -U postgres -d chamados_db
\i schema_chamados.sql
```

## 3. Configurar o Ambiente Python

### 3.1. Criar ambiente virtual

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 3.2. Instalar dependências

```bash
pip install -r requirements.txt
```

## 4. Configurar Variáveis de Ambiente

### 4.1. Copiar arquivo de exemplo

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

### 4.2. Editar o arquivo .env

Abra o arquivo `.env` e configure:

```env
DATABASE_URL=postgresql://postgres:sua_senha@localhost:5432/chamados_db
SECRET_KEY=sua_chave_secreta_aqui
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

**IMPORTANTE**: Gere uma SECRET_KEY segura:

```bash
# Windows (PowerShell)
python -c "import secrets; print(secrets.token_hex(32))"

# Linux/Mac
openssl rand -hex 32
```

## 5. Executar a API

### 5.1. Rodar em modo desenvolvimento

```bash
uvicorn main:app --reload --port 8000
```

### 5.2. Rodar diretamente com Python

```bash
python main.py
```

## 6. Testar a API

### 6.1. Acessar a documentação interativa

Abra seu navegador e acesse:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### 6.2. Testar endpoint de health check

```bash
curl http://localhost:8000/health
```

Resposta esperada:
```json
{
  "status": "healthy"
}
```

## 7. Exemplos de Uso

### 7.1. Listar categorias

```bash
curl http://localhost:8000/api/v1/categorias/
```

### 7.2. Criar um usuário

```bash
curl -X POST "http://localhost:8000/api/v1/usuarios/" \
  -H "Content-Type: application/json" \
  -d '{
    "nome": "João Silva",
    "setor_id": 1,
    "role_id": 3,
    "ativo": true
  }'
```

### 7.3. Criar um chamado

```bash
curl -X POST "http://localhost:8000/api/v1/chamados/" \
  -H "Content-Type: application/json" \
  -d '{
    "solicitante_id": 1,
    "categoria_id": 2,
    "titulo": "Problema com impressora",
    "descricao": "A impressora do setor não está funcionando",
    "prioridade": "Alta"
  }'
```

### 7.4. Listar todos os chamados

```bash
curl http://localhost:8000/api/v1/chamados/
```

### 7.5. Adicionar comentário a um chamado

```bash
curl -X POST "http://localhost:8000/api/v1/comentarios/" \
  -H "Content-Type: application/json" \
  -d '{
    "chamado_id": 1,
    "usuario_id": 2,
    "comentario": "Estou verificando o problema",
    "is_interno": false
  }'
```

## 8. Estrutura da API

### Endpoints Disponíveis

#### Chamados
- `GET /api/v1/chamados/` - Listar chamados
- `GET /api/v1/chamados/{id}` - Buscar chamado por ID
- `POST /api/v1/chamados/` - Criar chamado
- `PUT /api/v1/chamados/{id}` - Atualizar chamado
- `DELETE /api/v1/chamados/{id}` - Deletar chamado

#### Usuários
- `GET /api/v1/usuarios/` - Listar usuários
- `GET /api/v1/usuarios/{id}` - Buscar usuário por ID
- `POST /api/v1/usuarios/` - Criar usuário
- `PUT /api/v1/usuarios/{id}` - Atualizar usuário
- `DELETE /api/v1/usuarios/{id}` - Desativar usuário

#### Comentários
- `GET /api/v1/comentarios/chamado/{chamado_id}` - Listar comentários de um chamado
- `GET /api/v1/comentarios/{id}` - Buscar comentário por ID
- `POST /api/v1/comentarios/` - Criar comentário
- `PUT /api/v1/comentarios/{id}` - Atualizar comentário
- `DELETE /api/v1/comentarios/{id}` - Deletar comentário

#### Setores
- `GET /api/v1/setores/` - Listar setores
- `GET /api/v1/setores/{id}` - Buscar setor por ID
- `POST /api/v1/setores/` - Criar setor
- `PUT /api/v1/setores/{id}` - Atualizar setor
- `DELETE /api/v1/setores/{id}` - Desativar setor

#### Categorias
- `GET /api/v1/categorias/` - Listar categorias
- `GET /api/v1/categorias/{id}` - Buscar categoria por ID
- `POST /api/v1/categorias/` - Criar categoria
- `PUT /api/v1/categorias/{id}` - Atualizar categoria
- `DELETE /api/v1/categorias/{id}` - Desativar categoria

#### Histórico
- `GET /api/v1/historico/chamado/{chamado_id}` - Listar histórico de um chamado
- `GET /api/v1/historico/{id}` - Buscar histórico por ID

## 9. Troubleshooting

### Erro de conexão com o banco

Se você receber erro de conexão, verifique:

1. PostgreSQL está rodando
2. Credenciais corretas no `.env`
3. Banco de dados foi criado
4. Schema foi executado

### Erro de import

Se receber erro de import de módulos:

```bash
# Reinstale as dependências
pip install --upgrade -r requirements.txt
```

### Porta já em uso

Se a porta 8000 estiver em uso, use outra porta:

```bash
uvicorn main:app --reload --port 8001
```

## 10. Próximos Passos

- [ ] Implementar autenticação JWT
- [ ] Adicionar upload de anexos
- [ ] Criar endpoints de relatórios
- [ ] Implementar paginação avançada
- [ ] Adicionar testes unitários
- [ ] Configurar Docker
- [ ] Implementar WebSockets para notificações em tempo real

## 11. Suporte

Para dúvidas ou problemas:
- Email: ti@healthsafetytech.com
- Abra uma issue no repositório
