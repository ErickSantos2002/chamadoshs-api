from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Annotated, Optional
from datetime import datetime
from enum import Enum

from app.schemas.sla import SLAInfo

# Tamanhos mínimos dos campos de texto do chamado, iguais aos que o frontend
# exige desde 11/08/2026.
#
# `strip_whitespace=True` é o que faz a regra valer: o Pydantic apara antes de
# medir, então uma barra de espaço repetida não satisfaz o mínimo — e o valor
# gravado no banco vai sem os espaços das pontas, em vez de guardar o que o
# formulário mandou.
#
# Estes tipos NÃO entram em `ChamadoBase`. Ver o comentário lá.
TituloChamado = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10)]
DescricaoChamado = Annotated[str, StringConstraints(strip_whitespace=True, min_length=20)]


class PrioridadeEnum(str, Enum):
    BAIXA = "Baixa"
    MEDIA = "Média"
    ALTA = "Alta"
    CRITICA = "Crítica"


class UrgenciaEnum(str, Enum):
    NAO_URGENTE = "Não Urgente"
    NORMAL = "Normal"
    URGENTE = "Urgente"
    MUITO_URGENTE = "Muito Urgente"


class StatusEnum(str, Enum):
    ABERTO = "Aberto"
    EM_ANDAMENTO = "Em Andamento"
    AGUARDANDO = "Aguardando"
    RESOLVIDO = "Resolvido"
    FECHADO = "Fechado"


class ChamadoBase(BaseModel):
    """
    Campos comuns de entrada e de saída.

    `titulo` e `descricao` ficam SEM tamanho mínimo aqui de propósito, mesmo
    sendo esse o lugar óbvio: `ChamadoResponse` herda desta classe, e o
    FastAPI valida a resposta contra ela. Um mínimo aqui faria todo chamado
    antigo com título curto — que existe, porque a API aceitou qualquer coisa
    até 11/08/2026 — estourar `ResponseValidationError` no `GET`. A regra
    entraria para melhorar o cadastro e derrubaria a leitura do histórico.

    O mínimo mora em `ChamadoCreate`, que é entrada pura.
    """

    titulo: str
    descricao: str
    categoria_id: Optional[int] = None
    prioridade: PrioridadeEnum = PrioridadeEnum.MEDIA


class ChamadoCreate(ChamadoBase):
    """Chamado novo: aqui o mínimo vale, porque não há legado para respeitar."""

    titulo: TituloChamado
    descricao: DescricaoChamado
    solicitante_id: int


class ChamadoUpdate(BaseModel):
    titulo: Optional[str] = None
    descricao: Optional[str] = None
    categoria_id: Optional[int] = None
    prioridade: Optional[PrioridadeEnum] = None
    urgencia: Optional[UrgenciaEnum] = None
    status: Optional[StatusEnum] = None
    tecnico_responsavel_id: Optional[int] = None
    solucao: Optional[str] = None
    observacoes: Optional[str] = None
    avaliacao: Optional[int] = Field(None, ge=1, le=5)


class ChamadoAvaliacao(BaseModel):
    """
    Corpo do PATCH /chamados/{id}/avaliar.

    Schema próprio, e não `ChamadoUpdate`, porque este é o único corpo que o
    solicitante comum pode enviar: qualquer campo aqui é campo que ele passa a
    poder escrever. Manter só `avaliacao` é o que impede a rota de virar um
    caminho alternativo para mexer em status, prioridade ou técnico.

    `ge`/`le` espelham o CHECK da coluna — sem eles um 0 ou 6 só falharia no
    commit, virando 500 em vez de 422.
    """

    avaliacao: int = Field(..., ge=1, le=5)


class ChamadoResponse(ChamadoBase):
    id: int
    protocolo: str
    solicitante_id: int
    status: StatusEnum
    urgencia: Optional[UrgenciaEnum] = None
    tecnico_responsavel_id: Optional[int] = None
    solucao: Optional[str] = None
    tempo_resolucao_minutos: Optional[int] = None
    observacoes: Optional[str] = None
    avaliacao: Optional[int] = None
    cancelado: bool = False
    arquivado: bool = False
    data_abertura: datetime
    data_atualizacao: datetime
    data_resolucao: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    sla: Optional[SLAInfo] = None

    model_config = ConfigDict(from_attributes=True)
