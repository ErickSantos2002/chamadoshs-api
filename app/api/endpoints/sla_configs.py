from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.sla_config import SLAConfig
from app.schemas.sla import SLAConfigResponse, SLAConfigUpdate

router = APIRouter()


@router.get("/", response_model=List[SLAConfigResponse])
def listar_sla_configs(db: Session = Depends(get_db)):
    """Lista os prazos de SLA de todas as prioridades."""
    return db.query(SLAConfig).order_by(SLAConfig.minutos_resolucao.desc()).all()


@router.put("/{prioridade}", response_model=SLAConfigResponse)
def atualizar_sla_config(
    prioridade: str,
    dados: SLAConfigUpdate,
    db: Session = Depends(get_db),
):
    """Atualiza os prazos de uma prioridade."""
    config = db.query(SLAConfig).filter(SLAConfig.prioridade == prioridade).first()
    if not config:
        raise HTTPException(status_code=404, detail="Prioridade não encontrada")

    config.minutos_resposta = dados.minutos_resposta
    config.minutos_resolucao = dados.minutos_resolucao

    db.commit()
    db.refresh(config)
    return config
