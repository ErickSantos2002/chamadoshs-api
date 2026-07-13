"""
Regras de SLA.

- Relógio de RESPOSTA: da abertura até a primeira saída do status "Aberto".
- Relógio de RESOLUÇÃO: da abertura até a resolução, descontando o tempo em "Aguardando".
- `situacao` reflete SEMPRE o relógio de resolução; o furo de resposta vai em
  `resposta_cumprida` separadamente.
- Sem config para a prioridade ou sem `data_abertura`: o chamado não tem SLA
  aplicável e `calcular_sla` devolve `None` (em vez de fingir "No prazo" para
  algo que não está sendo medido).
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
) -> Optional[dict]:
    """
    Calcula o bloco de SLA de um chamado. Devolve as chaves de SLAInfo, ou
    `None` quando não há SLA aplicável: sem config para a prioridade ou sem
    `data_abertura`.
    """
    if config is None or chamado.data_abertura is None:
        return None

    if config.minutos_resolucao <= 0:
        return None

    agora = agora or agora_brasilia()
    abertura = chamado.data_abertura

    # --- Relógio de resolução -------------------------------------------------
    # Chamados Resolvido/Fechado congelam a situação no momento da resolução,
    # mesmo que `data_resolucao` esteja ausente (dados legados/importados).
    esta_finalizado = chamado.status in STATUS_FINAIS
    fim_resolucao = (
        (chamado.data_resolucao or chamado.data_atualizacao or agora)
        if esta_finalizado
        else agora
    )

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
    fim_resposta = _fim_da_resposta(historicos) or fim_resolucao
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
