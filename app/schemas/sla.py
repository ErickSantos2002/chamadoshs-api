from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SLAConfigResponse(BaseModel):
    prioridade: str
    minutos_resposta: int
    minutos_resolucao: int

    model_config = ConfigDict(from_attributes=True)


class SLAConfigUpdate(BaseModel):
    minutos_resposta: int = Field(gt=0)
    minutos_resolucao: int = Field(gt=0)


class SLAInfo(BaseModel):
    """Bloco de SLA calculado e embutido em cada chamado."""
    prazo_resposta: Optional[datetime] = None
    prazo_resolucao: Optional[datetime] = None
    minutos_resposta_consumidos: int = 0
    minutos_resolucao_consumidos: int = 0
    minutos_pausados: int = 0
    percentual_resolucao: int = 0
    situacao: str = "No prazo"  # "No prazo" | "Atenção" | "Estourado"
    resposta_cumprida: bool = True
