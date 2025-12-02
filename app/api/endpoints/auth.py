from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import timedelta

from app.api.deps import get_db, get_current_user
from app.models.usuario import Usuario
from app.models.role import Role
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    UsuarioCreate,
    AlterarSenhaRequest,
    UsuarioLogado
)
from app.core.security import verificar_senha, gerar_hash_senha, criar_token_acesso
from app.core.config import settings

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    """
    Endpoint de login - retorna token JWT
    """
    # Buscar usuário pelo nome (username)
    usuario = db.query(Usuario).filter(Usuario.nome == credentials.nome).first()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos"
        )

    # Verificar se o usuário está ativo
    if not usuario.ativo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo"
        )

    # Verificar senha
    if not usuario.senha_hash or not verificar_senha(credentials.senha, usuario.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos"
        )

    # Buscar role do usuário
    role = db.query(Role).filter(Role.id == usuario.role_id).first()
    role_nome = role.nome if role else "Usuario"

    # Criar token JWT
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = criar_token_acesso(
        data={"sub": usuario.id, "nome": usuario.nome, "role": role_nome},
        expires_delta=access_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=usuario.id,
        nome=usuario.nome,
        role=role_nome
    )


@router.post("/registro", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def registrar_usuario(usuario_data: UsuarioCreate, db: Session = Depends(get_db)):
    """
    Endpoint de registro - cria novo usuário e retorna token
    """
    # Verificar se o nome de usuário já existe
    usuario_existe = db.query(Usuario).filter(Usuario.nome == usuario_data.nome).first()
    if usuario_existe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de usuário já cadastrado"
        )

    # Criar hash da senha
    senha_hash = gerar_hash_senha(usuario_data.senha)

    # Criar usuário
    novo_usuario = Usuario(
        nome=usuario_data.nome,
        senha_hash=senha_hash,
        setor_id=usuario_data.setor_id,
        role_id=usuario_data.role_id,
        ativo=usuario_data.ativo
    )

    db.add(novo_usuario)
    db.commit()
    db.refresh(novo_usuario)

    # Buscar role do usuário
    role = db.query(Role).filter(Role.id == novo_usuario.role_id).first()
    role_nome = role.nome if role else "Usuario"

    # Criar token JWT
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = criar_token_acesso(
        data={"sub": novo_usuario.id, "nome": novo_usuario.nome, "role": role_nome},
        expires_delta=access_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=novo_usuario.id,
        nome=novo_usuario.nome,
        role=role_nome
    )


@router.get("/me", response_model=UsuarioLogado)
def obter_usuario_logado(current_user: Usuario = Depends(get_current_user)):
    """
    Retorna informações do usuário logado
    """
    return UsuarioLogado(
        id=current_user.id,
        nome=current_user.nome,
        setor_id=current_user.setor_id,
        role_id=current_user.role_id,
        ativo=current_user.ativo
    )


@router.post("/alterar-senha")
def alterar_senha(
    dados: AlterarSenhaRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Altera a senha do usuário logado
    """
    # Verificar senha atual
    if not current_user.senha_hash or not verificar_senha(dados.senha_atual, current_user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta"
        )

    # Atualizar senha
    current_user.senha_hash = gerar_hash_senha(dados.senha_nova)
    db.commit()

    return {"message": "Senha alterada com sucesso"}


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Renova o token JWT do usuário logado
    """
    # Buscar role do usuário
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    role_nome = role.nome if role else "Usuario"

    # Criar novo token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = criar_token_acesso(
        data={"sub": current_user.id, "nome": current_user.nome, "role": role_nome},
        expires_delta=access_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=current_user.id,
        nome=current_user.nome,
        role=role_nome
    )
