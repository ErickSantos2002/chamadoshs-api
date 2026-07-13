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
