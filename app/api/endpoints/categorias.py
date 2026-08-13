from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db, require_admin
from app.models.categoria import Categoria
from app.models.chamado import Chamado
from app.models.usuario import Usuario
from app.schemas.categoria import CategoriaCreate, CategoriaUpdate, CategoriaResponse

router = APIRouter()


@router.get("/", response_model=List[CategoriaResponse])
def listar_categorias(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
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
def criar_categoria(
    categoria_data: CategoriaCreate,
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Cria uma nova categoria. Restrito a administrador.
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
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Atualiza uma categoria existente. Restrito a administrador.
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
def deletar_categoria(
    categoria_id: int,
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Exclui uma categoria. Restrito a administrador.

    Só apaga se nenhum chamado estiver vinculado a ela — caso contrário devolve 400,
    porque apagar quebraria o histórico dos chamados (FK chamados.categoria_id).
    """
    categoria = db.query(Categoria).filter(Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")

    vinculados = db.query(Chamado).filter(Chamado.categoria_id == categoria_id).count()
    if vinculados > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Não é possível excluir categoria com {vinculados} chamado(s) vinculado(s)",
        )

    db.delete(categoria)
    db.commit()
    return None
