from datetime import datetime
from sqlalchemy.orm import Session
from app.models.chamado import Chamado
from app.models.historico import HistoricoChamado
from app.utils.timezone import para_brasilia


def gerar_protocolo(db: Session) -> str:
    """
    Gera um protocolo único para o chamado no formato: CHAM-YYYY-NNNN
    """
    ano_atual = datetime.now().year

    # Busca o último chamado do ano
    ultimo_chamado = db.query(Chamado).filter(
        Chamado.protocolo.like(f'CHAM-{ano_atual}-%')
    ).order_by(Chamado.id.desc()).first()

    if ultimo_chamado:
        # Extrai o número sequencial do protocolo
        numero = int(ultimo_chamado.protocolo.split('-')[-1]) + 1
    else:
        numero = 1

    return f"CHAM-{ano_atual}-{numero:04d}"


def registrar_historico(
    db: Session,
    chamado_id: int,
    usuario_id: int,
    acao: str,
    descricao: str = None,
    status_anterior: str = None,
    status_novo: str = None
):
    """
    Registra uma ação no histórico do chamado
    """
    historico = HistoricoChamado(
        chamado_id=chamado_id,
        usuario_id=usuario_id,
        acao=acao,
        descricao=descricao,
        status_anterior=status_anterior,
        status_novo=status_novo
    )
    db.add(historico)
    db.commit()
    return historico


def calcular_tempo_resolucao(data_abertura: datetime, data_resolucao: datetime) -> int:
    """
    Calcula o tempo de resolução em minutos.
    Garante que ambas as datas estejam com timezone antes de calcular a diferença.
    """
    # Garante que ambas as datas tenham timezone (offset-aware)
    data_abertura_tz = para_brasilia(data_abertura)
    data_resolucao_tz = para_brasilia(data_resolucao)

    diferenca = data_resolucao_tz - data_abertura_tz
    return int(diferenca.total_seconds() / 60)
