from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db
from app.models.historico import HistoricoChamado
from app.schemas.historico import HistoricoResponse

router = APIRouter()


@router.get("/chamado/{chamado_id}", response_model=List[HistoricoResponse])
def listar_historico_chamado(
    chamado_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    Lista todo o histórico de um chamado
    """
    historicos = db.query(HistoricoChamado).filter(
        HistoricoChamado.chamado_id == chamado_id
    ).order_by(HistoricoChamado.created_at.desc()).offset(skip).limit(limit).all()
    return historicos


@router.get("/{historico_id}", response_model=HistoricoResponse)
def buscar_historico(historico_id: int, db: Session = Depends(get_db)):
    """
    Busca um registro de histórico específico
    """
    historico = db.query(HistoricoChamado).filter(HistoricoChamado.id == historico_id).first()
    if not historico:
        raise HTTPException(status_code=404, detail="Histórico não encontrado")
    return historico
