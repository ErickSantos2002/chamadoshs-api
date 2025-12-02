from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class RoleBase(BaseModel):
    nome: str
    descricao: Optional[str] = None


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None


class RoleResponse(RoleBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
