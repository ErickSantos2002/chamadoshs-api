from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db
from app.models.comentario import ComentarioChamado
from app.schemas.comentario import ComentarioCreate, ComentarioUpdate, ComentarioResponse

router = APIRouter()


@router.get("/chamado/{chamado_id}", response_model=List[ComentarioResponse])
def listar_comentarios_chamado(
    chamado_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Lista todos os comentários de um chamado
    """
    comentarios = db.query(ComentarioChamado).filter(
        ComentarioChamado.chamado_id == chamado_id
    ).offset(skip).limit(limit).all()
    return comentarios


@router.get("/{comentario_id}", response_model=ComentarioResponse)
def buscar_comentario(comentario_id: int, db: Session = Depends(get_db)):
    """
    Busca um comentário específico por ID
    """
    comentario = db.query(ComentarioChamado).filter(ComentarioChamado.id == comentario_id).first()
    if not comentario:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")
    return comentario


@router.post("/", response_model=ComentarioResponse, status_code=status.HTTP_201_CREATED)
def criar_comentario(comentario_data: ComentarioCreate, db: Session = Depends(get_db)):
    """
    Adiciona um novo comentário a um chamado
    """
    comentario = ComentarioChamado(**comentario_data.model_dump())
    db.add(comentario)
    db.commit()
    db.refresh(comentario)
    return comentario


@router.put("/{comentario_id}", response_model=ComentarioResponse)
def atualizar_comentario(
    comentario_id: int,
    comentario_data: ComentarioUpdate,
    db: Session = Depends(get_db)
):
    """
    Atualiza um comentário existente
    """
    comentario = db.query(ComentarioChamado).filter(ComentarioChamado.id == comentario_id).first()
    if not comentario:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")

    update_data = comentario_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(comentario, field, value)

    db.commit()
    db.refresh(comentario)
    return comentario


@router.delete("/{comentario_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_comentario(comentario_id: int, db: Session = Depends(get_db)):
    """
    Deleta um comentário
    """
    comentario = db.query(ComentarioChamado).filter(ComentarioChamado.id == comentario_id).first()
    if not comentario:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")

    db.delete(comentario)
    db.commit()
    return None
