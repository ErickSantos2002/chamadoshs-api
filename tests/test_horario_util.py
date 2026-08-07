"""
Testes do motor de horas úteis.

É a base de todo o SLA: erro aqui contamina prazo, percentual e situação de
todos os chamados. Expediente: seg-sex, 08:00-12:00 e 13:00-17:00, 480
minutos por dia útil.

Datas escolhidas de propósito, para o teste falar por si:
    2026-08-03 é uma SEGUNDA
    2026-08-07 é uma SEXTA
    2026-08-08 é um SÁBADO
    2026-08-10 é a SEGUNDA seguinte

Todos os instantes são passados explicitamente. Nenhuma função aqui lê o
relógio, então não há nada a congelar — o único risco de fuso está na
conversão de datetime aware, coberta em test_normalizacao_de_fuso.
"""

from datetime import datetime, timedelta

import pytest
import pytz

from app.services.horario_util import (
    MINUTOS_POR_DIA_UTIL,
    contar_minutos_uteis,
    somar_minutos_uteis,
)

SEG = datetime(2026, 8, 3)
SEX = datetime(2026, 8, 7)
SAB = datetime(2026, 8, 8)
SEG_SEGUINTE = datetime(2026, 8, 10)


def em(dia: datetime, hora: int, minuto: int = 0) -> datetime:
    return dia.replace(hour=hora, minute=minuto)


# ---------------------------------------------------------------------------
# contar_minutos_uteis
# ---------------------------------------------------------------------------

def test_intervalo_dentro_de_uma_janela():
    assert contar_minutos_uteis(em(SEG, 9), em(SEG, 11)) == 120


def test_almoco_nao_conta():
    """Das 11h às 14h existem 3 horas de relógio, mas só 2 de expediente."""
    assert contar_minutos_uteis(em(SEG, 11), em(SEG, 14)) == 120


def test_dia_util_completo_sao_480_minutos():
    assert contar_minutos_uteis(em(SEG, 8), em(SEG, 17)) == MINUTOS_POR_DIA_UTIL


def test_intervalo_maior_que_o_expediente_satura_no_dia():
    """Da meia-noite à meia-noite continua valendo só o expediente."""
    assert contar_minutos_uteis(em(SEG, 0), em(SEG, 23, 59)) == MINUTOS_POR_DIA_UTIL


def test_fora_do_expediente_nao_conta():
    assert contar_minutos_uteis(em(SEG, 18), em(SEG, 22)) == 0
    assert contar_minutos_uteis(em(SEG, 5), em(SEG, 7)) == 0
    assert contar_minutos_uteis(em(SEG, 12, 10), em(SEG, 12, 50)) == 0


def test_fim_de_semana_nao_conta():
    assert contar_minutos_uteis(em(SAB, 8), em(SAB, 17)) == 0


def test_travessia_de_fim_de_semana():
    """Sexta 16h a segunda 9h: 1h na sexta + 1h na segunda."""
    assert contar_minutos_uteis(em(SEX, 16), em(SEG_SEGUINTE, 9)) == 120


def test_semana_inteira():
    assert contar_minutos_uteis(em(SEG, 8), em(SEX, 17)) == 5 * MINUTOS_POR_DIA_UTIL


def test_fim_anterior_ou_igual_ao_inicio_da_zero():
    assert contar_minutos_uteis(em(SEG, 11), em(SEG, 9)) == 0
    assert contar_minutos_uteis(em(SEG, 10), em(SEG, 10)) == 0


def test_normalizacao_de_fuso():
    """
    O container roda em UTC e o sistema opera em Brasília (UTC-3). Um instante
    aware precisa ser convertido antes de virar hora de expediente: 14:00 UTC
    são 11:00 em Brasília, dentro da janela da manhã.
    """
    utc = pytz.UTC
    inicio = utc.localize(datetime(2026, 8, 3, 14, 0))  # 11:00 Brasília
    fim = utc.localize(datetime(2026, 8, 3, 15, 0))     # 12:00 Brasília
    assert contar_minutos_uteis(inicio, fim) == 60

    # 23:00 UTC de segunda são 20:00 de segunda em Brasília: fora do expediente.
    fora = utc.localize(datetime(2026, 8, 3, 23, 0))
    assert contar_minutos_uteis(fora, fora + timedelta(hours=2)) == 0


def test_aware_e_naive_produzem_o_mesmo_resultado():
    naive = contar_minutos_uteis(em(SEG, 9), em(SEG, 11))
    aware = contar_minutos_uteis(
        pytz.timezone("America/Sao_Paulo").localize(em(SEG, 9)),
        pytz.timezone("America/Sao_Paulo").localize(em(SEG, 11)),
    )
    assert naive == aware == 120


# ---------------------------------------------------------------------------
# somar_minutos_uteis
# ---------------------------------------------------------------------------

def test_soma_dentro_da_mesma_janela():
    assert somar_minutos_uteis(em(SEG, 9), 60) == em(SEG, 10)


def test_soma_pula_o_almoco():
    """11:00 + 90 min úteis: 60 até o meio-dia, 30 restantes após as 13h."""
    assert somar_minutos_uteis(em(SEG, 11), 90) == em(SEG, 13, 30)


def test_soma_vira_o_dia():
    """16:00 + 120 min: 60 até as 17h, 60 restantes na manhã seguinte."""
    assert somar_minutos_uteis(em(SEG, 16), 120) == em(SEG + timedelta(days=1), 9)


def test_soma_de_um_dia_util_para_no_fim_do_expediente():
    """
    480 minutos a partir da abertura esgotam exatamente no fechamento do
    mesmo dia. O prazo é 17:00 de segunda, e não 08:00 de terça: as duas
    datas são equivalentes em tempo útil, mas o prazo tem de cair no
    instante em que o orçamento acaba, dentro do expediente.
    """
    assert somar_minutos_uteis(em(SEG, 8), MINUTOS_POR_DIA_UTIL) == em(SEG, 17)


def test_um_minuto_alem_do_dia_util_vira_para_o_dia_seguinte():
    assert somar_minutos_uteis(em(SEG, 8), MINUTOS_POR_DIA_UTIL + 1) == em(
        SEG + timedelta(days=1), 8, 1
    )


def test_soma_atravessa_o_fim_de_semana():
    """Sexta 16h + 120 min: 60 na sexta, o resto só na segunda de manhã."""
    assert somar_minutos_uteis(em(SEX, 16), 120) == em(SEG_SEGUINTE, 9)


@pytest.mark.parametrize(
    "instante,esperado",
    [
        (em(SEG, 6), em(SEG, 8)),               # antes da abertura
        (em(SEG, 12, 30), em(SEG, 13)),         # durante o almoço
        (em(SEG, 20), em(SEG + timedelta(days=1), 8)),  # após o expediente
        (em(SAB, 10), em(SEG_SEGUINTE, 8)),     # fim de semana
    ],
)
def test_inicio_fora_do_expediente_avanca_para_a_proxima_abertura(instante, esperado):
    """Somar zero devolve o próximo instante útil — sem adiantar o relógio."""
    assert somar_minutos_uteis(instante, 0) == esperado


def test_minutos_negativos_nao_retrocedem():
    assert somar_minutos_uteis(em(SEG, 10), -30) == em(SEG, 10)


def test_soma_longa_converge():
    """
    Trava contra regressão no laço: 20 dias úteis a partir de segunda 08:00
    esgotam no fechamento da sexta da quarta semana (2026-08-28).
    """
    resultado = somar_minutos_uteis(em(SEG, 8), 20 * MINUTOS_POR_DIA_UTIL)
    assert resultado == datetime(2026, 8, 28, 17, 0)
    assert resultado.weekday() == 4  # sexta


def test_soma_normaliza_datetime_aware():
    """14:00 UTC = 11:00 Brasília; +60 min úteis = 12:00 Brasília (naive)."""
    inicio = pytz.UTC.localize(datetime(2026, 8, 3, 14, 0))
    assert somar_minutos_uteis(inicio, 60) == em(SEG, 12)


def test_ida_e_volta_entre_somar_e_contar():
    """
    As duas funções precisam concordar: somar N minutos e depois contar o
    intervalo tem de devolver os mesmos N.
    """
    inicio = em(SEG, 9, 15)
    for minutos in (30, 90, 480, 1000, 2400):
        fim = somar_minutos_uteis(inicio, minutos)
        assert contar_minutos_uteis(inicio, fim) == minutos
