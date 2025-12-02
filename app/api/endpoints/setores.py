from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db
from app.models.setor import Setor
from app.schemas.setor import SetorCreate, SetorUpdate, SetorResponse

router = APIRouter()


@router.get("/", response_model=List[SetorResponse])
def listar_setores(
    skip: int = 0,
    limit: int = 100,
    ativo: bool = None,
    db: Session = Depends(get_db)
):
    """
    Lista todos os setores
    """
    query = db.query(Setor)
    if ativo is not None:
        query = query.filter(Setor.ativo == ativo)

    setores = query.offset(skip).limit(limit).all()
    return setores


@router.get("/{setor_id}", response_model=SetorResponse)
def buscar_setor(setor_id: int, db: Session = Depends(get_db)):
    """
    Busca um setor específico por ID
    """
    setor = db.query(Setor).filter(Setor.id == setor_id).first()
    if not setor:
        raise HTTPException(status_code=404, detail="Setor não encontrado")
    return setor


@router.post("/", response_model=SetorResponse, status_code=status.HTTP_201_CREATED)
def criar_setor(setor_data: SetorCreate, db: Session = Depends(get_db)):
    """
    Cria um novo setor
    """
    setor = Setor(**setor_data.model_dump())
    db.add(setor)
    db.commit()
    db.refresh(setor)
    return setor


@router.put("/{setor_id}", response_model=SetorResponse)
def atualizar_setor(
    setor_id: int,
    setor_data: SetorUpdate,
    db: Session = Depends(get_db)
):
    """
    Atualiza um setor existente
    """
    setor = db.query(Setor).filter(Setor.id == setor_id).first()
    if not setor:
        raise HTTPException(status_code=404, detail="Setor não encontrado")

    update_data = setor_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(setor, field, value)

    db.commit()
    db.refresh(setor)
    return setor


@router.delete("/{setor_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_setor(setor_id: int, db: Session = Depends(get_db)):
    """
    Desativa um setor
    """
    setor = db.query(Setor).filter(Setor.id == setor_id).first()
    if not setor:
        raise HTTPException(status_code=404, detail="Setor não encontrado")

    setor.ativo = False
    db.commit()
    return None
