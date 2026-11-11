from pydantic import BaseModel, Field, model_validator
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

    @model_validator(mode="before")
    @classmethod
    def _sem_conta_de_servico(cls, dados):
        """
        `POST /auth/registro` não decide se a conta é de serviço (API-11, S5).

        O campo não existe aqui e o Pydantic descartava a chave calado: quem
        mandava `true` recebia 201 e uma conta humana. Qualquer presença —
        `true`, `false`, `null`, outro tipo — vira 422, sem criar a conta. A
        conta de serviço nasce pelo `POST /usuarios/`, onde o campo existe.
        """
        if isinstance(dados, dict) and "conta_de_servico" in dados:
            raise ValueError("conta_de_servico não é aceito em /auth/registro; use POST /usuarios/")
        return dados


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
    # Se a conta é da equipe da TI (API-7, A7-5), calculado a cada pedido por
    # `integra_equipe_ti` — a mesma regra de `require_equipe_ti`. Só de
    # resposta: não está no cadastro, no banco nem no token.
    #
    # Diz de qual equipe a pessoa é, não o que ela pode: o administrador fora
    # de um setor da TI recebe False e administra assim mesmo, pelo perfil. A
    # tela combina os dois — perfil Administrador OU este campo.
    integra_equipe_ti: bool
