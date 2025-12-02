from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate, UsuarioResponse

router = APIRouter()


@router.get("/", response_model=List[UsuarioResponse])
def listar_usuarios(
    skip: int = 0,
    limit: int = 100,
    setor_id: int = None,
    role_id: int = None,
    ativo: bool = None,
    db: Session = Depends(get_db)
):
    """
    Lista todos os usuários com filtros opcionais
    """
    query = db.query(Usuario)

    if setor_id:
        query = query.filter(Usuario.setor_id == setor_id)
    if role_id:
        query = query.filter(Usuario.role_id == role_id)
    if ativo is not None:
        query = query.filter(Usuario.ativo == ativo)

    usuarios = query.offset(skip).limit(limit).all()
    return usuarios


@router.get("/{usuario_id}", response_model=UsuarioResponse)
def buscar_usuario(usuario_id: int, db: Session = Depends(get_db)):
    """
    Busca um usuário específico por ID
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return usuario


@router.post("/", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def criar_usuario(usuario_data: UsuarioCreate, db: Session = Depends(get_db)):
    """
    Cria um novo usuário
    """
    usuario = Usuario(**usuario_data.model_dump())
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.put("/{usuario_id}", response_model=UsuarioResponse)
def atualizar_usuario(
    usuario_id: int,
    usuario_data: UsuarioUpdate,
    db: Session = Depends(get_db)
):
    """
    Atualiza um usuário existente
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    update_data = usuario_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(usuario, field, value)

    db.commit()
    db.refresh(usuario)
    return usuario


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_usuario(usuario_id: int, db: Session = Depends(get_db)):
    """
    Desativa um usuário (soft delete)
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    usuario.ativo = False
    db.commit()
    return None
