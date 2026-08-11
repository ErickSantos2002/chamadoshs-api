-- ============================================
-- SISTEMA DE CHAMADOS - SCHEMA PostgreSQL
-- ============================================
--
-- Este arquivo é o schema COMPLETO e ATUAL. Rodá-lo num banco vazio produz um
-- banco em que a API sobe e as pessoas conseguem autenticar. É o arquivo de
-- recuperação de desastre e de montagem de homologação — nada além dele é
-- necessário para um banco novo.
--
-- Isso mudou em 11/08/2026. Antes, este arquivo era o schema da 1.0 e as seis
-- entregas seguintes viviam só em `migrations/`: rodá-lo sozinho criava um
-- banco sem `usuarios.senha_hash`, ou seja, um banco onde ninguém loga. O
-- procedimento correto (base + migrations na ordem) existia em prosa no
-- DEPLOY.md e já estava desatualizado — listava duas das seis.
--
-- Divisão de trabalho, agora explícita:
--
--   banco NOVO       -> rode só este arquivo. NÃO rode `migrations/`.
--   banco EXISTENTE  -> rode só o que falta de `migrations/`. Não rode este.
--
-- A segunda regra tem consequência prática: rodar as migrations depois deste
-- arquivo falha, porque parte delas não é idempotente (`add_auth_fields.sql`
-- faz `ADD COLUMN` sem `IF NOT EXISTS`). Elas existem para bancos criados
-- antes da entrega correspondente, e é só para isso que servem.
--
-- `tests/test_schema_sql_bate_com_os_models.py` compara este arquivo com os
-- models do SQLAlchemy e falha se divergirem. Coluna nova em `app/models/`
-- sem a coluna aqui quebra a suíte — que é o único motivo de este arquivo
-- não voltar a envelhecer sozinho.
--
-- Tudo aqui é idempotente: rodar duas vezes não estraga nada.

-- Tabela de Setores
CREATE TABLE IF NOT EXISTS setores (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL UNIQUE,
    descricao TEXT,
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Roles (Perfis de Acesso)
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(50) NOT NULL UNIQUE,
    descricao TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Usuários
--
-- `nome` é o username do login, por isso o UNIQUE. `criar_usuario_inicial.sql`
-- depende dele: sem a restrição, o `ON CONFLICT (nome) DO NOTHING` de lá é
-- erro de sintaxe, não proteção.
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    senha_hash VARCHAR(255),
    setor_id INTEGER REFERENCES setores(id),
    role_id INTEGER NOT NULL REFERENCES roles(id),
    ativo BOOLEAN DEFAULT TRUE,
    -- Conta que não representa uma pessoa: painel de parede, integração,
    -- login compartilhado. Distinta de `ativo` — estas contas precisam
    -- autenticar, e `get_current_user` recusa usuário inativo.
    conta_de_servico BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT usuarios_nome_unique UNIQUE (nome)
);

-- Tabela de Categorias
CREATE TABLE IF NOT EXISTS categorias (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    descricao TEXT,
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela Principal de Chamados
CREATE TABLE IF NOT EXISTS chamados (
    id SERIAL PRIMARY KEY,
    protocolo VARCHAR(50) UNIQUE NOT NULL,

    -- Quem e quando
    solicitante_id INTEGER NOT NULL REFERENCES usuarios(id),
    data_abertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_resolucao TIMESTAMP,

    -- O que
    categoria_id INTEGER REFERENCES categorias(id),
    titulo VARCHAR(255) NOT NULL,
    descricao TEXT NOT NULL,

    -- Prioridade, Urgência e Status
    prioridade VARCHAR(20) DEFAULT 'Média',
    urgencia VARCHAR(20),
    status VARCHAR(50) DEFAULT 'Aberto',

    -- Atendimento
    tecnico_responsavel_id INTEGER REFERENCES usuarios(id),
    solucao TEXT,
    tempo_resolucao_minutos INTEGER,

    -- Observações e Avaliação
    observacoes TEXT,
    avaliacao INTEGER CHECK (avaliacao >= 1 AND avaliacao <= 5),

    -- Flags de controle (soft delete e arquivamento)
    cancelado BOOLEAN NOT NULL DEFAULT FALSE,
    arquivado BOOLEAN NOT NULL DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT chk_prioridade CHECK (prioridade IN ('Baixa', 'Média', 'Alta', 'Crítica')),
    CONSTRAINT chk_urgencia CHECK (urgencia IS NULL OR urgencia IN ('Não Urgente', 'Normal', 'Urgente', 'Muito Urgente')),
    CONSTRAINT chk_status CHECK (status IN ('Aberto', 'Em Andamento', 'Aguardando', 'Resolvido', 'Fechado'))
);

-- Tabela de Comentários nos Chamados
CREATE TABLE IF NOT EXISTS comentarios_chamados (
    id SERIAL PRIMARY KEY,
    chamado_id INTEGER NOT NULL REFERENCES chamados(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    comentario TEXT NOT NULL,
    is_interno BOOLEAN DEFAULT FALSE, -- comentário visível só para técnicos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Histórico (Auditoria)
CREATE TABLE IF NOT EXISTS historico_chamados (
    id SERIAL PRIMARY KEY,
    chamado_id INTEGER NOT NULL REFERENCES chamados(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    acao VARCHAR(100) NOT NULL,
    descricao TEXT,
    status_anterior VARCHAR(50),
    status_novo VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Anexos
CREATE TABLE IF NOT EXISTS anexos (
    id SERIAL PRIMARY KEY,
    chamado_id INTEGER NOT NULL REFERENCES chamados(id) ON DELETE CASCADE,
    nome_arquivo VARCHAR(255) NOT NULL,
    caminho VARCHAR(500) NOT NULL,
    tamanho_kb INTEGER,
    tipo_mime VARCHAR(100),
    uploaded_by INTEGER REFERENCES usuarios(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Prazos de SLA por prioridade, em MINUTOS ÚTEIS (expediente de 480 min/dia).
--
-- Sem linha para uma prioridade, o chamado daquela prioridade simplesmente não
-- tem SLA — a API devolve o campo `sla` nulo em vez de um falso "No prazo".
CREATE TABLE IF NOT EXISTS sla_configs (
    prioridade        VARCHAR(20) PRIMARY KEY,
    minutos_resposta  INTEGER NOT NULL,
    minutos_resolucao INTEGER NOT NULL
);

-- Tarefas recorrentes (rotinas). NÃO são chamados.
--
-- Cada tarefa tem um padrão de recorrência (diária/semanal/mensal) e a data da
-- próxima execução. Cada vez que é realizada, gera uma linha em
-- tarefas_recorrentes_execucoes e a proxima_data avança para a ocorrência
-- seguinte.
CREATE TABLE IF NOT EXISTS tarefas_recorrentes (
    id                SERIAL PRIMARY KEY,
    titulo            VARCHAR(255) NOT NULL,
    descricao         TEXT,
    instrucoes        TEXT,
    categoria_id      INTEGER REFERENCES categorias(id),
    responsavel_id    INTEGER REFERENCES usuarios(id),
    prioridade        VARCHAR(20) NOT NULL DEFAULT 'Média',
    tipo_recorrencia  VARCHAR(10) NOT NULL,           -- diaria | semanal | mensal
    intervalo         INTEGER NOT NULL DEFAULT 1,     -- a cada N dias/semanas/meses
    dia_semana        SMALLINT,                       -- 0=Dom..6=Sáb (quando semanal)
    dia_mes           SMALLINT,                       -- 1..31 (quando mensal)
    proxima_data      DATE NOT NULL,
    ativo             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP NOT NULL DEFAULT now(),
    updated_at        TIMESTAMP NOT NULL DEFAULT now(),

    CONSTRAINT chk_tr_prioridade CHECK (prioridade IN ('Baixa','Média','Alta','Crítica')),
    CONSTRAINT chk_tr_tipo CHECK (tipo_recorrencia IN ('diaria','semanal','mensal')),
    CONSTRAINT chk_tr_dia_semana CHECK (dia_semana IS NULL OR (dia_semana BETWEEN 0 AND 6)),
    CONSTRAINT chk_tr_dia_mes CHECK (dia_mes IS NULL OR (dia_mes BETWEEN 1 AND 31))
);

-- Histórico de execuções de cada tarefa recorrente
CREATE TABLE IF NOT EXISTS tarefas_recorrentes_execucoes (
    id            SERIAL PRIMARY KEY,
    tarefa_id     INTEGER NOT NULL REFERENCES tarefas_recorrentes(id) ON DELETE CASCADE,
    usuario_id    INTEGER NOT NULL REFERENCES usuarios(id),
    data_prevista DATE,                               -- a proxima_data que estava agendada
    realizada_em  TIMESTAMP NOT NULL DEFAULT now(),
    observacao    TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);

-- ============================================
-- ÍNDICES PARA PERFORMANCE
-- ============================================

CREATE INDEX IF NOT EXISTS idx_chamados_solicitante ON chamados(solicitante_id);
CREATE INDEX IF NOT EXISTS idx_chamados_tecnico ON chamados(tecnico_responsavel_id);
CREATE INDEX IF NOT EXISTS idx_chamados_status ON chamados(status);
CREATE INDEX IF NOT EXISTS idx_chamados_prioridade ON chamados(prioridade);
CREATE INDEX IF NOT EXISTS idx_chamados_data_abertura ON chamados(data_abertura);
CREATE INDEX IF NOT EXISTS idx_chamados_categoria ON chamados(categoria_id);
CREATE INDEX IF NOT EXISTS idx_chamados_cancelado ON chamados(cancelado);
CREATE INDEX IF NOT EXISTS idx_chamados_arquivado ON chamados(arquivado);
CREATE INDEX IF NOT EXISTS idx_historico_chamado ON historico_chamados(chamado_id);
CREATE INDEX IF NOT EXISTS idx_comentarios_chamado ON comentarios_chamados(chamado_id);
CREATE INDEX IF NOT EXISTS idx_anexos_chamado ON anexos(chamado_id);
CREATE INDEX IF NOT EXISTS idx_usuarios_setor ON usuarios(setor_id);
CREATE INDEX IF NOT EXISTS idx_usuarios_role ON usuarios(role_id);
CREATE INDEX IF NOT EXISTS idx_usuarios_nome_login ON usuarios(nome) WHERE ativo = true;
CREATE INDEX IF NOT EXISTS idx_tr_execucoes_tarefa ON tarefas_recorrentes_execucoes(tarefa_id);
CREATE INDEX IF NOT EXISTS idx_tr_proxima_data ON tarefas_recorrentes(proxima_data);

-- ============================================
-- FUNÇÃO PARA ATUALIZAR updated_at
-- ============================================

CREATE OR REPLACE FUNCTION atualizar_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers para atualização automática.
--
-- Só nas três tabelas que já tinham trigger em produção. `tarefas_recorrentes`
-- também tem `updated_at`, mas quem o mantém é o `onupdate` do SQLAlchemy —
-- criar um trigger aqui deixaria este arquivo diferente do banco que está no
-- ar, que é exatamente o problema que ele deveria resolver.
DROP TRIGGER IF EXISTS trigger_usuarios_updated_at ON usuarios;
CREATE TRIGGER trigger_usuarios_updated_at
    BEFORE UPDATE ON usuarios
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_updated_at();

DROP TRIGGER IF EXISTS trigger_chamados_updated_at ON chamados;
CREATE TRIGGER trigger_chamados_updated_at
    BEFORE UPDATE ON chamados
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_updated_at();

DROP TRIGGER IF EXISTS trigger_comentarios_updated_at ON comentarios_chamados;
CREATE TRIGGER trigger_comentarios_updated_at
    BEFORE UPDATE ON comentarios_chamados
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_updated_at();

-- ============================================
-- DADOS INICIAIS (SEED)
-- ============================================

-- Inserir Roles padrão.
--
-- Os nomes são lidos por `app/api/deps.py` (ROLE_ADMIN, ROLE_TECNICO,
-- ROLE_USUARIO). Mudar um nome aqui derruba a autorização inteira.
INSERT INTO roles (nome, descricao) VALUES
    ('Administrador', 'Acesso total ao sistema'),
    ('Tecnico', 'Equipe de TI que atende chamados'),
    ('Usuario', 'Funcionário que abre chamados')
ON CONFLICT (nome) DO NOTHING;

-- Inserir Setores (padrão da empresa)
INSERT INTO setores (nome, descricao) VALUES
    ('Ti', 'Setor de Ti'),
    ('ADM', 'Setor administrativo'),
    ('Diretoria', 'Setor Administração Geral'),
    ('Suporte', 'Setor Suporte Técnico'),
    ('Qualidade', 'Setor Qualidade'),
    ('Laboratorio', 'Setor Laboratório'),
    ('Expedicao', 'Setor Expedição/Almoxarifado'),
    ('Comercial - Vendas', 'Setor Comercial - Vendas'),
    ('Comercial - Servicos', 'Setor Comercial - Serviços')
ON CONFLICT (nome) DO NOTHING;

-- Inserir Categorias padrão.
--
-- `categorias.nome` não é UNIQUE, então não há ON CONFLICT para usar aqui: a
-- guarda é semear só com a tabela vazia. Rodar de novo num banco que já tem
-- categorias (inclusive categorias criadas pela equipe) não duplica nada.
INSERT INTO categorias (nome, descricao)
SELECT * FROM (VALUES
    ('Hardware', 'Problemas com equipamentos físicos'),
    ('Software', 'Problemas com programas e sistemas'),
    ('Rede', 'Problemas de conectividade e internet'),
    ('Acesso', 'Requisições de acesso e permissões'),
    ('Outro', 'Outros tipos de solicitações')
) AS v(nome, descricao)
WHERE NOT EXISTS (SELECT 1 FROM categorias);

-- Prazos de SLA por prioridade, em minutos úteis:
-- Baixa:   resposta 8h úteis  / resolução 3 dias úteis
-- Média:   resposta 4h        / resolução 1 dia útil
-- Alta:    resposta 1h        / resolução 4h  (piso da faixa "4 a 8h", para não empatar com Média)
-- Crítica: resposta 15min     / resolução 2h
INSERT INTO sla_configs (prioridade, minutos_resposta, minutos_resolucao) VALUES
    ('Baixa',   480, 1440),
    ('Média',   240,  480),
    ('Alta',     60,  240),
    ('Crítica',  15,  120)
ON CONFLICT (prioridade) DO NOTHING;

-- ============================================
-- COMENTÁRIOS NAS TABELAS (DOCUMENTAÇÃO)
-- ============================================

COMMENT ON TABLE setores IS 'Setores da empresa';
COMMENT ON TABLE roles IS 'Perfis de acesso dos usuários';
COMMENT ON TABLE usuarios IS 'Usuários do sistema (solicitantes e técnicos)';
COMMENT ON TABLE categorias IS 'Categorias de chamados';
COMMENT ON TABLE chamados IS 'Chamados/Tickets de suporte';
COMMENT ON TABLE comentarios_chamados IS 'Comentários e conversas nos chamados';
COMMENT ON TABLE historico_chamados IS 'Histórico de alterações para auditoria';
COMMENT ON TABLE anexos IS 'Arquivos anexados aos chamados';
COMMENT ON TABLE sla_configs IS 'Prazos de SLA por prioridade, em minutos úteis';
COMMENT ON TABLE tarefas_recorrentes IS 'Rotinas periódicas da equipe; não são chamados';
COMMENT ON TABLE tarefas_recorrentes_execucoes IS 'Registro de cada vez que uma tarefa recorrente foi realizada';

COMMENT ON COLUMN chamados.protocolo IS 'Número único de protocolo (ex: CHAM-2024-001)';
COMMENT ON COLUMN chamados.tempo_resolucao_minutos IS 'Tempo entre abertura e resolução em minutos';
COMMENT ON COLUMN chamados.avaliacao IS 'Nota de satisfação do solicitante (1 a 5)';
COMMENT ON COLUMN chamados.urgencia IS 'Nível de urgência definido por técnicos (Não Urgente, Normal, Urgente, Muito Urgente)';
COMMENT ON COLUMN chamados.cancelado IS 'Soft delete: some da visualização padrão, permanece no banco';
COMMENT ON COLUMN chamados.arquivado IS 'Sai da visualização padrão sem ser cancelado';
COMMENT ON COLUMN comentarios_chamados.is_interno IS 'Se TRUE, visível apenas para técnicos';
COMMENT ON COLUMN usuarios.senha_hash IS 'Hash bcrypt da senha do usuário';
COMMENT ON COLUMN usuarios.conta_de_servico IS 'Conta que não representa uma pessoa (painel, integração, login compartilhado)';

-- ============================================
-- FIM DO SCHEMA
-- ============================================
