from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class HistoricoBase(BaseModel):
    acao: str
    descricao: Optional[str] = None
    status_anterior: Optional[str] = None
    status_novo: Optional[str] = None


class HistoricoResponse(HistoricoBase):
    id: int
    chamado_id: int
    usuario_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
