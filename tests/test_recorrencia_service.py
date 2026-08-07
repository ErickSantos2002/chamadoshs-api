"""
Testes do cálculo da próxima data de tarefas recorrentes.

Invariante central: a próxima data é SEMPRE estritamente depois da base, para
nunca ficar no passado quando a tarefa é realizada com atraso.

Cuidado com a convenção de dia da semana: o parâmetro `dia_semana` usa
0=Domingo..6=Sábado (padrão JavaScript, que é o que o frontend envia), não a
convenção do Python, onde 0=Segunda. A conversão é o ponto mais fácil de
quebrar neste módulo.

Datas de referência:
    2026-08-03 segunda ... 2026-08-09 domingo
"""

from datetime import date

import pytest

from app.services.recorrencia_service import calcular_proxima_data

SEGUNDA = date(2026, 8, 3)
QUARTA = date(2026, 8, 5)
DOMINGO = date(2026, 8, 9)


# ---------------------------------------------------------------------------
# Diária
# ---------------------------------------------------------------------------

def test_diaria_soma_o_intervalo():
    assert calcular_proxima_data("diaria", 1, None, None, SEGUNDA) == date(2026, 8, 4)
    assert calcular_proxima_data("diaria", 3, None, None, SEGUNDA) == date(2026, 8, 6)


def test_diaria_atravessa_o_mes():
    assert calcular_proxima_data("diaria", 5, None, None, date(2026, 8, 30)) == date(2026, 9, 4)


@pytest.mark.parametrize("intervalo", [0, None])
def test_intervalo_invalido_vira_um(intervalo):
    """`n = max(1, intervalo or 1)` protege contra tarefa que nunca avança."""
    assert calcular_proxima_data("diaria", intervalo, None, None, SEGUNDA) == date(2026, 8, 4)


# ---------------------------------------------------------------------------
# Semanal
# ---------------------------------------------------------------------------

def test_semanal_proxima_ocorrencia_na_mesma_semana():
    """De segunda, a próxima quarta (dia_semana=3) é dois dias depois."""
    assert calcular_proxima_data("semanal", 1, 3, None, SEGUNDA) == QUARTA


def test_semanal_no_mesmo_dia_pula_para_a_semana_seguinte():
    """
    Estritamente depois da base: realizar a tarefa de segunda numa segunda
    agenda a próxima para a segunda seguinte, não para hoje.
    """
    assert calcular_proxima_data("semanal", 1, 1, None, SEGUNDA) == date(2026, 8, 10)


def test_semanal_dia_ja_passado_vai_para_a_semana_seguinte():
    """De quarta, o próximo domingo (0) é 4 dias depois."""
    assert calcular_proxima_data("semanal", 1, 0, None, QUARTA) == DOMINGO


def test_semanal_com_intervalo_maior_soma_semanas_extras():
    """Quinzenal: a próxima quarta, mais uma semana."""
    assert calcular_proxima_data("semanal", 2, 3, None, SEGUNDA) == date(2026, 8, 12)


@pytest.mark.parametrize(
    "dia_semana,esperado",
    [
        (0, date(2026, 8, 9)),   # domingo
        (1, date(2026, 8, 10)),  # segunda (a seguinte)
        (2, date(2026, 8, 4)),   # terça
        (3, date(2026, 8, 5)),   # quarta
        (4, date(2026, 8, 6)),   # quinta
        (5, date(2026, 8, 7)),   # sexta
        (6, date(2026, 8, 8)),   # sábado
    ],
)
def test_semanal_cobre_a_convencao_domingo_zero(dia_semana, esperado):
    """
    Trava a conversão 0=Domingo..6=Sábado. Se alguém trocar pela convenção do
    Python (0=Segunda), todos estes casos mudam de uma vez.
    """
    resultado = calcular_proxima_data("semanal", 1, dia_semana, None, SEGUNDA)
    assert resultado == esperado
    assert resultado > SEGUNDA


def test_semanal_sem_dia_semana_falha():
    with pytest.raises(ValueError, match="dia_semana"):
        calcular_proxima_data("semanal", 1, None, None, SEGUNDA)


# ---------------------------------------------------------------------------
# Mensal
# ---------------------------------------------------------------------------

def test_mensal_ainda_neste_mes():
    assert calcular_proxima_data("mensal", 1, None, 20, SEGUNDA) == date(2026, 8, 20)


def test_mensal_dia_ja_passado_vai_para_o_mes_seguinte():
    assert calcular_proxima_data("mensal", 1, None, 1, SEGUNDA) == date(2026, 9, 1)


def test_mensal_no_mesmo_dia_pula_para_o_mes_seguinte():
    assert calcular_proxima_data("mensal", 1, None, 3, SEGUNDA) == date(2026, 9, 3)


def test_mensal_com_intervalo_maior_soma_meses_extras():
    """
    A regra é "próxima ocorrência + (intervalo-1) meses", e não "base +
    intervalo meses". Partindo de 03/08 com intervalo 3, a próxima ocorrência
    do dia 20 é 20/08, mais 2 meses: 20/10.
    """
    assert calcular_proxima_data("mensal", 3, None, 20, SEGUNDA) == date(2026, 10, 20)


def test_mensal_cadencia_se_estabiliza_no_intervalo():
    """
    Consequência da regra acima: o primeiro salto pode ser mais curto, mas as
    execuções seguintes ficam exatamente `intervalo` meses distantes entre si.
    """
    primeira = calcular_proxima_data("mensal", 3, None, 20, SEGUNDA)
    segunda = calcular_proxima_data("mensal", 3, None, 20, primeira)
    terceira = calcular_proxima_data("mensal", 3, None, 20, segunda)

    assert primeira == date(2026, 10, 20)
    assert segunda == date(2027, 1, 20)
    assert terceira == date(2027, 4, 20)


def test_mensal_vira_o_ano():
    assert calcular_proxima_data("mensal", 1, None, 1, date(2026, 12, 15)) == date(2027, 1, 1)


def test_mensal_dia_31_em_mes_de_30_cai_no_ultimo_dia():
    """Dia 31 em setembro não existe: vira 30."""
    assert calcular_proxima_data("mensal", 1, None, 31, date(2026, 9, 15)) == date(2026, 9, 30)


def test_mensal_dia_31_em_fevereiro_comum():
    assert calcular_proxima_data("mensal", 1, None, 31, date(2027, 2, 1)) == date(2027, 2, 28)


def test_mensal_dia_30_em_fevereiro_bissexto():
    """2028 é bissexto: 29 dias."""
    assert calcular_proxima_data("mensal", 1, None, 30, date(2028, 2, 1)) == date(2028, 2, 29)


def test_mensal_clamp_nao_arrasta_o_dia_nos_meses_seguintes():
    """
    O clamp vale só para o mês curto. Depois de cair em 28/02, a ocorrência
    seguinte tem de voltar ao dia 31 (ou ao último dia do mês).
    """
    fevereiro = calcular_proxima_data("mensal", 1, None, 31, date(2027, 2, 1))
    assert fevereiro == date(2027, 2, 28)
    marco = calcular_proxima_data("mensal", 1, None, 31, fevereiro)
    assert marco == date(2027, 3, 31)


def test_mensal_sem_dia_mes_falha():
    with pytest.raises(ValueError, match="dia_mes"):
        calcular_proxima_data("mensal", 1, None, None, SEGUNDA)


# ---------------------------------------------------------------------------
# Invariante geral
# ---------------------------------------------------------------------------

def test_tipo_invalido_falha():
    with pytest.raises(ValueError, match="tipo_recorrencia"):
        calcular_proxima_data("anual", 1, None, None, SEGUNDA)


@pytest.mark.parametrize(
    "tipo,intervalo,dia_semana,dia_mes",
    [
        ("diaria", 1, None, None),
        ("diaria", 7, None, None),
        ("semanal", 1, 0, None),
        ("semanal", 2, 5, None),
        ("mensal", 1, None, 1),
        ("mensal", 2, None, 31),
    ],
)
def test_resultado_e_sempre_depois_da_base(tipo, intervalo, dia_semana, dia_mes):
    """
    A invariante que sustenta o módulo: a próxima data nunca fica no passado,
    mesmo quando a tarefa é realizada com atraso.
    """
    for base in (SEGUNDA, QUARTA, DOMINGO, date(2026, 1, 31), date(2026, 12, 31)):
        assert calcular_proxima_data(tipo, intervalo, dia_semana, dia_mes, base) > base
