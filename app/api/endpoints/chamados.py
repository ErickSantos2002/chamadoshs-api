from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.api.deps import get_db
from app.models.chamado import Chamado
from app.schemas.chamado import ChamadoCreate, ChamadoUpdate, ChamadoResponse
from app.services.chamado_service import gerar_protocolo, registrar_historico, calcular_tempo_resolucao

router = APIRouter()


@router.get("/", response_model=List[ChamadoResponse])
def listar_chamados(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    solicitante_id: int = None,
    tecnico_id: int = None,
    db: Session = Depends(get_db)
):
    """
    Lista todos os chamados com filtros opcionais
    """
    query = db.query(Chamado)

    if status:
        query = query.filter(Chamado.status == status)
    if solicitante_id:
        query = query.filter(Chamado.solicitante_id == solicitante_id)
    if tecnico_id:
        query = query.filter(Chamado.tecnico_responsavel_id == tecnico_id)

    chamados = query.offset(skip).limit(limit).all()
    return chamados


@router.get("/{chamado_id}", response_model=ChamadoResponse)
def buscar_chamado(chamado_id: int, db: Session = Depends(get_db)):
    """
    Busca um chamado específico por ID
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")
    return chamado


@router.post("/", response_model=ChamadoResponse, status_code=status.HTTP_201_CREATED)
def criar_chamado(chamado_data: ChamadoCreate, db: Session = Depends(get_db)):
    """
    Cria um novo chamado
    """
    # Gerar protocolo único
    protocolo = gerar_protocolo(db)

    # Criar chamado
    chamado = Chamado(
        protocolo=protocolo,
        solicitante_id=chamado_data.solicitante_id,
        categoria_id=chamado_data.categoria_id,
        titulo=chamado_data.titulo,
        descricao=chamado_data.descricao,
        prioridade=chamado_data.prioridade,
        status="Aberto"
    )

    db.add(chamado)
    db.commit()
    db.refresh(chamado)

    # Registrar no histórico
    registrar_historico(
        db=db,
        chamado_id=chamado.id,
        usuario_id=chamado_data.solicitante_id,
        acao="Abertura de chamado",
        descricao=f"Chamado aberto com protocolo {protocolo}",
        status_novo="Aberto"
    )

    return chamado


@router.put("/{chamado_id}", response_model=ChamadoResponse)
def atualizar_chamado(
    chamado_id: int,
    chamado_data: ChamadoUpdate,
    usuario_id: int,  # Em produção, isso viria do token de autenticação
    db: Session = Depends(get_db)
):
    """
    Atualiza um chamado existente
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    # Armazenar status anterior para histórico
    status_anterior = chamado.status

    # Atualizar campos
    update_data = chamado_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(chamado, field, value)

    # Se mudou para "Resolvido" ou "Fechado", calcular tempo de resolução
    if chamado_data.status and chamado_data.status in ["Resolvido", "Fechado"]:
        if not chamado.data_resolucao:
            chamado.data_resolucao = datetime.now()
            chamado.tempo_resolucao_minutos = calcular_tempo_resolucao(
                chamado.data_abertura,
                chamado.data_resolucao
            )

    db.commit()
    db.refresh(chamado)

    # Registrar no histórico se mudou o status
    if chamado_data.status and status_anterior != chamado_data.status:
        registrar_historico(
            db=db,
            chamado_id=chamado.id,
            usuario_id=usuario_id,
            acao="Alteração de status",
            descricao=f"Status alterado de {status_anterior} para {chamado_data.status.value}",
            status_anterior=status_anterior,
            status_novo=chamado_data.status.value
        )

    return chamado


@router.delete("/{chamado_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_chamado(chamado_id: int, db: Session = Depends(get_db)):
    """
    Deleta um chamado (soft delete recomendado em produção)
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    db.delete(chamado)
    db.commit()
    return None
