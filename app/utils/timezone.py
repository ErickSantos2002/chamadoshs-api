from datetime import datetime
import pytz

# Timezone de Brasília
BRASILIA_TZ = pytz.timezone('America/Sao_Paulo')


def agora_brasilia() -> datetime:
    """
    Retorna o datetime atual no horário de Brasília (America/Sao_Paulo)

    Returns:
        datetime: Datetime atual com timezone de Brasília
    """
    return datetime.now(BRASILIA_TZ)


def para_brasilia(dt: datetime) -> datetime:
    """
    Converte um datetime para o horário de Brasília

    Args:
        dt: Datetime a ser convertido (pode ser naive ou aware)

    Returns:
        datetime: Datetime convertido para timezone de Brasília
    """
    if dt.tzinfo is None:
        # Se for naive, assume que já está em Brasília
        return BRASILIA_TZ.localize(dt)
    else:
        # Se já tem timezone, converte para Brasília
        return dt.astimezone(BRASILIA_TZ)
