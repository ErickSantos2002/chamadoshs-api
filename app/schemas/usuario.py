from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class UsuarioBase(BaseModel):
    nome: str
    setor_id: Optional[int] = None
    role_id: int
    ativo: bool = True


class UsuarioCreate(UsuarioBase):
    pass


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    setor_id: Optional[int] = None
    role_id: Optional[int] = None
    ativo: Optional[bool] = None


class UsuarioResponse(UsuarioBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
