from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    """Schema para requisição de login"""
    nome: str = Field(..., description="Nome de usuário (username)")
    senha: str = Field(..., description="Senha do usuário")


class TokenResponse(BaseModel):
    """Schema para resposta com token"""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    nome: str
    role: str


class UsuarioCreate(BaseModel):
    """Schema para criação de usuário com senha"""
    nome: str = Field(..., description="Nome de usuário (username)")
    senha: str = Field(..., min_length=6, description="Senha do usuário (mínimo 6 caracteres)")
    setor_id: Optional[int] = None
    role_id: int
    ativo: bool = True


class UsuarioUpdate(BaseModel):
    """Schema para atualização de usuário"""
    nome: Optional[str] = None
    senha: Optional[str] = Field(None, min_length=6, description="Nova senha (opcional)")
    setor_id: Optional[int] = None
    role_id: Optional[int] = None
    ativo: Optional[bool] = None


class AlterarSenhaRequest(BaseModel):
    """Schema para alteração de senha"""
    senha_atual: str = Field(..., description="Senha atual")
    senha_nova: str = Field(..., min_length=6, description="Nova senha (mínimo 6 caracteres)")


class UsuarioLogado(BaseModel):
    """Schema com dados do usuário logado"""
    id: int
    nome: str
    setor_id: Optional[int]
    role_id: int
    ativo: bool
