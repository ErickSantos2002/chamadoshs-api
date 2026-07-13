# SLA de atendimento + correção do delete de categoria — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calcular, exibir e medir o SLA dos chamados por prioridade (em horas úteis), com prazos configuráveis, e fazer o botão "Excluir categoria" apagar de verdade.

**Architecture:** O SLA é **derivado**, nunca armazenado no chamado. Um motor de horas úteis (funções puras) soma/conta minutos dentro do expediente; o endpoint de chamados enriquece cada resposta com um bloco `sla` calculado a partir de `data_abertura` + `historico_chamados` + a tabela `sla_configs`. O frontend só pinta o que recebe.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Pydantic v2 + Postgres 15 (backend); React 18 + TypeScript + Vite + Tailwind + axios (frontend). Docker Compose para subir a stack.

## Global Constraints

- **Expediente:** seg–sex, 08:00–12:00 e 13:00–17:00 (pausa de almoço) → **480 minutos úteis/dia**.
- **Feriados:** não são considerados. Só sábado e domingo são não-úteis.
- **Prazos padrão (minutos úteis):** Baixa 480/1440 · Média 240/480 · Alta 60/240 · Crítica 15/120 (resposta/resolução).
- **"Atenção"** = ≥80% do prazo de resolução consumido. **"Estourado"** = >100%.
- **`situacao` reflete o relógio de resolução.** O furo de resposta é reportado separadamente em `resposta_cumprida`.
- **Gotcha de timezone (crítico):** as colunas do banco são `TIMESTAMP` *sem* timezone → o SQLAlchemy devolve datetimes **naive**. Já `agora_brasilia()` devolve **aware**. Misturar os dois levanta `TypeError: can't subtract offset-naive and offset-aware datetimes`. **Todo cálculo do SLA normaliza para naive-Brasília primeiro** (helper `_para_naive_brasilia`).
- **Sem pytest** (decisão do Erick). Verificação = script de bordas descartável + stack Docker local.
- **Portas locais:** a API sobe em **8001** e o Postgres em **5433** — a 8000 está ocupada pelo TaskHS e não pode ser tocada.
- Timezone de referência: `America/Sao_Paulo` (`app/utils/timezone.py`).

## Estrutura de arquivos

**Backend (`~/github/chamadoshs-api`)**

| Arquivo | Responsabilidade |
|---|---|
| `app/services/horario_util.py` | **Novo.** Motor puro de horas úteis: somar e contar minutos dentro do expediente. Sem dependência de banco. |
| `app/services/sla_service.py` | **Novo.** Regras de SLA: pausas, relógios de resposta/resolução, situação. Usa o motor acima. |
| `app/models/sla_config.py` | **Novo.** ORM da tabela `sla_configs`. |
| `app/schemas/sla.py` | **Novo.** `SLAInfo` (bloco embutido no chamado) e `SLAConfigResponse`/`SLAConfigUpdate`. |
| `app/api/endpoints/sla_configs.py` | **Novo.** `GET /` e `PUT /{prioridade}`. |
| `migrations/add_sla_configs.sql` | **Novo.** Cria e semeia `sla_configs`. |
| `app/models/__init__.py` | Registrar `SLAConfig`. |
| `app/schemas/chamado.py` | `ChamadoResponse` ganha `sla: Optional[SLAInfo]`. |
| `app/api/endpoints/chamados.py` | Enriquecer `listar_chamados` e `buscar_chamado` com o SLA. |
| `app/api/endpoints/categorias.py` | `deletar_categoria` vira hard delete com trava de vínculo. |
| `main.py` | Registrar o router de `sla_configs`. |

**Frontend (`~/github/chamadoshs-sistema`)**

| Arquivo | Responsabilidade |
|---|---|
| `src/types/api.ts` | Tipos `SLAInfo`, `SLASituacao`, `SLAConfig`; campo `sla` em `Chamado`. |
| `src/services/chamadoshsapi.ts` | `slaConfigsService` (listar/atualizar). |
| `src/components/SlaBadge.tsx` | **Novo.** Badge reutilizável (verde/amarelo/vermelho + tooltip com o prazo). |
| `src/components/KanbanColumn.tsx` | Badge no card do chamado. |
| `src/pages/ChamadoDetalhes.tsx` | Bloco de SLA no detalhe. |
| `src/pages/Dashboard.tsx` | Métricas de SLA. |
| `src/components/cadastros/SlaTab.tsx` | **Novo.** Aba de edição dos prazos. |
| `src/pages/CadastrosBasicos.tsx` | Registrar a aba "SLA". |

---

### Task 1: Motor de horas úteis

O coração da feature. Funções puras, sem banco — é aqui que moram os bugs de borda.

**Files:**
- Create: `app/services/horario_util.py`
- Create (descartável): `/tmp/claude-1000/-home-ericks/b81285d3-e320-4160-875d-6901ef879c00/scratchpad/checar_horario_util.py`

**Interfaces:**
- Consumes: `app.utils.timezone.BRASILIA_TZ`
- Produces:
  - `somar_minutos_uteis(inicio: datetime, minutos: int) -> datetime`
  - `contar_minutos_uteis(inicio: datetime, fim: datetime) -> int`
  - `MINUTOS_POR_DIA_UTIL: int = 480`

- [ ] **Step 1: Escrever o motor**

Create `app/services/horario_util.py`:

```python
"""
Motor de horas úteis do SLA.

Expediente: seg-sex, 08:00-12:00 e 13:00-17:00 (480 minutos úteis por dia).
Feriados não são considerados nesta versão.

Todas as funções normalizam datetimes para naive-Brasília antes de calcular:
o banco guarda TIMESTAMP sem timezone (naive), mas agora_brasilia() devolve
aware — misturar os dois levanta TypeError.
"""
from datetime import date, datetime, time, timedelta

from app.utils.timezone import BRASILIA_TZ

# Janelas do expediente (início, fim)
JANELAS = [
    (time(8, 0), time(12, 0)),
    (time(13, 0), time(17, 0)),
]

MINUTOS_POR_DIA_UTIL = 480

# Trava de segurança: impede loop infinito se alguém pedir um prazo absurdo.
_MAX_ITERACOES = 10_000


def _para_naive_brasilia(dt: datetime) -> datetime:
    """Converte para o horário de Brasília e remove o tzinfo."""
    if dt.tzinfo is not None:
        return dt.astimezone(BRASILIA_TZ).replace(tzinfo=None)
    return dt


def _e_dia_util(d: date) -> bool:
    return d.weekday() < 5  # 0=segunda ... 4=sexta


def _minutos_uteis_no_dia(dia: date, inicio: datetime, fim: datetime) -> int:
    """Minutos úteis do dia `dia` que caem dentro do intervalo [inicio, fim]."""
    if not _e_dia_util(dia):
        return 0

    total = 0
    for janela_inicio, janela_fim in JANELAS:
        abertura = datetime.combine(dia, janela_inicio)
        fechamento = datetime.combine(dia, janela_fim)

        ini = max(abertura, inicio)
        f = min(fechamento, fim)
        if f > ini:
            total += int((f - ini).total_seconds() // 60)

    return total


def contar_minutos_uteis(inicio: datetime, fim: datetime) -> int:
    """Quantos minutos úteis existem entre `inicio` e `fim`."""
    inicio = _para_naive_brasilia(inicio)
    fim = _para_naive_brasilia(fim)

    if fim <= inicio:
        return 0

    total = 0
    dia = inicio.date()
    while dia <= fim.date():
        total += _minutos_uteis_no_dia(dia, inicio, fim)
        dia += timedelta(days=1)

    return total


def _proximo_instante_util(dt: datetime) -> datetime:
    """Se `dt` cai fora do expediente, avança para a próxima abertura."""
    while True:
        if not _e_dia_util(dt.date()):
            dt = datetime.combine(dt.date() + timedelta(days=1), JANELAS[0][0])
            continue

        for janela_inicio, janela_fim in JANELAS:
            abertura = datetime.combine(dt.date(), janela_inicio)
            fechamento = datetime.combine(dt.date(), janela_fim)
            if dt < abertura:
                return abertura
            if dt < fechamento:
                return dt

        # Passou do fim do expediente: vai para a abertura do próximo dia.
        dt = datetime.combine(dt.date() + timedelta(days=1), JANELAS[0][0])


def _fim_da_janela(dt: datetime) -> datetime:
    """Fim da janela de expediente que contém `dt` (assume dt já é útil)."""
    for janela_inicio, janela_fim in JANELAS:
        abertura = datetime.combine(dt.date(), janela_inicio)
        fechamento = datetime.combine(dt.date(), janela_fim)
        if abertura <= dt < fechamento:
            return fechamento
    raise ValueError(f"{dt} não está dentro do expediente")


def somar_minutos_uteis(inicio: datetime, minutos: int) -> datetime:
    """Soma `minutos` úteis a `inicio` e devolve o prazo final (naive-Brasília)."""
    atual = _proximo_instante_util(_para_naive_brasilia(inicio))

    if minutos <= 0:
        return atual

    restante = minutos
    for _ in range(_MAX_ITERACOES):
        atual = _proximo_instante_util(atual)
        fim_janela = _fim_da_janela(atual)
        disponivel = int((fim_janela - atual).total_seconds() // 60)

        if restante <= disponivel:
            return atual + timedelta(minutes=restante)

        restante -= disponivel
        atual = fim_janela

    raise RuntimeError(f"somar_minutos_uteis não convergiu para {minutos} minutos")
```

- [ ] **Step 2: Escrever o script de bordas**

Como não usamos pytest, este script é a rede de segurança. Create `/tmp/claude-1000/-home-ericks/b81285d3-e320-4160-875d-6901ef879c00/scratchpad/checar_horario_util.py`:

```python
"""Confere o motor de horas úteis nas bordas. Rodar DENTRO do container da API."""
from datetime import datetime

from app.services.horario_util import contar_minutos_uteis, somar_minutos_uteis

# (descrição, inicio, minutos, prazo esperado)
CASOS_SOMA = [
    ("Segunda 08:00 + 60min -> mesma manhã",
     datetime(2026, 7, 13, 8, 0), 60, datetime(2026, 7, 13, 9, 0)),
    ("Segunda 11:30 + 60min -> pula o almoço",
     datetime(2026, 7, 13, 11, 30), 60, datetime(2026, 7, 13, 13, 30)),
    ("Segunda 12:30 (no almoço) + 30min -> começa a contar 13h",
     datetime(2026, 7, 13, 12, 30), 30, datetime(2026, 7, 13, 13, 30)),
    ("Segunda 16:50 + 30min -> vira o dia",
     datetime(2026, 7, 13, 16, 50), 30, datetime(2026, 7, 14, 8, 20)),
    ("Sexta 16:00 + 120min -> pula o fim de semana",
     datetime(2026, 7, 17, 16, 0), 120, datetime(2026, 7, 20, 9, 0)),
    ("Sábado 10:00 + 60min -> começa segunda 08:00",
     datetime(2026, 7, 18, 10, 0), 60, datetime(2026, 7, 20, 9, 0)),
    ("Domingo 23:00 + 15min (crítico) -> segunda 08:15",
     datetime(2026, 7, 19, 23, 0), 15, datetime(2026, 7, 20, 8, 15)),
    ("Segunda 08:00 + 480min (1 dia útil) -> segunda 17:00",
     datetime(2026, 7, 13, 8, 0), 480, datetime(2026, 7, 13, 17, 0)),
    ("Segunda 08:00 + 1440min (3 dias úteis) -> quarta 17:00",
     datetime(2026, 7, 13, 8, 0), 1440, datetime(2026, 7, 15, 17, 0)),
    ("Antes da abertura: segunda 06:00 + 60min -> 09:00",
     datetime(2026, 7, 13, 6, 0), 60, datetime(2026, 7, 13, 9, 0)),
]

# (descrição, inicio, fim, minutos esperados)
CASOS_CONTAGEM = [
    ("Manhã inteira", datetime(2026, 7, 13, 8, 0), datetime(2026, 7, 13, 12, 0), 240),
    ("Dia útil inteiro", datetime(2026, 7, 13, 8, 0), datetime(2026, 7, 13, 17, 0), 480),
    ("Atravessa o almoço", datetime(2026, 7, 13, 11, 30), datetime(2026, 7, 13, 13, 30), 60),
    ("Fim de semana inteiro não conta",
     datetime(2026, 7, 18, 0, 0), datetime(2026, 7, 20, 0, 0), 0),
    ("Sexta 16:00 -> segunda 09:00 = 1h sexta + 1h segunda",
     datetime(2026, 7, 17, 16, 0), datetime(2026, 7, 20, 9, 0), 120),
    ("Fora do expediente dos dois lados (18h -> 07h) = 0",
     datetime(2026, 7, 13, 18, 0), datetime(2026, 7, 14, 7, 0), 0),
    ("Fim antes do início = 0", datetime(2026, 7, 13, 12, 0), datetime(2026, 7, 13, 8, 0), 0),
]

falhas = 0

print("== somar_minutos_uteis ==")
for descricao, inicio, minutos, esperado in CASOS_SOMA:
    obtido = somar_minutos_uteis(inicio, minutos)
    ok = obtido == esperado
    falhas += 0 if ok else 1
    print(f"[{'OK ' if ok else 'FALHA'}] {descricao}\n        esperado={esperado} obtido={obtido}")

print("\n== contar_minutos_uteis ==")
for descricao, inicio, fim, esperado in CASOS_CONTAGEM:
    obtido = contar_minutos_uteis(inicio, fim)
    ok = obtido == esperado
    falhas += 0 if ok else 1
    print(f"[{'OK ' if ok else 'FALHA'}] {descricao}\n        esperado={esperado} obtido={obtido}")

print(f"\n{'TODOS OS CASOS PASSARAM' if falhas == 0 else f'{falhas} CASO(S) FALHARAM'}")
raise SystemExit(1 if falhas else 0)
```

Referência do calendário usado: 2026-07-13 é uma **segunda**, 17/07 **sexta**, 18/07 **sábado**, 19/07 **domingo**, 20/07 **segunda**.

- [ ] **Step 3: Subir a stack e rodar o script**

```bash
cd ~/github/chamadoshs-api
docker compose -p chamadosdebug \
  -f docker-compose.yml \
  -f /tmp/claude-1000/-home-ericks/b81285d3-e320-4160-875d-6901ef879c00/scratchpad/chamados-override.yml \
  up -d
docker cp /tmp/claude-1000/-home-ericks/b81285d3-e320-4160-875d-6901ef879c00/scratchpad/checar_horario_util.py \
  chamadoshs_api_debug:/app/checar_horario_util.py
docker exec chamadoshs_api_debug python /app/checar_horario_util.py
```

Expected: todas as linhas `[OK ]` e `TODOS OS CASOS PASSARAM` (exit 0).
Se qualquer caso falhar, **corrigir o motor antes de seguir** — todo o resto depende dele.

- [ ] **Step 4: Commit**

```bash
git add app/services/horario_util.py
git commit -m "feat(sla): motor de horas uteis (seg-sex 8-17 com pausa de almoco)"
```

---

### Task 2: Tabela de configuração de prazos

**Files:**
- Create: `app/models/sla_config.py`
- Create: `app/schemas/sla.py`
- Create: `migrations/add_sla_configs.sql`
- Modify: `app/models/__init__.py`

**Interfaces:**
- Consumes: `app.core.database.Base`
- Produces:
  - Modelo `SLAConfig` com campos `prioridade: str` (PK), `minutos_resposta: int`, `minutos_resolucao: int`
  - Schemas `SLAConfigResponse`, `SLAConfigUpdate`, `SLAInfo`

- [ ] **Step 1: Criar o modelo**

Create `app/models/sla_config.py`:

```python
from sqlalchemy import Column, Integer, String

from app.core.database import Base


class SLAConfig(Base):
    """Prazos de SLA por prioridade, em minutos úteis."""
    __tablename__ = "sla_configs"

    prioridade = Column(String(20), primary_key=True)
    minutos_resposta = Column(Integer, nullable=False)
    minutos_resolucao = Column(Integer, nullable=False)
```

- [ ] **Step 2: Registrar o modelo**

Modify `app/models/__init__.py` — adicionar o import e a entrada em `__all__`:

```python
from app.models.sla_config import SLAConfig
```

E incluir `"SLAConfig"` na lista `__all__`.

- [ ] **Step 3: Criar os schemas**

Create `app/schemas/sla.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SLAConfigResponse(BaseModel):
    prioridade: str
    minutos_resposta: int
    minutos_resolucao: int

    model_config = ConfigDict(from_attributes=True)


class SLAConfigUpdate(BaseModel):
    minutos_resposta: int = Field(gt=0)
    minutos_resolucao: int = Field(gt=0)


class SLAInfo(BaseModel):
    """Bloco de SLA calculado e embutido em cada chamado."""
    prazo_resposta: Optional[datetime] = None
    prazo_resolucao: Optional[datetime] = None
    minutos_resposta_consumidos: int = 0
    minutos_resolucao_consumidos: int = 0
    minutos_pausados: int = 0
    percentual_resolucao: int = 0
    situacao: str = "No prazo"  # "No prazo" | "Atenção" | "Estourado"
    resposta_cumprida: bool = True
```

- [ ] **Step 4: Criar a migração com o seed**

Create `migrations/add_sla_configs.sql`:

```sql
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
```

- [ ] **Step 5: Aplicar a migração e conferir**

```bash
docker exec -i chamadoshs_pg_debug psql -U postgres -d chamados_db < migrations/add_sla_configs.sql
docker exec chamadoshs_pg_debug psql -U postgres -d chamados_db -c 'SELECT * FROM sla_configs ORDER BY minutos_resolucao DESC;'
```

Expected: 4 linhas, na ordem Baixa (1440) → Média (480) → Alta (240) → Crítica (120).

- [ ] **Step 6: Commit**

```bash
git add app/models/sla_config.py app/models/__init__.py app/schemas/sla.py migrations/add_sla_configs.sql
git commit -m "feat(sla): tabela sla_configs com prazos por prioridade"
```

---

### Task 3: Serviço de cálculo do SLA

**Files:**
- Create: `app/services/sla_service.py`

**Interfaces:**
- Consumes: `somar_minutos_uteis`, `contar_minutos_uteis` (Task 1); `SLAConfig` (Task 2); `Chamado`, `HistoricoChamado`
- Produces: `calcular_sla(chamado, historicos, config, agora=None) -> dict` — o dict tem exatamente as chaves de `SLAInfo`.

- [ ] **Step 1: Escrever o serviço**

Create `app/services/sla_service.py`:

```python
"""
Regras de SLA.

- Relógio de RESPOSTA: da abertura até a primeira saída do status "Aberto".
- Relógio de RESOLUÇÃO: da abertura até a resolução, descontando o tempo em "Aguardando".
- `situacao` reflete SEMPRE o relógio de resolução; o furo de resposta vai em
  `resposta_cumprida` separadamente.
"""
from datetime import datetime
from typing import List, Optional

from app.models.chamado import Chamado
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.services.horario_util import contar_minutos_uteis, somar_minutos_uteis
from app.utils.timezone import agora_brasilia

STATUS_FINAIS = ("Resolvido", "Fechado")
STATUS_PAUSA = "Aguardando"

PERCENTUAL_ATENCAO = 80


def _periodos_pausados(historicos: List[HistoricoChamado], fim_relogio: datetime):
    """
    Reconstrói os intervalos em que o chamado esteve em "Aguardando".

    Um período abre quando o status_novo vira "Aguardando" e fecha na transição
    seguinte. Se o chamado ainda está "Aguardando", o período fica aberto até
    `fim_relogio`.
    """
    transicoes = sorted(
        [h for h in historicos if h.status_novo],
        key=lambda h: h.created_at,
    )

    periodos = []
    inicio_pausa: Optional[datetime] = None

    for h in transicoes:
        if h.status_novo == STATUS_PAUSA and inicio_pausa is None:
            inicio_pausa = h.created_at
        elif h.status_novo != STATUS_PAUSA and inicio_pausa is not None:
            periodos.append((inicio_pausa, h.created_at))
            inicio_pausa = None

    if inicio_pausa is not None:
        periodos.append((inicio_pausa, fim_relogio))

    return periodos


def _fim_da_resposta(historicos: List[HistoricoChamado]) -> Optional[datetime]:
    """Momento da primeira saída do status "Aberto" (None se ainda não saiu)."""
    saidas = sorted(
        [
            h for h in historicos
            if h.status_anterior == "Aberto" and h.status_novo and h.status_novo != "Aberto"
        ],
        key=lambda h: h.created_at,
    )
    return saidas[0].created_at if saidas else None


def calcular_sla(
    chamado: Chamado,
    historicos: List[HistoricoChamado],
    config: Optional[SLAConfig],
    agora: Optional[datetime] = None,
) -> dict:
    """Calcula o bloco de SLA de um chamado. Devolve as chaves de SLAInfo."""
    if config is None or chamado.data_abertura is None:
        return SLA_VAZIO.copy()

    agora = agora or agora_brasilia()
    abertura = chamado.data_abertura

    # --- Relógio de resolução -------------------------------------------------
    resolvido = chamado.status in STATUS_FINAIS and chamado.data_resolucao is not None
    fim_resolucao = chamado.data_resolucao if resolvido else agora

    minutos_pausados = sum(
        contar_minutos_uteis(inicio, fim)
        for inicio, fim in _periodos_pausados(historicos, fim_resolucao)
    )

    consumido_resolucao = max(
        contar_minutos_uteis(abertura, fim_resolucao) - minutos_pausados,
        0,
    )

    # O prazo se estende pelo tempo que o chamado ficou parado esperando terceiros.
    prazo_resolucao = somar_minutos_uteis(
        abertura, config.minutos_resolucao + minutos_pausados
    )

    percentual = round(consumido_resolucao / config.minutos_resolucao * 100)

    if consumido_resolucao > config.minutos_resolucao:
        situacao = "Estourado"
    elif percentual >= PERCENTUAL_ATENCAO:
        situacao = "Atenção"
    else:
        situacao = "No prazo"

    # --- Relógio de resposta --------------------------------------------------
    fim_resposta = _fim_da_resposta(historicos) or agora
    consumido_resposta = contar_minutos_uteis(abertura, fim_resposta)
    prazo_resposta = somar_minutos_uteis(abertura, config.minutos_resposta)

    return {
        "prazo_resposta": prazo_resposta,
        "prazo_resolucao": prazo_resolucao,
        "minutos_resposta_consumidos": consumido_resposta,
        "minutos_resolucao_consumidos": consumido_resolucao,
        "minutos_pausados": minutos_pausados,
        "percentual_resolucao": percentual,
        "situacao": situacao,
        "resposta_cumprida": consumido_resposta <= config.minutos_resposta,
    }


SLA_VAZIO = {
    "prazo_resposta": None,
    "prazo_resolucao": None,
    "minutos_resposta_consumidos": 0,
    "minutos_resolucao_consumidos": 0,
    "minutos_pausados": 0,
    "percentual_resolucao": 0,
    "situacao": "No prazo",
    "resposta_cumprida": True,
}
```

- [ ] **Step 2: Commit**

```bash
git add app/services/sla_service.py
git commit -m "feat(sla): servico de calculo (pausas, resposta, resolucao, situacao)"
```

---

### Task 4: Expor o SLA nos chamados

**Files:**
- Modify: `app/schemas/chamado.py` (`ChamadoResponse`)
- Modify: `app/api/endpoints/chamados.py` (`listar_chamados`, `buscar_chamado`)

**Interfaces:**
- Consumes: `calcular_sla` (Task 3), `SLAInfo` (Task 2)
- Produces: `ChamadoResponse.sla: Optional[SLAInfo]` — é o que todo o frontend consome.

- [ ] **Step 1: Adicionar o campo no schema**

Modify `app/schemas/chamado.py`: adicionar o import e o campo em `ChamadoResponse` (antes de `model_config`).

```python
from app.schemas.sla import SLAInfo
```

```python
    sla: Optional[SLAInfo] = None
```

- [ ] **Step 2: Escrever o enriquecedor**

Modify `app/api/endpoints/chamados.py`. Adicionar aos imports:

```python
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.services.sla_service import calcular_sla
```

E adicionar esta função logo abaixo de `router = APIRouter()`:

```python
def _anexar_sla(chamados: List[Chamado], db: Session) -> List[Chamado]:
    """
    Calcula e anexa o bloco `sla` a cada chamado.

    Duas queries no total (configs + históricos de todos os chamados de uma vez),
    para não cair em N+1 na listagem.
    """
    if not chamados:
        return chamados

    configs = {c.prioridade: c for c in db.query(SLAConfig).all()}

    ids = [c.id for c in chamados]
    historicos_por_chamado: dict[int, list] = {i: [] for i in ids}
    historicos = (
        db.query(HistoricoChamado)
        .filter(HistoricoChamado.chamado_id.in_(ids))
        .all()
    )
    for h in historicos:
        historicos_por_chamado[h.chamado_id].append(h)

    for chamado in chamados:
        chamado.sla = calcular_sla(
            chamado=chamado,
            historicos=historicos_por_chamado.get(chamado.id, []),
            config=configs.get(chamado.prioridade),
        )

    return chamados
```

- [ ] **Step 3: Ligar nos dois endpoints**

Em `listar_chamados`, trocar o retorno:

```python
    chamados = query.order_by(Chamado.id.desc()).offset(skip).limit(limit).all()
    return _anexar_sla(chamados, db)
```

Em `buscar_chamado`, trocar o retorno:

```python
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")
    return _anexar_sla([chamado], db)[0]
```

- [ ] **Step 4: Verificar com a API rodando**

```bash
docker restart chamadoshs_api_debug && sleep 6
curl -s "http://localhost:8001/api/v1/chamados/?limit=3" | python3 -m json.tool | head -40
```

Expected: cada chamado traz um bloco `"sla"` com `prazo_resolucao`, `percentual_resolucao` e `situacao` preenchidos. Chamados antigos (abertos há muito tempo e nunca resolvidos) devem aparecer como `"Estourado"` — isso é esperado e correto.

- [ ] **Step 5: Commit**

```bash
git add app/schemas/chamado.py app/api/endpoints/chamados.py
git commit -m "feat(sla): expor bloco sla no ChamadoResponse"
```

---

### Task 5: Endpoint de configuração dos prazos

**Files:**
- Create: `app/api/endpoints/sla_configs.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `SLAConfig` (Task 2), `SLAConfigResponse`, `SLAConfigUpdate`
- Produces: `GET /api/v1/sla-configs/` e `PUT /api/v1/sla-configs/{prioridade}`

- [ ] **Step 1: Criar o endpoint**

Create `app/api/endpoints/sla_configs.py`:

```python
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.sla_config import SLAConfig
from app.schemas.sla import SLAConfigResponse, SLAConfigUpdate

router = APIRouter()


@router.get("/", response_model=List[SLAConfigResponse])
def listar_sla_configs(db: Session = Depends(get_db)):
    """Lista os prazos de SLA de todas as prioridades."""
    return db.query(SLAConfig).order_by(SLAConfig.minutos_resolucao.desc()).all()


@router.put("/{prioridade}", response_model=SLAConfigResponse)
def atualizar_sla_config(
    prioridade: str,
    dados: SLAConfigUpdate,
    db: Session = Depends(get_db),
):
    """Atualiza os prazos de uma prioridade."""
    config = db.query(SLAConfig).filter(SLAConfig.prioridade == prioridade).first()
    if not config:
        raise HTTPException(status_code=404, detail="Prioridade não encontrada")

    config.minutos_resposta = dados.minutos_resposta
    config.minutos_resolucao = dados.minutos_resolucao

    db.commit()
    db.refresh(config)
    return config
```

- [ ] **Step 2: Registrar o router**

Modify `main.py` — adicionar `sla_configs` ao import de endpoints:

```python
from app.api.endpoints import auth, chamados, usuarios, comentarios, setores, categorias, historico, diagnostico, sla_configs
```

E registrar o router junto dos outros:

```python
app.include_router(
    sla_configs.router,
    prefix="/api/v1/sla-configs",
    tags=["SLA"]
)
```

- [ ] **Step 3: Verificar**

```bash
docker restart chamadoshs_api_debug && sleep 6
curl -s http://localhost:8001/api/v1/sla-configs/ | python3 -m json.tool
curl -s -X PUT http://localhost:8001/api/v1/sla-configs/Alta \
  -H 'Content-Type: application/json' \
  -d '{"minutos_resposta": 60, "minutos_resolucao": 300}' | python3 -m json.tool
```

Expected: o GET lista as 4 prioridades; o PUT devolve a Alta com `minutos_resolucao: 300`.
**Depois do teste, reverter a Alta para 240** com outro PUT.

- [ ] **Step 4: Commit**

```bash
git add app/api/endpoints/sla_configs.py main.py
git commit -m "feat(sla): endpoint de configuracao dos prazos"
```

---

### Task 6: Corrigir o delete de categoria

Hoje o `DELETE` faz soft delete (`ativo = false`), mas a lista da tela carrega todas as categorias (sem filtro `ativo`), então a categoria "excluída" reaparece no reload. O frontend **já** trata um 400 "categoria com chamados vinculados" que o backend nunca emitiu.

**Files:**
- Modify: `app/api/endpoints/categorias.py:75-86`

**Interfaces:**
- Produces: `DELETE /api/v1/categorias/{id}` → 204 quando apaga, 400 quando há vínculo.

- [ ] **Step 1: Reescrever o delete**

Modify `app/api/endpoints/categorias.py` — adicionar o import do modelo de chamado:

```python
from app.models.chamado import Chamado
```

E substituir toda a função `deletar_categoria` por:

```python
@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_categoria(categoria_id: int, db: Session = Depends(get_db)):
    """
    Exclui uma categoria.

    Só apaga se nenhum chamado estiver vinculado a ela — caso contrário devolve 400,
    porque apagar quebraria o histórico dos chamados (FK chamados.categoria_id).
    """
    categoria = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    vinculados = db.query(Chamado).filter(Chamado.categoria_id == categoria_id).count()
    if vinculados > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível excluir categoria com {vinculados} chamado(s) vinculado(s)",
        )

    db.delete(categoria)
    db.commit()
    return None
```

- [ ] **Step 2: Verificar os dois caminhos**

```bash
docker restart chamadoshs_api_debug && sleep 6

# Caminho A: categoria SEM chamados -> deve apagar (204) e sumir da listagem
NOVA=$(curl -s -X POST http://localhost:8001/api/v1/categorias/ \
  -H 'Content-Type: application/json' -d '{"nome":"Descartavel"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
curl -s -o /dev/null -w 'DELETE sem vinculo -> HTTP %{http_code}\n' \
  -X DELETE http://localhost:8001/api/v1/categorias/$NOVA
curl -s http://localhost:8001/api/v1/categorias/ | grep -c Descartavel

# Caminho B: categoria COM chamados -> deve barrar (400) com a contagem
EM_USO=$(curl -s http://localhost:8001/api/v1/chamados/?limit=1 \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["categoria_id"])')
curl -s -w '\nHTTP %{http_code}\n' -X DELETE http://localhost:8001/api/v1/categorias/$EM_USO
```

Expected:
- Caminho A: `HTTP 204`, e o `grep -c` devolve `0` (a categoria sumiu de verdade).
- Caminho B: `HTTP 400` com `{"detail":"Não é possível excluir categoria com N chamado(s) vinculado(s)"}`.

- [ ] **Step 3: Commit**

```bash
git add app/api/endpoints/categorias.py
git commit -m "fix(categorias): delete real com trava de vinculo em vez de soft delete invisivel"
```

---

### Task 7: Tipos e serviço de SLA no frontend

**Files:**
- Modify: `src/types/api.ts`
- Modify: `src/services/chamadoshsapi.ts`

**Interfaces:**
- Consumes: o bloco `sla` do `ChamadoResponse` (Task 4) e `/sla-configs/` (Task 5)
- Produces: tipos `SLASituacao`, `SLAInfo`, `SLAConfig`; `Chamado.sla`; `slaConfigsService.listar()` / `.atualizar()`

- [ ] **Step 1: Adicionar os tipos**

Modify `src/types/api.ts` — adicionar antes da interface `Chamado`:

```typescript
// SLA
export type SLASituacao = 'No prazo' | 'Atenção' | 'Estourado';

export interface SLAInfo {
  prazo_resposta: string | null;
  prazo_resolucao: string | null;
  minutos_resposta_consumidos: number;
  minutos_resolucao_consumidos: number;
  minutos_pausados: number;
  percentual_resolucao: number;
  situacao: SLASituacao;
  resposta_cumprida: boolean;
}

export interface SLAConfig {
  prioridade: PrioridadeEnum;
  minutos_resposta: number;
  minutos_resolucao: number;
}
```

E adicionar o campo dentro da interface `Chamado`:

```typescript
  sla?: SLAInfo;
```

- [ ] **Step 2: Adicionar o serviço**

Modify `src/services/chamadoshsapi.ts` — importar `SLAConfig` junto dos outros tipos e adicionar o serviço antes do export default:

```typescript
// ============================================
// SERVIÇO DE CONFIGURAÇÃO DE SLA
// ============================================

export const slaConfigsService = {
  /**
   * Lista os prazos de SLA de todas as prioridades
   */
  async listar(): Promise<SLAConfig[]> {
    const response = await api.get<SLAConfig[]>('/sla-configs/');
    return response.data;
  },

  /**
   * Atualiza os prazos de uma prioridade
   */
  async atualizar(
    prioridade: string,
    dados: { minutos_resposta: number; minutos_resolucao: number }
  ): Promise<SLAConfig> {
    const response = await api.put<SLAConfig>(
      `/sla-configs/${encodeURIComponent(prioridade)}`,
      dados
    );
    return response.data;
  },
};
```

E incluir `slaConfigs: slaConfigsService,` no objeto `chamadosHSApi`.

**Atenção:** o `encodeURIComponent` não é opcional — as prioridades têm acento (`Média`, `Crítica`) e vão na URL.

- [ ] **Step 3: Verificar que compila**

```bash
cd ~/github/chamadoshs-sistema && npm run build
```

Expected: `✓ built in ...` sem erros de TypeScript.

- [ ] **Step 4: Commit**

```bash
git add src/types/api.ts src/services/chamadoshsapi.ts
git commit -m "feat(sla): tipos e servico de configuracao de SLA"
```

---

### Task 8: Badge de SLA nos chamados

**Files:**
- Create: `src/components/SlaBadge.tsx`
- Modify: `src/components/KanbanColumn.tsx`
- Modify: `src/pages/ChamadoDetalhes.tsx`

**Interfaces:**
- Consumes: `SLAInfo` (Task 7)
- Produces: `<SlaBadge sla={chamado.sla} />` — usado no card e no detalhe.

- [ ] **Step 1: Criar o badge**

Create `src/components/SlaBadge.tsx`:

```typescript
import React from 'react';
import { SLAInfo } from '../types/api';

interface SlaBadgeProps {
  sla?: SLAInfo;
  /** Versão compacta (sem percentual), para os cards do kanban */
  compacto?: boolean;
}

const ESTILOS: Record<string, string> = {
  'No prazo':
    'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  'Atenção':
    'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
  'Estourado':
    'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
};

const formatarPrazo = (prazo: string | null): string => {
  if (!prazo) return 'sem prazo definido';
  return new Date(prazo).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const SlaBadge: React.FC<SlaBadgeProps> = ({ sla, compacto = false }) => {
  if (!sla) return null;

  const estilo = ESTILOS[sla.situacao] ?? ESTILOS['No prazo'];
  const titulo = `Prazo de resolução: ${formatarPrazo(sla.prazo_resolucao)} · ${sla.percentual_resolucao}% consumido${
    sla.minutos_pausados > 0 ? ` · ${sla.minutos_pausados} min pausados em Aguardando` : ''
  }`;

  return (
    <span
      title={titulo}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${estilo}`}
    >
      {sla.situacao}
      {!compacto && ` · ${sla.percentual_resolucao}%`}
    </span>
  );
};

export default SlaBadge;
```

- [ ] **Step 2: Colocar no card do kanban**

Modify `src/components/KanbanColumn.tsx` — importar o badge:

```typescript
import SlaBadge from './SlaBadge';
```

E renderizar logo abaixo do badge de prioridade (perto da linha 80, onde `{chamado.prioridade}` é exibido), dentro do mesmo container de badges:

```typescript
<SlaBadge sla={chamado.sla} compacto />
```

- [ ] **Step 3: Colocar no detalhe do chamado**

Modify `src/pages/ChamadoDetalhes.tsx` — importar o badge:

```typescript
import SlaBadge from '../components/SlaBadge';
```

E exibir a versão completa junto das informações do chamado (ao lado do status/prioridade):

```typescript
<SlaBadge sla={chamado?.sla} />
```

- [ ] **Step 4: Verificar no navegador**

```bash
cd ~/github/chamadoshs-sistema
npm run build    # precisa passar sem erro de tipo
```

Depois, com a API local rodando na 8001, subir o front apontando pra ela e conferir visualmente que os cards mostram o badge colorido:

```bash
VITE_API_URL=http://localhost:8001 npm run dev
```

Expected: os cards do kanban mostram badge verde/amarelo/vermelho; passar o mouse mostra o tooltip com o prazo.

- [ ] **Step 5: Commit**

```bash
git add src/components/SlaBadge.tsx src/components/KanbanColumn.tsx src/pages/ChamadoDetalhes.tsx
git commit -m "feat(sla): badge de SLA nos cards e no detalhe do chamado"
```

---

### Task 9: Métricas de SLA no Dashboard

**Files:**
- Modify: `src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: `chamado.sla` (Task 7)
- Produces: bloco visual de métricas. Denominadores explícitos (ver Global Constraints do spec).

- [ ] **Step 1: Calcular as métricas**

Modify `src/pages/Dashboard.tsx` — adicionar este `useMemo` junto dos outros cálculos de métricas (perto da linha 111, na seção "CÁLCULO DE MÉTRICAS"):

```typescript
  // Métricas de SLA
  const metricasSla = useMemo(() => {
    const resolvidos = chamados.filter(
      (c) => c.status === StatusEnum.RESOLVIDO || c.status === StatusEnum.FECHADO
    );
    const emAberto = chamados.filter(
      (c) => c.status !== StatusEnum.RESOLVIDO && c.status !== StatusEnum.FECHADO
    );

    // % dentro do SLA: entre os JÁ RESOLVIDOS, quantos fecharam sem estourar
    const resolvidosNoPrazo = resolvidos.filter(
      (c) => c.sla && c.sla.situacao !== 'Estourado'
    ).length;

    const percentualNoPrazo =
      resolvidos.length > 0
        ? Math.round((resolvidosNoPrazo / resolvidos.length) * 100)
        : 100;

    // Estourados em aberto: a dor de agora
    const estouradosEmAberto = emAberto.filter(
      (c) => c.sla?.situacao === 'Estourado'
    ).length;

    const emAtencao = emAberto.filter((c) => c.sla?.situacao === 'Atenção').length;

    return {
      percentualNoPrazo,
      totalResolvidos: resolvidos.length,
      estouradosEmAberto,
      emAtencao,
    };
  }, [chamados]);
```

- [ ] **Step 2: Renderizar o bloco**

Modify `src/pages/Dashboard.tsx` — adicionar a seção logo abaixo dos cards de métricas existentes:

```typescript
      {/* ======================================== */}
      {/* MÉTRICAS DE SLA                          */}
      {/* ======================================== */}
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          SLA
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Resolvidos dentro do prazo
            </p>
            <p className="text-3xl font-bold text-green-600 dark:text-green-400">
              {metricasSla.percentualNoPrazo}%
            </p>
            <p className="text-xs text-gray-400">
              de {metricasSla.totalResolvidos} chamado(s) resolvido(s)
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Estourados em aberto
            </p>
            <p className="text-3xl font-bold text-red-600 dark:text-red-400">
              {metricasSla.estouradosEmAberto}
            </p>
            <p className="text-xs text-gray-400">precisam de ação agora</p>
          </div>
          <div>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Em atenção (≥80% do prazo)
            </p>
            <p className="text-3xl font-bold text-yellow-600 dark:text-yellow-400">
              {metricasSla.emAtencao}
            </p>
            <p className="text-xs text-gray-400">prestes a estourar</p>
          </div>
        </div>
      </div>
```

- [ ] **Step 3: Verificar**

```bash
cd ~/github/chamadoshs-sistema && npm run build
```

Expected: build passa. No navegador (`VITE_API_URL=http://localhost:8001 npm run dev`), o Dashboard mostra os três números e eles batem com o que os badges do kanban mostram.

- [ ] **Step 4: Commit**

```bash
git add src/pages/Dashboard.tsx
git commit -m "feat(sla): metricas de SLA no dashboard"
```

---

### Task 10: Aba de configuração dos prazos

**Files:**
- Create: `src/components/cadastros/SlaTab.tsx`
- Modify: `src/pages/CadastrosBasicos.tsx`

**Interfaces:**
- Consumes: `slaConfigsService` (Task 7), `SLAConfig`
- Produces: aba "SLA" em Cadastros Básicos, visível só para Administrador.

- [ ] **Step 1: Criar a aba**

Create `src/components/cadastros/SlaTab.tsx`:

```typescript
import React, { useEffect, useState } from 'react';
import { slaConfigsService } from '../../services/chamadoshsapi';
import { SLAConfig } from '../../types/api';

/** Converte minutos úteis em algo legível (8h úteis/dia). */
const formatarMinutos = (minutos: number): string => {
  if (minutos < 60) return `${minutos} min`;
  const horas = minutos / 60;
  if (minutos % 480 === 0) {
    const dias = minutos / 480;
    return `${horas}h úteis (${dias} dia${dias > 1 ? 's' : ''} útil${dias > 1 ? 'eis' : ''})`;
  }
  return `${horas}h úteis`;
};

const SlaTab: React.FC = () => {
  const [configs, setConfigs] = useState<SLAConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState<string | null>(null);

  const carregar = async () => {
    try {
      setLoading(true);
      setConfigs(await slaConfigsService.listar());
      setErro(null);
    } catch {
      setErro('Não foi possível carregar os prazos de SLA.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    carregar();
  }, []);

  const alterarCampo = (
    prioridade: string,
    campo: 'minutos_resposta' | 'minutos_resolucao',
    valor: number
  ) => {
    setConfigs((prev) =>
      prev.map((c) => (c.prioridade === prioridade ? { ...c, [campo]: valor } : c))
    );
  };

  const salvar = async (config: SLAConfig) => {
    try {
      setSalvando(config.prioridade);
      setErro(null);
      await slaConfigsService.atualizar(config.prioridade, {
        minutos_resposta: config.minutos_resposta,
        minutos_resolucao: config.minutos_resolucao,
      });
    } catch {
      setErro(`Erro ao salvar os prazos de ${config.prioridade}.`);
      await carregar();
    } finally {
      setSalvando(null);
    }
  };

  if (loading) {
    return <p className="text-gray-500 dark:text-gray-400">Carregando prazos...</p>;
  }

  return (
    <div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        Prazos em <strong>minutos úteis</strong>. O relógio só corre de seg a sex, das 8h às
        17h, com pausa de 12h às 13h — ou seja, <strong>1 dia útil = 480 minutos</strong>.
        Alterar um prazo recalcula o SLA de todos os chamados, inclusive os antigos.
      </p>

      {erro && (
        <div className="mb-4 p-3 rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
          {erro}
        </div>
      )}

      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-gray-200 dark:border-gray-700">
            <th className="py-2 text-sm text-gray-600 dark:text-gray-300">Prioridade</th>
            <th className="py-2 text-sm text-gray-600 dark:text-gray-300">Resposta (min)</th>
            <th className="py-2 text-sm text-gray-600 dark:text-gray-300">Resolução (min)</th>
            <th className="py-2 text-sm text-gray-600 dark:text-gray-300"></th>
          </tr>
        </thead>
        <tbody>
          {configs.map((config) => (
            <tr
              key={config.prioridade}
              className="border-b border-gray-100 dark:border-gray-700"
            >
              <td className="py-3 font-medium text-gray-900 dark:text-white">
                {config.prioridade}
              </td>
              <td className="py-3">
                <input
                  type="number"
                  min={1}
                  value={config.minutos_resposta}
                  onChange={(e) =>
                    alterarCampo(config.prioridade, 'minutos_resposta', Number(e.target.value))
                  }
                  className="w-24 px-2 py-1 border rounded dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                />
                <span className="ml-2 text-xs text-gray-400">
                  {formatarMinutos(config.minutos_resposta)}
                </span>
              </td>
              <td className="py-3">
                <input
                  type="number"
                  min={1}
                  value={config.minutos_resolucao}
                  onChange={(e) =>
                    alterarCampo(config.prioridade, 'minutos_resolucao', Number(e.target.value))
                  }
                  className="w-24 px-2 py-1 border rounded dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                />
                <span className="ml-2 text-xs text-gray-400">
                  {formatarMinutos(config.minutos_resolucao)}
                </span>
              </td>
              <td className="py-3">
                <button
                  onClick={() => salvar(config)}
                  disabled={salvando === config.prioridade}
                  className="px-3 py-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded"
                >
                  {salvando === config.prioridade ? 'Salvando...' : 'Salvar'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default SlaTab;
```

- [ ] **Step 2: Registrar a aba**

Modify `src/types/cadastros.types.ts` — adicionar `'sla'` à união do tipo `TipoAba`
(hoje é `'categorias' | 'setores' | 'usuarios'`):

```typescript
export type TipoAba = 'categorias' | 'setores' | 'usuarios' | 'sla';
```

Modify `src/pages/CadastrosBasicos.tsx`:

1. Adicionar `Clock` ao import de ícones (a linha já importa de `lucide-react`):

```typescript
import { Settings, Tag, Building, Users, Clock } from 'lucide-react';
```

2. Importar a aba:

```typescript
import SlaTab from '../components/cadastros/SlaTab';
```

3. Adicionar a permissão junto de `podeVerUsuarios`:

```typescript
  const podeVerSla = user?.role === 'Administrador';
```

4. Adicionar a entrada como **último item** do array `abas`:

```typescript
    {
      id: 'sla',
      label: 'SLA',
      icon: <Clock className="w-4 h-4" />,
      component: <SlaTab />,
      visible: podeVerSla,
    },
```

- [ ] **Step 3: Verificar**

```bash
cd ~/github/chamadoshs-sistema && npm run build
```

Expected: build passa. No navegador, a aba "SLA" aparece em Cadastros Básicos (logado como Administrador), lista as 4 prioridades com os prazos, e salvar um valor persiste após recarregar a página.

- [ ] **Step 4: Commit**

```bash
git add src/components/cadastros/SlaTab.tsx src/pages/CadastrosBasicos.tsx
git commit -m "feat(sla): aba de configuracao dos prazos em cadastros basicos"
```

---

### Task 11: Verificação ponta a ponta e limpeza

**Files:** nenhum (só verificação)

- [ ] **Step 1: Exercitar o fluxo real**

Com a stack local rodando, criar um chamado Crítico, movê-lo para "Aguardando", esperar, tirar de "Aguardando" e resolver. Conferir que:

1. O badge muda de cor conforme o prazo é consumido.
2. Os minutos em "Aguardando" aparecem no tooltip e **não** contam contra o SLA.
3. O Dashboard reflete o chamado resolvido no `% dentro do prazo`.

```bash
docker exec chamadoshs_pg_debug psql -U postgres -d chamados_db -c \
  "SELECT id, protocolo, prioridade, status, data_abertura FROM chamados ORDER BY id DESC LIMIT 5;"
curl -s "http://localhost:8001/api/v1/chamados/?limit=5" \
  | python3 -c "
import sys, json
for c in json.load(sys.stdin):
    s = c['sla']
    print(f\"{c['protocolo']:<12} {c['prioridade']:<8} {c['status']:<12} \"
          f\"{s['situacao']:<10} {s['percentual_resolucao']:>4}% pausado={s['minutos_pausados']}min\")
"
```

Expected: a coluna `situacao` é coerente com o percentual (>100% → Estourado, ≥80% → Atenção), e o chamado que passou por "Aguardando" mostra `pausado > 0`.

- [ ] **Step 2: Derrubar a stack de debug**

```bash
cd ~/github/chamadoshs-api
docker compose -p chamadosdebug \
  -f docker-compose.yml \
  -f /tmp/claude-1000/-home-ericks/b81285d3-e320-4160-875d-6901ef879c00/scratchpad/chamados-override.yml \
  down -v
docker ps    # confirmar que só o taskhs-backend-1 continua de pé
```

Expected: nenhum container `chamadoshs_*_debug` sobrando, e o TaskHS intacto na porta 8000.

- [ ] **Step 3: Lembrete de deploy**

O deploy tem que ser dos **dois** repos e o backend primeiro — o frontend novo espera o campo `sla` e o endpoint `/sla-configs/`, que só existem depois de a API subir. **A migração `migrations/add_sla_configs.sql` precisa ser aplicada no banco de produção antes de a API nova subir**, senão todo `GET /chamados/` quebra ao consultar a tabela inexistente.

---

## Notas de execução

- **Ordem importa.** Tasks 1→2→3→4 são uma cadeia: o motor sustenta o serviço, que sustenta o endpoint. As Tasks 5 e 6 são independentes entre si. As Tasks 7→8/9/10 dependem do backend estar de pé.
- **A Task 6 (delete de categoria) é independente de todo o resto** e pode ser feita/entregue sozinha se você quiser o fix mais cedo.
- Nenhum commit é enviado (`push`) sem autorização do Erick.
