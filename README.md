# 🎫 ChamadosHS

Sistema de gerenciamento de chamados de suporte técnico desenvolvido para atender requisitos da ISO 27001.

## 📋 Sobre o Projeto

Sistema interno para registro, acompanhamento e resolução de chamados de suporte, com foco em simplicidade, rastreabilidade e conformidade com ISO 27001.

### Características Principais

- ✅ Abertura de chamados de forma simples e rápida
- ✅ Gestão de prioridades e categorias
- ✅ Atribuição automática de técnicos
- ✅ Histórico completo de ações (auditoria)
- ✅ Sistema de comentários para comunicação
- ✅ Anexos de arquivos
- ✅ Relatórios e dashboards
- ✅ Rastreabilidade completa para ISO 27001

## 🛠️ Tecnologias

### Backend
- **FastAPI** - Framework Python para API REST
- **PostgreSQL** - Banco de dados relacional
- **SQLAlchemy** - ORM para Python
- **Pydantic** - Validação de dados

### Frontend
- **React** - Biblioteca JavaScript para interface
- **TypeScript** - Superset tipado do JavaScript
- **Tailwind CSS** - Framework CSS utilitário
- **React Query** - Gerenciamento de estado e cache

### Infraestrutura
- **Docker** - Containerização
- **Easypanel** - Orquestração de containers
- **n8n** - Automação de workflows (notificações)

## 📊 Estrutura do Banco de Dados

### Tabelas Principais

#### `usuarios`
Usuários do sistema (solicitantes e técnicos)
- `id`, `nome`, `setor_id`, `role_id`, `ativo`

#### `chamados`
Registro de todos os chamados
- `id`, `protocolo`, `solicitante_id`, `categoria_id`, `titulo`, `descricao`
- `prioridade`, `status`, `tecnico_responsavel_id`, `solucao`
- `data_abertura`, `data_resolucao`, `tempo_resolucao_minutos`

#### `comentarios_chamados`
Comentários e conversas nos chamados
- `id`, `chamado_id`, `usuario_id`, `comentario`, `is_interno`

#### `historico_chamados`
Histórico de alterações para auditoria
- `id`, `chamado_id`, `usuario_id`, `acao`, `status_anterior`, `status_novo`

#### Tabelas Auxiliares
- `setores` - Setores da empresa
- `roles` - Perfis de acesso (Administrador, Tecnico, Usuario)
- `categorias` - Categorias de chamados (Hardware, Software, Rede, Acesso, Outro)
- `anexos` - Arquivos anexados aos chamados

## 🚀 Instalação

### Pré-requisitos

- Docker e Docker Compose
- PostgreSQL 15+
- Node.js 18+
- Python 3.11+

### 1. Clonar o Repositório

```bash
git clone https://github.com/sua-empresa/ChamadosHS.git
cd ChamadosHS
```

### 2. Configurar Banco de Dados

```bash
# Criar banco de dados
createdb chamados_db

# Executar schema (completo e atual; num banco novo não rode migrations/)
psql chamados_db < schema_chamados.sql
```

### 3. Configurar Backend

```bash
cd backend

# Criar ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows

# Instalar dependências
pip install -r requirements.txt

# Configurar variáveis de ambiente
cp .env.example .env
# Editar .env com suas configurações

# Rodar API
uvicorn main:app --reload --port 8000
```

### 4. Configurar Frontend

```bash
cd frontend

# Instalar dependências
npm install

# Configurar variáveis de ambiente
cp .env.example .env
# Editar .env com a URL da API

# Rodar aplicação
npm run dev
```

### 5. Acessar Sistema

- **Frontend**: http://localhost:5173
- **API**: http://localhost:8000
- **Documentação API**: http://localhost:8000/docs

## 📁 Estrutura de Diretórios

```
ChamadosHS/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── endpoints/
│   │   │   │   ├── chamados.py
│   │   │   │   ├── usuarios.py
│   │   │   │   ├── comentarios.py
│   │   │   │   └── relatorios.py
│   │   │   └── deps.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   └── security.py
│   │   ├── models/
│   │   │   ├── chamado.py
│   │   │   ├── usuario.py
│   │   │   └── comentario.py
│   │   ├── schemas/
│   │   │   ├── chamado.py
│   │   │   ├── usuario.py
│   │   │   └── comentario.py
│   │   └── services/
│   │       ├── chamado_service.py
│   │       └── notificacao_service.py
│   ├── main.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── FormularioChamado.tsx
│   │   │   ├── ListaChamados.tsx
│   │   │   ├── DetalhesChamado.tsx
│   │   │   └── Dashboard.tsx
│   │   ├── pages/
│   │   │   ├── AbrirChamado.tsx
│   │   │   ├── MeusChamados.tsx
│   │   │   ├── GerenciarChamados.tsx
│   │   │   └── Relatorios.tsx
│   │   ├── services/
│   │   │   └── api.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── .env.example
├── database/
│   └── schema_chamados.sql
├── docker-compose.yml
└── README.md
```

## 🔐 Perfis de Acesso

Resumo. A regra completa, rota a rota, está em [AUTH.md](AUTH.md) ("Restrições
por perfil" e "Leitura de chamado").

### Administrador
- Acesso total ao sistema
- Gerenciar usuários, setores (inclusive excluir), categorias, SLA e
  tarefas recorrentes
- Visualizar todos os chamados
- Gerar relatórios completos

### Técnico
- Técnico da TI (setor listado em `SETORES_TI_IDS`): visualizar e gerenciar
  os chamados da TI e da Qualidade, e ser responsável por chamado da TI;
  administrar setores (sem excluir), categorias, prazos de SLA e tarefas
  recorrentes, e ver a trilha de setores
- Técnico da Qualidade (setor de `SETOR_QUALIDADE_ID`): visualizar e
  gerenciar os chamados da Qualidade; da TI, só ver os que abriu ou atende
- Técnico de outro setor, ou sem setor: só os chamados que abriu ou atende
- Fora da TI, nenhum técnico administra cadastros, SLA ou rotinas — nem o da
  Qualidade (API-7)
- Comentar (inclusive comentário interno) e resolver
- Gerar relatórios da equipe

### Usuário
- Abrir novos chamados
- Visualizar e comentar os chamados que abriu ou que atende hoje (atendimento
  da Qualidade)
- Avaliar atendimento

Quem não pode ver um chamado recebe o mesmo 404 de um chamado que não existe,
também ao tentar alterá-lo, cancelá-lo, avaliá-lo, atendê-lo ou mexer nos
comentários dele.

**`SETORES_TI_IDS` precisa estar configurada:** sem ela nenhum técnico é da
TI, e a administração fica só com o administrador (ver `.env.example` e a seção "Ação necessária no deploy" do
[CHANGELOG](CHANGELOG.md)). Os ids saem do cadastro de cada ambiente, por
`diagnosticos/api6_setores_ti.sql`; num banco local criado pelo
`schema_chamados.sql`, quem decide quais setores são da TI é você.

## 📊 Fluxo de Chamados

```
Aberto → Em Andamento → Aguardando → Resolvido → Fechado
```

### Status Detalhados

- **Aberto**: Chamado criado, aguardando atribuição
- **Em Andamento**: Técnico trabalhando na resolução
- **Aguardando**: Aguardando resposta do solicitante ou terceiros
- **Resolvido**: Problema solucionado, aguardando confirmação
- **Fechado**: Chamado finalizado e arquivado

## 🎯 Prioridades

- **Crítica**: Sistema parado, impacto em toda empresa
- **Alta**: Problema grave, impacto significativo
- **Média**: Problema moderado, pode aguardar
- **Baixa**: Solicitação simples, sem urgência

## 📈 Relatórios e Métricas

### Relatórios Disponíveis

- Chamados por período
- Chamados por categoria
- Chamados por técnico
- Tempo médio de resolução
- Taxa de satisfação
- Solicitantes mais frequentes
- Equipamentos/setores problemáticos

### KPIs Principais

- **Tempo Médio de Resposta**: Tempo até primeiro atendimento
- **Tempo Médio de Resolução**: Tempo total até resolver
- **Taxa de Resolução no Prazo**: % resolvidos dentro do SLA
- **Satisfação do Usuário**: Média das avaliações (1-5)
- **Volume por Categoria**: Distribuição de tipos de chamados

## 🔔 Notificações

Integrações via n8n:

- ✉️ Email ao abrir chamado
- 💬 WhatsApp para chamados críticos
- 📊 Relatório diário para gestão
- ⚠️ Alerta de chamados não atendidos

## 🔒 Conformidade ISO 27001

### Requisitos Atendidos

- ✅ **Registro de Incidentes**: Todos os chamados são registrados com data/hora
- ✅ **Rastreabilidade**: Histórico completo de ações
- ✅ **Classificação**: Categorias e prioridades definidas
- ✅ **Atribuição**: Responsável identificado
- ✅ **Resolução**: Solução documentada
- ✅ **Auditoria**: Relatórios para análise

### Relatórios para Auditoria

```sql
-- Exemplo: Incidentes de segurança no período
SELECT * FROM chamados 
WHERE categoria_id = (SELECT id FROM categorias WHERE nome = 'Acesso')
AND data_abertura BETWEEN '2024-01-01' AND '2024-12-31'
ORDER BY data_abertura;
```

## 🤝 Contribuindo

1. Fork o projeto
2. Crie uma branch para sua feature (`git checkout -b feature/NovaFuncionalidade`)
3. Commit suas mudanças (`git commit -m 'Adiciona nova funcionalidade'`)
4. Push para a branch (`git push origin feature/NovaFuncionalidade`)
5. Abra um Pull Request

## 📝 Licença

Este projeto é proprietário da [Nome da Empresa] e de uso interno apenas.

## 👥 Equipe

- **Desenvolvedor**: Erick Santos
- **Setor**: TI
- **Contato**: ti@healthsafetytech.com

## 📅 Roadmap

### Versão 1.0 (Atual)
- ✅ CRUD de chamados
- ✅ Sistema de comentários
- ✅ Histórico de ações
- ✅ Relatórios básicos

### Versão 1.1 (Próxima)
- ⏳ SLA automático
- ⏳ Notificações em tempo real
- ⏳ Dashboard interativo
- ⏳ Integração com WhatsApp

### Versão 2.0 (Futuro)
- 📋 Base de conhecimento
- 📋 Chatbot para abertura
- 📋 App mobile
- 📋 Integração com Active Directory

## 🐛 Reportar Bugs

Encontrou um bug? Abra um chamado no próprio sistema! 😄

Ou entre em contato com a equipe de TI:
- Email: ti@healthsafetytech.com

---

**Desenvolvido com ❤️ pela equipe de TI**