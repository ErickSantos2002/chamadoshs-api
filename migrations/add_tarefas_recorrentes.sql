-- Tarefas recorrentes (rotinas). NÃO são chamados.
-- Cada tarefa tem um padrão de recorrência (diária/semanal/mensal) e a data da
-- próxima execução. Cada vez que é realizada, gera uma linha em
-- tarefas_recorrentes_execucoes e a proxima_data avança para a próxima ocorrência.

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

CREATE INDEX IF NOT EXISTS idx_tr_execucoes_tarefa ON tarefas_recorrentes_execucoes(tarefa_id);
CREATE INDEX IF NOT EXISTS idx_tr_proxima_data ON tarefas_recorrentes(proxima_data);
