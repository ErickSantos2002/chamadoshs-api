from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class AnexoBase(BaseModel):
    nome_arquivo: str
    caminho: str
    tamanho_kb: Optional[int] = None
    tipo_mime: Optional[str] = None


class AnexoCreate(AnexoBase):
    chamado_id: int
    uploaded_by: Optional[int] = None


class AnexoResponse(AnexoBase):
    id: int
    chamado_id: int
    uploaded_by: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
