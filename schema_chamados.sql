-- ============================================
-- SISTEMA DE CHAMADOS - SCHEMA PostgreSQL
-- ============================================

-- Tabela de Setores
CREATE TABLE setores (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL UNIQUE,
    descricao TEXT,
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Roles (Perfis de Acesso)
CREATE TABLE roles (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(50) NOT NULL UNIQUE,
    descricao TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Usuários
CREATE TABLE usuarios (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    setor_id INTEGER REFERENCES setores(id),
    role_id INTEGER NOT NULL REFERENCES roles(id),
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Categorias
CREATE TABLE categorias (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) NOT NULL,
    descricao TEXT,
    ativo BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela Principal de Chamados
CREATE TABLE chamados (
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
    
    -- Prioridade e Status
    prioridade VARCHAR(20) DEFAULT 'Média',
    status VARCHAR(50) DEFAULT 'Aberto',
    
    -- Atendimento
    tecnico_responsavel_id INTEGER REFERENCES usuarios(id),
    solucao TEXT,
    tempo_resolucao_minutos INTEGER,
    
    -- Observações e Avaliação
    observacoes TEXT,
    avaliacao INTEGER CHECK (avaliacao >= 1 AND avaliacao <= 5),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT chk_prioridade CHECK (prioridade IN ('Baixa', 'Média', 'Alta', 'Crítica')),
    CONSTRAINT chk_status CHECK (status IN ('Aberto', 'Em Andamento', 'Aguardando', 'Resolvido', 'Fechado'))
);

-- Tabela de Comentários nos Chamados
CREATE TABLE comentarios_chamados (
    id SERIAL PRIMARY KEY,
    chamado_id INTEGER NOT NULL REFERENCES chamados(id) ON DELETE CASCADE,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    comentario TEXT NOT NULL,
    is_interno BOOLEAN DEFAULT FALSE, -- comentário visível só para técnicos
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabela de Histórico (Auditoria)
CREATE TABLE historico_chamados (
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
CREATE TABLE anexos (
    id SERIAL PRIMARY KEY,
    chamado_id INTEGER NOT NULL REFERENCES chamados(id) ON DELETE CASCADE,
    nome_arquivo VARCHAR(255) NOT NULL,
    caminho VARCHAR(500) NOT NULL,
    tamanho_kb INTEGER,
    tipo_mime VARCHAR(100),
    uploaded_by INTEGER REFERENCES usuarios(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- ÍNDICES PARA PERFORMANCE
-- ============================================

CREATE INDEX idx_chamados_solicitante ON chamados(solicitante_id);
CREATE INDEX idx_chamados_tecnico ON chamados(tecnico_responsavel_id);
CREATE INDEX idx_chamados_status ON chamados(status);
CREATE INDEX idx_chamados_prioridade ON chamados(prioridade);
CREATE INDEX idx_chamados_data_abertura ON chamados(data_abertura);
CREATE INDEX idx_chamados_categoria ON chamados(categoria_id);
CREATE INDEX idx_historico_chamado ON historico_chamados(chamado_id);
CREATE INDEX idx_comentarios_chamado ON comentarios_chamados(chamado_id);
CREATE INDEX idx_anexos_chamado ON anexos(chamado_id);
CREATE INDEX idx_usuarios_setor ON usuarios(setor_id);
CREATE INDEX idx_usuarios_role ON usuarios(role_id);

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

-- Triggers para atualização automática
CREATE TRIGGER trigger_usuarios_updated_at
    BEFORE UPDATE ON usuarios
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_updated_at();

CREATE TRIGGER trigger_chamados_updated_at
    BEFORE UPDATE ON chamados
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_updated_at();

CREATE TRIGGER trigger_comentarios_updated_at
    BEFORE UPDATE ON comentarios_chamados
    FOR EACH ROW
    EXECUTE FUNCTION atualizar_updated_at();

-- ============================================
-- DADOS INICIAIS (SEED)
-- ============================================

-- Inserir Roles padrão
INSERT INTO roles (nome, descricao) VALUES
    ('Administrador', 'Acesso total ao sistema'),
    ('Tecnico', 'Equipe de TI que atende chamados'),
    ('Usuario', 'Funcionário que abre chamados');

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
    ('Comercial - Servicos', 'Setor Comercial - Serviços');

-- Inserir Categorias padrão
INSERT INTO categorias (nome, descricao) VALUES
    ('Hardware', 'Problemas com equipamentos físicos'),
    ('Software', 'Problemas com programas e sistemas'),
    ('Rede', 'Problemas de conectividade e internet'),
    ('Acesso', 'Requisições de acesso e permissões'),
    ('Outro', 'Outros tipos de solicitações');

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

COMMENT ON COLUMN chamados.protocolo IS 'Número único de protocolo (ex: CHAM-2024-001)';
COMMENT ON COLUMN chamados.tempo_resolucao_minutos IS 'Tempo entre abertura e resolução em minutos';
COMMENT ON COLUMN chamados.avaliacao IS 'Nota de satisfação do solicitante (1 a 5)';
COMMENT ON COLUMN comentarios_chamados.is_interno IS 'Se TRUE, visível apenas para técnicos';

-- ============================================
-- FIM DO SCHEMA
-- ============================================