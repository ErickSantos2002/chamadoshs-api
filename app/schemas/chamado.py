from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime
from enum import Enum


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
    titulo: str
    descricao: str
    categoria_id: Optional[int] = None
    prioridade: PrioridadeEnum = PrioridadeEnum.MEDIA


class ChamadoCreate(ChamadoBase):
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

    model_config = ConfigDict(from_attributes=True)
