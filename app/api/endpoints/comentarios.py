import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_current_user, get_db, is_admin, is_staff
from app.models.comentario import ComentarioChamado
from app.models.usuario import Usuario
from app.schemas.comentario import ComentarioCreate, ComentarioUpdate, ComentarioResponse

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/chamado/{chamado_id}", response_model=List[ComentarioResponse])
def listar_comentarios_chamado(
    chamado_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lista os comentários de um chamado.

    Comentários internos só aparecem para administrador e técnico — é para
    isso que serve a marcação is_interno.
    """
    query = db.query(ComentarioChamado).filter(
        ComentarioChamado.chamado_id == chamado_id
    )

    if not is_staff(current_user):
        query = query.filter(ComentarioChamado.is_interno.is_(False))

    return query.offset(skip).limit(limit).all()


@router.get("/{comentario_id}", response_model=ComentarioResponse)
def buscar_comentario(
    comentario_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Busca um comentário específico por ID.

    Comentário interno só é devolvido para administrador e técnico.
    """
    comentario = db.query(ComentarioChamado).filter(ComentarioChamado.id == comentario_id).first()
    if not comentario:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")

    if comentario.is_interno and not is_staff(current_user):
        # 404 em vez de 403: um 403 confirmaria que existe um comentário
        # interno naquele id.
        raise HTTPException(status_code=404, detail="Comentário não encontrado")

    return comentario


@router.post("/", response_model=ComentarioResponse, status_code=status.HTTP_201_CREATED)
def criar_comentario(
    comentario_data: ComentarioCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Adiciona um novo comentário a um chamado.

    O autor vem do token. Só administrador e técnico podem marcar o
    comentário como interno.
    """
    # Só `is not None`: o aviso conta quem ainda manda o campo, não quem manda
    # o id de outra pessoa. Ver a nota em chamados.py.
    if comentario_data.usuario_id is not None:
        logger.warning(
            "campo usuario_id depreciado em criar_comentario: recebido %s, usando %s (do token)",
            comentario_data.usuario_id,
            current_user.id,
        )

    if comentario_data.is_interno and not is_staff(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administrador ou técnico pode criar comentário interno",
        )

    # exclude do usuario_id é obrigatório: sem ele o valor enviado pelo
    # cliente ainda chegaria ao banco, mesmo o campo sendo ignorado acima.
    comentario = ComentarioChamado(
        **comentario_data.model_dump(exclude={"usuario_id"}),
        usuario_id=current_user.id,
    )
    db.add(comentario)
    db.commit()
    db.refresh(comentario)
    return comentario


@router.put("/{comentario_id}", response_model=ComentarioResponse)
def atualizar_comentario(
    comentario_id: int,
    comentario_data: ComentarioUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Atualiza um comentário existente. Só o autor ou um administrador.
    """
    comentario = db.query(ComentarioChamado).filter(ComentarioChamado.id == comentario_id).first()
    if not comentario:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")

    if comentario.usuario_id != current_user.id and not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só é possível editar comentários de sua autoria",
        )

    if comentario_data.is_interno and not is_staff(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administrador ou técnico pode marcar comentário como interno",
        )

    update_data = comentario_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(comentario, field, value)

    db.commit()
    db.refresh(comentario)
    return comentario


@router.delete("/{comentario_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_comentario(
    comentario_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deleta um comentário. Só o autor ou um administrador.
    """
    comentario = db.query(ComentarioChamado).filter(ComentarioChamado.id == comentario_id).first()
    if not comentario:
        raise HTTPException(status_code=404, detail="Comentário não encontrado")

    if comentario.usuario_id != current_user.id and not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só é possível excluir comentários de sua autoria",
        )

    db.delete(comentario)
    db.commit()
    return None
