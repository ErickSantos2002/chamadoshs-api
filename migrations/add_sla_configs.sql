-- Prazos de SLA por prioridade, em MINUTOS ÚTEIS (expediente de 480 min/dia).
-- Baixa:   resposta 8h úteis  / resolução 3 dias úteis
-- Média:   resposta 4h        / resolução 1 dia útil
-- Alta:    resposta 1h        / resolução 4h  (piso da faixa "4 a 8h", para não empatar com Média)
-- Crítica: resposta 15min     / resolução 2h

CREATE TABLE IF NOT EXISTS sla_configs (
    prioridade        VARCHAR(20) PRIMARY KEY,
    minutos_resposta  INTEGER NOT NULL,
    minutos_resolucao INTEGER NOT NULL
);

INSERT INTO sla_configs (prioridade, minutos_resposta, minutos_resolucao) VALUES
    ('Baixa',   480, 1440),
    ('Média',   240,  480),
    ('Alta',     60,  240),
    ('Crítica',  15,  120)
ON CONFLICT (prioridade) DO NOTHING;
