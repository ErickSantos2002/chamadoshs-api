from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class SetorBase(BaseModel):
    nome: str
    descricao: Optional[str] = None
    ativo: bool = True


class SetorCreate(SetorBase):
    pass


class SetorUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    ativo: Optional[bool] = None


class SetorResponse(SetorBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
