from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class ComentarioBase(BaseModel):
    comentario: str
    is_interno: bool = False


class ComentarioCreate(ComentarioBase):
    chamado_id: int
    usuario_id: int


class ComentarioUpdate(BaseModel):
    comentario: Optional[str] = None
    is_interno: Optional[bool] = None


class ComentarioResponse(ComentarioBase):
    id: int
    chamado_id: int
    usuario_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
