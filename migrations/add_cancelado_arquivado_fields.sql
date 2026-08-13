-- Script para adicionar campos de cancelado e arquivado na tabela chamados
-- Execute este script manualmente no banco de dados

ALTER TABLE chamados
ADD COLUMN cancelado BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE chamados
ADD COLUMN arquivado BOOLEAN NOT NULL DEFAULT FALSE;

-- Opcional: adicionar índices para melhorar performance nas consultas
CREATE INDEX idx_chamados_cancelado ON chamados(cancelado);
CREATE INDEX idx_chamados_arquivado ON chamados(arquivado);
