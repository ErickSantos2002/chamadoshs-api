from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class UsuarioBase(BaseModel):
    nome: str
    setor_id: Optional[int] = None
    role_id: int
    ativo: bool = True
    # Conta que não representa uma pessoa (painel, integração, login
    # compartilhado). Fica em UsuarioBase para valer nos três lados: aceito na
    # criação, devolvido na resposta.
    #
    # O padrão False é parte do contrato: conta criada sem informar o campo é
    # pessoa. O contrário faria toda conta nova sumir do seletor de técnico.
    conta_de_servico: bool = False


class UsuarioCreate(UsuarioBase):
    senha: str


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    senha: Optional[str] = None
    setor_id: Optional[int] = None
    role_id: Optional[int] = None
    ativo: Optional[bool] = None
    # None aqui significa "não mexer", e não False: o handler usa
    # exclude_unset, então omitir o campo preserva o valor gravado.
    conta_de_servico: Optional[bool] = None


class UsuarioResponse(UsuarioBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
