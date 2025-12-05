from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.api.deps import get_db
from app.models.chamado import Chamado
from app.schemas.chamado import ChamadoCreate, ChamadoUpdate, ChamadoResponse
from app.services.chamado_service import gerar_protocolo, registrar_historico, calcular_tempo_resolucao
from app.services.webhook_service import enviar_webhook_tecnico

router = APIRouter()


@router.get("/", response_model=List[ChamadoResponse])
def listar_chamados(
    skip: int = 0,
    limit: int = 100,
    status: str = None,
    solicitante_id: int = None,
    tecnico_id: int = None,
    incluir_cancelados: bool = False,
    incluir_arquivados: bool = False,
    db: Session = Depends(get_db)
):
    """
    Lista todos os chamados com filtros opcionais.
    Por padrão, exclui chamados cancelados e arquivados.
    """
    query = db.query(Chamado)

    # Filtros padrão para excluir cancelados e arquivados
    if not incluir_cancelados:
        query = query.filter(Chamado.cancelado == False)
    if not incluir_arquivados:
        query = query.filter(Chamado.arquivado == False)

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

    # Enviar webhook para notificação (sem técnico = "Sem atribuição")
    enviar_webhook_tecnico(
        db=db,
        protocolo=protocolo,
        titulo=chamado.titulo,
        tecnico_id=None,
        acao="criado"
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

    # Armazenar status anterior e técnico anterior para histórico e webhook
    status_anterior = chamado.status
    tecnico_anterior = chamado.tecnico_responsavel_id

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

    # Enviar webhook se o técnico foi atribuído ou alterado
    if chamado_data.tecnico_responsavel_id is not None and tecnico_anterior != chamado_data.tecnico_responsavel_id:
        enviar_webhook_tecnico(
            db=db,
            protocolo=chamado.protocolo,
            titulo=chamado.titulo,
            tecnico_id=chamado_data.tecnico_responsavel_id,
            acao="atribuido"
        )

    return chamado


@router.patch("/{chamado_id}/cancelar", response_model=ChamadoResponse)
def cancelar_chamado(
    chamado_id: int,
    usuario_id: int,  # Em produção, isso viria do token de autenticação
    db: Session = Depends(get_db)
):
    """
    Cancela um chamado (soft delete - apenas marca como cancelado)
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    if chamado.cancelado:
        raise HTTPException(status_code=400, detail="Chamado já está cancelado")

    chamado.cancelado = True
    db.commit()
    db.refresh(chamado)

    # Registrar no histórico
    registrar_historico(
        db=db,
        chamado_id=chamado.id,
        usuario_id=usuario_id,
        acao="Cancelamento de chamado",
        descricao=f"Chamado #{chamado.protocolo} foi cancelado"
    )

    return chamado


@router.patch("/{chamado_id}/arquivar", response_model=ChamadoResponse)
def arquivar_chamado(
    chamado_id: int,
    usuario_id: int,  # Em produção, isso viria do token de autenticação
    db: Session = Depends(get_db)
):
    """
    Arquiva um chamado (remove da visualização padrão mas mantém no banco)
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    if chamado.arquivado:
        raise HTTPException(status_code=400, detail="Chamado já está arquivado")

    chamado.arquivado = True
    db.commit()
    db.refresh(chamado)

    # Registrar no histórico
    registrar_historico(
        db=db,
        chamado_id=chamado.id,
        usuario_id=usuario_id,
        acao="Arquivamento de chamado",
        descricao=f"Chamado #{chamado.protocolo} foi arquivado"
    )

    return chamado


@router.patch("/{chamado_id}/desarquivar", response_model=ChamadoResponse)
def desarquivar_chamado(
    chamado_id: int,
    usuario_id: int,  # Em produção, isso viria do token de autenticação
    db: Session = Depends(get_db)
):
    """
    Desarquiva um chamado (volta a exibir na visualização padrão)
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    if not chamado.arquivado:
        raise HTTPException(status_code=400, detail="Chamado não está arquivado")

    chamado.arquivado = False
    db.commit()
    db.refresh(chamado)

    # Registrar no histórico
    registrar_historico(
        db=db,
        chamado_id=chamado.id,
        usuario_id=usuario_id,
        acao="Desarquivamento de chamado",
        descricao=f"Chamado #{chamado.protocolo} foi desarquivado"
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
