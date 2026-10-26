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


# Título gerado para os chamados da Qualidade, cujo formulário não tem título.
TITULO_DERIVADO_MAXIMO = 80
# Abaixo disto a primeira linha não diz nada sozinha ("Oi", "Bom dia"), e o
# título passa a ser o começo da descrição inteira. É o mesmo mínimo do título
# digitado na TI.
TITULO_DERIVADO_MINIMO_DA_LINHA = 10


def derivar_titulo(descricao: str) -> str:
    """
    Título a partir da descrição: a primeira linha com texto, ou — se ela for
    curta demais para identificar o chamado — o começo da descrição inteira.

    Espaços, tabs e quebras de linha repetidos viram um espaço só, e o
    resultado tem no máximo `TITULO_DERIVADO_MAXIMO` caracteres, com "…" no
    corte. Nunca vazio para uma descrição com algum texto, que é o que o
    schema de criação garante.
    """
    linhas = (" ".join(linha.split()) for linha in descricao.splitlines())
    primeira = next((linha for linha in linhas if linha), "")

    if len(primeira) >= TITULO_DERIVADO_MINIMO_DA_LINHA:
        titulo = primeira
    else:
        titulo = " ".join(descricao.split())

    if len(titulo) <= TITULO_DERIVADO_MAXIMO:
        return titulo
    return titulo[: TITULO_DERIVADO_MAXIMO - 1].rstrip() + "…"


# Transições da rota de atendimento da Qualidade: as mesmas ações rápidas do
# frontend (`AcoesRapidas.tsx` e `ChamadoDetalhes.tsx`). O PUT da equipe não
# passa por aqui e continua sem restrição de transição.
TRANSICOES_DO_ATENDIMENTO = {
    "Aberto": frozenset({"Em Andamento"}),
    "Em Andamento": frozenset({"Aguardando", "Resolvido"}),
    "Aguardando": frozenset({"Em Andamento", "Resolvido"}),
    "Resolvido": frozenset({"Em Andamento"}),
    "Fechado": frozenset({"Em Andamento"}),
}


def transicao_permitida(status_atual: str, status_novo: str) -> bool:
    """Se o atendimento pode levar o chamado de um status ao outro."""
    return status_novo in TRANSICOES_DO_ATENDIMENTO.get(status_atual, frozenset())


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
