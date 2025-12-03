-- =====================================================
-- Script para adicionar campo URGENCIA na tabela chamados
-- Data: 2025-12-03
-- =====================================================

-- 1. Adicionar coluna urgencia
ALTER TABLE chamados
ADD COLUMN urgencia VARCHAR(20) NULL;

-- 2. Adicionar comentário na coluna
COMMENT ON COLUMN chamados.urgencia IS 'Nível de urgência definido por técnicos (Não Urgente, Normal, Urgente, Muito Urgente)';

-- 3. Adicionar constraint de validação
ALTER TABLE chamados
ADD CONSTRAINT chk_urgencia
CHECK (urgencia IS NULL OR urgencia IN ('Não Urgente', 'Normal', 'Urgente', 'Muito Urgente'));

-- 4. Verificar a estrutura da tabela
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'chamados'
ORDER BY ordinal_position;

-- =====================================================
-- FIM DO SCRIPT
-- =====================================================
