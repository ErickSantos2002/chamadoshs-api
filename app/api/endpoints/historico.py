from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_current_user, get_db
from app.models.chamado import Chamado
from app.models.historico import HistoricoChamado
from app.models.usuario import Usuario
from app.schemas.historico import HistoricoResponse
from app.services.leitura_service import buscar_chamado_legivel, pode_ler_chamado

router = APIRouter()


@router.get("/chamado/{chamado_id}", response_model=List[HistoricoResponse])
def listar_historico_chamado(
    chamado_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lista todo o histórico de um chamado, se o usuário puder ler o chamado.

    Chamado que não existe e chamado que a pessoa não lê dão o mesmo 404
    (API-5). Antes, id inexistente devolvia lista vazia.
    """
    buscar_chamado_legivel(db, chamado_id, current_user)
    historicos = db.query(HistoricoChamado).filter(
        HistoricoChamado.chamado_id == chamado_id
    ).order_by(HistoricoChamado.created_at.desc()).offset(skip).limit(limit).all()
    return historicos


@router.get("/{historico_id}", response_model=HistoricoResponse)
def buscar_historico(
    historico_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Busca um registro de histórico específico.

    O registro segue a leitura do chamado dele: pedir pelo id do histórico não
    contorna a regra, e a recusa é o mesmo 404 de um id que não existe.
    """
    historico = db.query(HistoricoChamado).filter(HistoricoChamado.id == historico_id).first()
    chamado = db.query(Chamado).filter(Chamado.id == historico.chamado_id).first() if historico else None
    if chamado is None or not pode_ler_chamado(current_user, chamado):
        raise HTTPException(status_code=404, detail="Histórico não encontrado")
    return historico
