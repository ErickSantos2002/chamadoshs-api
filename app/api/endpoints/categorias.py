from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db
from app.models.categoria import Categoria
from app.schemas.categoria import CategoriaCreate, CategoriaUpdate, CategoriaResponse

router = APIRouter()


@router.get("/", response_model=List[CategoriaResponse])
def listar_categorias(
    skip: int = 0,
    limit: int = 100,
    ativo: bool = None,
    db: Session = Depends(get_db)
):
    """
    Lista todas as categorias
    """
    query = db.query(Categoria)
    if ativo is not None:
        query = query.filter(Categoria.ativo == ativo)

    categorias = query.offset(skip).limit(limit).all()
    return categorias


@router.get("/{categoria_id}", response_model=CategoriaResponse)
def buscar_categoria(categoria_id: int, db: Session = Depends(get_db)):
    """
    Busca uma categoria específica por ID
    """
    categoria = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    return categoria


@router.post("/", response_model=CategoriaResponse, status_code=status.HTTP_201_CREATED)
def criar_categoria(categoria_data: CategoriaCreate, db: Session = Depends(get_db)):
    """
    Cria uma nova categoria
    """
    categoria = Categoria(**categoria_data.model_dump())
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return categoria


@router.put("/{categoria_id}", response_model=CategoriaResponse)
def atualizar_categoria(
    categoria_id: int,
    categoria_data: CategoriaUpdate,
    db: Session = Depends(get_db)
):
    """
    Atualiza uma categoria existente
    """
    categoria = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    update_data = categoria_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(categoria, field, value)

    db.commit()
    db.refresh(categoria)
    return categoria


@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_categoria(categoria_id: int, db: Session = Depends(get_db)):
    """
    Desativa uma categoria
    """
    categoria = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    categoria.ativo = False
    db.commit()
    return None
