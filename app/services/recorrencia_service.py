"""Cálculo da próxima data de uma tarefa recorrente.

Regra: a próxima data é sempre a próxima ocorrência do padrão ESTRITAMENTE
depois da data base (normalmente "hoje", no momento em que a tarefa é
realizada). Isso garante que a próxima data nunca fica no passado, mesmo que
a tarefa tenha sido feita atrasada.
"""

import calendar
from datetime import date, timedelta
from typing import Optional


def _clamp_dia_mes(ano: int, mes: int, dia: int) -> date:
    """Retorna date(ano, mes, dia), limitando `dia` ao último dia do mês.

    Ex.: dia 31 em fevereiro vira o dia 28 (ou 29 em ano bissexto).
    """
    ultimo = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, min(dia, ultimo))


def calcular_proxima_data(
    tipo: str,
    intervalo: int,
    dia_semana: Optional[int],
    dia_mes: Optional[int],
    base: date,
) -> date:
    """Próxima ocorrência do padrão, estritamente depois de `base`.

    - diaria:  base + intervalo dias
    - semanal: próximo `dia_semana` (0=Dom..6=Sáb) depois de base; se
               intervalo > 1, soma (intervalo-1) semanas extras
    - mensal:  próxima ocorrência de `dia_mes` depois de base; se intervalo > 1,
               soma (intervalo-1) meses extras (com clamp para meses curtos)
    """
    n = max(1, intervalo or 1)

    if tipo == "diaria":
        return base + timedelta(days=n)

    if tipo == "semanal":
        if dia_semana is None:
            raise ValueError("dia_semana é obrigatório para recorrência semanal")
        base_js = (base.weekday() + 1) % 7  # converte Python (Seg=0) -> 0=Dom..6=Sáb
        dias = (dia_semana - base_js) % 7
        if dias == 0:
            dias = 7  # estritamente depois de base
        prox = base + timedelta(days=dias)
        if n > 1:
            prox += timedelta(weeks=n - 1)
        return prox

    if tipo == "mensal":
        if dia_mes is None:
            raise ValueError("dia_mes é obrigatório para recorrência mensal")
        ano, mes = base.year, base.month
        cand = _clamp_dia_mes(ano, mes, dia_mes)
        while cand <= base:
            mes += 1
            if mes > 12:
                mes, ano = 1, ano + 1
            cand = _clamp_dia_mes(ano, mes, dia_mes)
        for _ in range(n - 1):
            mes += 1
            if mes > 12:
                mes, ano = 1, ano + 1
        return _clamp_dia_mes(ano, mes, dia_mes)

    raise ValueError(f"tipo_recorrencia inválido: {tipo}")
