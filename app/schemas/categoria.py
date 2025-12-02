from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class CategoriaBase(BaseModel):
    nome: str
    descricao: Optional[str] = None
    ativo: bool = True


class CategoriaCreate(CategoriaBase):
    pass


class CategoriaUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    ativo: Optional[bool] = None


class CategoriaResponse(CategoriaBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
