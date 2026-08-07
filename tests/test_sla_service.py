"""
Testes das regras de SLA.

Sem banco: `calcular_sla` só lê atributos, então objetos simples bastam e o
teste fica legível. O instante "agora" é sempre passado explicitamente — a
função aceita o parâmetro justamente para não depender do relógio.

Datas de referência (mesma semana usada em test_horario_util):
    2026-08-03 segunda ... 2026-08-07 sexta, 2026-08-08 sábado
Expediente: 08:00-12:00 e 13:00-17:00.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.sla_service import PERCENTUAL_ATENCAO, calcular_sla

SEG = datetime(2026, 8, 3)


def em(dia: datetime, hora: int, minuto: int = 0) -> datetime:
    return dia.replace(hour=hora, minute=minuto)


def chamado(**kwargs):
    padrao = dict(
        data_abertura=em(SEG, 8),
        status="Aberto",
        cancelado=False,
        data_resolucao=None,
        data_atualizacao=None,
    )
    padrao.update(kwargs)
    return SimpleNamespace(**padrao)


def config(minutos_resolucao=480, minutos_resposta=60):
    return SimpleNamespace(
        minutos_resolucao=minutos_resolucao,
        minutos_resposta=minutos_resposta,
    )


def historico(created_at, status_novo=None, status_anterior=None):
    return SimpleNamespace(
        created_at=created_at,
        status_novo=status_novo,
        status_anterior=status_anterior,
    )


# ---------------------------------------------------------------------------
# Quando não há SLA aplicável
# ---------------------------------------------------------------------------

def test_sem_config_devolve_none():
    """
    Devolver None em vez de "No prazo" é deliberado: não se pode afirmar que
    está no prazo algo que não está sendo medido.
    """
    assert calcular_sla(chamado(), [], None, agora=em(SEG, 10)) is None


def test_sem_data_abertura_devolve_none():
    assert calcular_sla(chamado(data_abertura=None), [], config(), agora=em(SEG, 10)) is None


def test_cancelado_devolve_none():
    """Cancelamento não tem obrigação de SLA."""
    c = chamado(cancelado=True)
    assert calcular_sla(c, [], config(), agora=em(SEG, 10)) is None


def test_config_com_prazo_zero_devolve_none():
    """Evita divisão por zero no cálculo do percentual."""
    assert calcular_sla(chamado(), [], config(minutos_resolucao=0), agora=em(SEG, 10)) is None


# ---------------------------------------------------------------------------
# Situação pelo relógio de resolução
# ---------------------------------------------------------------------------

def test_no_prazo():
    sla = calcular_sla(chamado(), [], config(minutos_resolucao=480), agora=em(SEG, 10))
    assert sla["minutos_resolucao_consumidos"] == 120
    assert sla["percentual_resolucao"] == 25
    assert sla["situacao"] == "No prazo"


def test_atencao_a_partir_do_limiar():
    """
    80% de 480 são 384 minutos úteis. A partir das 08:00: 240 até o almoço e
    144 depois das 13:00, ou seja, 15:24.
    """
    sla = calcular_sla(chamado(), [], config(minutos_resolucao=480), agora=em(SEG, 15, 24))
    assert sla["minutos_resolucao_consumidos"] == 384
    assert sla["percentual_resolucao"] == PERCENTUAL_ATENCAO
    assert sla["situacao"] == "Atenção"


def test_logo_abaixo_do_limiar_ainda_e_no_prazo():
    agora = em(SEG, 14, 20)  # 380 min úteis -> 79%
    sla = calcular_sla(chamado(), [], config(minutos_resolucao=480), agora=agora)
    assert sla["situacao"] == "No prazo"


def test_exatamente_no_prazo_nao_estoura():
    """Consumir todo o prazo ainda não é furo; furo é ultrapassar."""
    sla = calcular_sla(chamado(), [], config(minutos_resolucao=480), agora=em(SEG, 17))
    assert sla["minutos_resolucao_consumidos"] == 480
    assert sla["percentual_resolucao"] == 100
    assert sla["situacao"] == "Atenção"


def test_estourado():
    agora = em(SEG + timedelta(days=1), 9)  # 480 + 60
    sla = calcular_sla(chamado(), [], config(minutos_resolucao=480), agora=agora)
    assert sla["minutos_resolucao_consumidos"] == 540
    assert sla["situacao"] == "Estourado"


def test_tempo_fora_do_expediente_nao_consome_prazo():
    """Aberto às 16h, consultado às 22h: só a hora até as 17h conta."""
    c = chamado(data_abertura=em(SEG, 16))
    sla = calcular_sla(c, [], config(), agora=em(SEG, 22))
    assert sla["minutos_resolucao_consumidos"] == 60


def test_prazo_de_resolucao_cai_em_horario_util():
    sla = calcular_sla(chamado(), [], config(minutos_resolucao=60), agora=em(SEG, 9))
    assert sla["prazo_resolucao"] == em(SEG, 9)
    assert sla["prazo_resposta"] == em(SEG, 9)


# ---------------------------------------------------------------------------
# Pausas em "Aguardando"
# ---------------------------------------------------------------------------

def test_periodo_aguardando_e_descontado():
    """
    Aberto 08:00, em Aguardando das 09:00 às 11:00, consultado 12:00.
    Decorridos 240 min úteis, 120 pausados, logo 120 consumidos.
    """
    historicos = [
        historico(em(SEG, 9), status_novo="Aguardando", status_anterior="Aberto"),
        historico(em(SEG, 11), status_novo="Em Andamento", status_anterior="Aguardando"),
    ]
    sla = calcular_sla(chamado(), historicos, config(), agora=em(SEG, 12))
    assert sla["minutos_pausados"] == 120
    assert sla["minutos_resolucao_consumidos"] == 120


def test_pausa_estende_o_prazo():
    """O prazo se estende pelo tempo parado esperando terceiros."""
    historicos = [
        historico(em(SEG, 9), status_novo="Aguardando", status_anterior="Aberto"),
        historico(em(SEG, 11), status_novo="Em Andamento", status_anterior="Aguardando"),
    ]
    sem_pausa = calcular_sla(chamado(), [], config(minutos_resolucao=240), agora=em(SEG, 12))
    com_pausa = calcular_sla(chamado(), historicos, config(minutos_resolucao=240), agora=em(SEG, 12))
    assert com_pausa["prazo_resolucao"] > sem_pausa["prazo_resolucao"]


def test_pausa_ainda_aberta_conta_ate_agora():
    historicos = [
        historico(em(SEG, 9), status_novo="Aguardando", status_anterior="Aberto"),
    ]
    sla = calcular_sla(chamado(status="Aguardando"), historicos, config(), agora=em(SEG, 11))
    assert sla["minutos_pausados"] == 120
    assert sla["minutos_resolucao_consumidos"] == 60  # 08:00 -> 09:00


def test_multiplas_pausas_somam():
    historicos = [
        historico(em(SEG, 9), status_novo="Aguardando", status_anterior="Aberto"),
        historico(em(SEG, 10), status_novo="Em Andamento", status_anterior="Aguardando"),
        historico(em(SEG, 14), status_novo="Aguardando", status_anterior="Em Andamento"),
        historico(em(SEG, 15), status_novo="Em Andamento", status_anterior="Aguardando"),
    ]
    sla = calcular_sla(chamado(), historicos, config(), agora=em(SEG, 16))
    assert sla["minutos_pausados"] == 120


def test_pausa_fora_do_expediente_nao_conta():
    """Pausa iniciada às 18h e encerrada às 20h não desconta nada."""
    historicos = [
        historico(em(SEG, 18), status_novo="Aguardando", status_anterior="Aberto"),
        historico(em(SEG, 20), status_novo="Em Andamento", status_anterior="Aguardando"),
    ]
    sla = calcular_sla(chamado(), historicos, config(), agora=em(SEG, 20))
    assert sla["minutos_pausados"] == 0


def test_consumido_nunca_fica_negativo():
    """Pausa mais longa que o decorrido não pode gerar consumo negativo."""
    historicos = [
        historico(em(SEG, 8), status_novo="Aguardando", status_anterior="Aberto"),
    ]
    sla = calcular_sla(chamado(status="Aguardando"), historicos, config(), agora=em(SEG, 12))
    assert sla["minutos_resolucao_consumidos"] == 0


# ---------------------------------------------------------------------------
# Relógio de resposta
# ---------------------------------------------------------------------------

def test_resposta_conta_ate_a_primeira_saida_de_aberto():
    historicos = [
        historico(em(SEG, 8, 30), status_novo="Em Andamento", status_anterior="Aberto"),
        historico(em(SEG, 11), status_novo="Aguardando", status_anterior="Em Andamento"),
    ]
    sla = calcular_sla(chamado(), historicos, config(minutos_resposta=60), agora=em(SEG, 16))
    assert sla["minutos_resposta_consumidos"] == 30
    assert sla["resposta_cumprida"] is True


def test_resposta_furada():
    historicos = [
        historico(em(SEG, 11), status_novo="Em Andamento", status_anterior="Aberto"),
    ]
    sla = calcular_sla(chamado(), historicos, config(minutos_resposta=60), agora=em(SEG, 16))
    assert sla["minutos_resposta_consumidos"] == 180
    assert sla["resposta_cumprida"] is False


def test_resposta_no_limite_e_cumprida():
    historicos = [
        historico(em(SEG, 9), status_novo="Em Andamento", status_anterior="Aberto"),
    ]
    sla = calcular_sla(chamado(), historicos, config(minutos_resposta=60), agora=em(SEG, 16))
    assert sla["minutos_resposta_consumidos"] == 60
    assert sla["resposta_cumprida"] is True


def test_situacao_reflete_resolucao_e_nao_resposta():
    """
    Regra explícita do módulo: `situacao` é sempre o relógio de resolução; o
    furo de resposta aparece separado em `resposta_cumprida`.
    """
    historicos = [
        historico(em(SEG, 11), status_novo="Em Andamento", status_anterior="Aberto"),
    ]
    sla = calcular_sla(
        chamado(), historicos, config(minutos_resolucao=480, minutos_resposta=10), agora=em(SEG, 10)
    )
    assert sla["resposta_cumprida"] is False
    assert sla["situacao"] == "No prazo"


def test_sem_saida_de_aberto_a_resposta_corre_ate_agora():
    sla = calcular_sla(chamado(), [], config(minutos_resposta=60), agora=em(SEG, 11))
    assert sla["minutos_resposta_consumidos"] == 180
    assert sla["resposta_cumprida"] is False


# ---------------------------------------------------------------------------
# Chamado finalizado
# ---------------------------------------------------------------------------

def test_finalizado_congela_no_momento_da_resolucao():
    """Consultar dias depois não pode aumentar o consumo de um chamado fechado."""
    historicos = [
        historico(em(SEG, 8, 30), status_novo="Em Andamento", status_anterior="Aberto"),
        historico(em(SEG, 10), status_novo="Resolvido", status_anterior="Em Andamento"),
    ]
    c = chamado(status="Resolvido")
    logo_depois = calcular_sla(c, historicos, config(), agora=em(SEG, 11))
    muito_depois = calcular_sla(c, historicos, config(), agora=em(SEG + timedelta(days=5), 11))
    assert logo_depois["minutos_resolucao_consumidos"] == 120
    assert muito_depois["minutos_resolucao_consumidos"] == 120


def test_reabertura_usa_a_ultima_transicao_final():
    """
    Com reabertura, a resolução válida é a mais recente. Usar a primeira
    subestimaria o tempo real de atendimento.
    """
    historicos = [
        historico(em(SEG, 10), status_novo="Resolvido", status_anterior="Em Andamento"),
        historico(em(SEG, 11), status_novo="Aberto", status_anterior="Resolvido"),
        historico(em(SEG, 15), status_novo="Resolvido", status_anterior="Em Andamento"),
    ]
    sla = calcular_sla(chamado(status="Resolvido"), historicos, config(), agora=em(SEG, 16))
    assert sla["minutos_resolucao_consumidos"] == 360  # 08:00 -> 15:00


def test_finalizado_sem_historico_usa_data_resolucao():
    """Fallback para chamados legados, anteriores ao registro de histórico."""
    c = chamado(status="Fechado", data_resolucao=em(SEG, 10))
    sla = calcular_sla(c, [], config(), agora=em(SEG + timedelta(days=3), 10))
    assert sla["minutos_resolucao_consumidos"] == 120


def test_finalizado_sem_historico_e_sem_data_resolucao_usa_data_atualizacao():
    c = chamado(status="Fechado", data_resolucao=None, data_atualizacao=em(SEG, 9))
    sla = calcular_sla(c, [], config(), agora=em(SEG + timedelta(days=3), 10))
    assert sla["minutos_resolucao_consumidos"] == 60


@pytest.mark.parametrize("status_final", ["Resolvido", "Fechado"])
def test_ambos_os_status_finais_congelam(status_final):
    historicos = [historico(em(SEG, 10), status_novo=status_final, status_anterior="Em Andamento")]
    sla = calcular_sla(chamado(status=status_final), historicos, config(), agora=em(SEG, 16))
    assert sla["minutos_resolucao_consumidos"] == 120


# ---------------------------------------------------------------------------
# Contrato de saída
# ---------------------------------------------------------------------------

def test_retorno_traz_todas_as_chaves_de_slainfo():
    """O schema SLAInfo do Pydantic exige exatamente estas chaves."""
    sla = calcular_sla(chamado(), [], config(), agora=em(SEG, 10))
    assert set(sla) == {
        "prazo_resposta",
        "prazo_resolucao",
        "minutos_resposta_consumidos",
        "minutos_resolucao_consumidos",
        "minutos_pausados",
        "percentual_resolucao",
        "situacao",
        "resposta_cumprida",
    }


def test_historico_fora_de_ordem_nao_afeta_o_resultado():
    """A função ordena por created_at; a ordem da lista não pode importar."""
    eventos = [
        historico(em(SEG, 9), status_novo="Aguardando", status_anterior="Aberto"),
        historico(em(SEG, 11), status_novo="Em Andamento", status_anterior="Aguardando"),
    ]
    normal = calcular_sla(chamado(), eventos, config(), agora=em(SEG, 12))
    invertido = calcular_sla(chamado(), list(reversed(eventos)), config(), agora=em(SEG, 12))
    assert normal == invertido
