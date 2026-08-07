from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.api.deps import get_db, require_admin
from app.models.chamado import Chamado
from app.models.usuario import Usuario
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.schemas.chamado import ChamadoCreate, ChamadoUpdate, ChamadoResponse
from app.services.chamado_service import gerar_protocolo, registrar_historico, calcular_tempo_resolucao
from app.services.sla_service import calcular_sla
from app.services.webhook_service import enviar_webhook_tecnico
from app.utils.timezone import agora_brasilia

router = APIRouter()


def _anexar_sla(chamados: List[Chamado], db: Session) -> List[Chamado]:
    """
    Calcula e anexa o bloco `sla` a cada chamado.

    Duas queries no total (configs + históricos de todos os chamados de uma vez),
    para não cair em N+1 na listagem.

    Resiliente à ausência da tabela `sla_configs` (ex.: migração ainda não
    rodou em produção): se a query falhar, trata como "sem configs" em vez de
    derrubar o endpoint inteiro — o chamado é devolvido normalmente, só sem
    bloco de SLA (ver `calcular_sla`: sem config, o chamado não tem SLA e o
    campo vai `None`, nunca um falso "No prazo").
    """
    if not chamados:
        return chamados

    try:
        configs = {c.prioridade: c for c in db.query(SLAConfig).all()}
    except SQLAlchemyError:
        db.rollback()  # sem isso, a próxima query nesta sessão estoura PendingRollbackError
        configs = {}

    ids = [c.id for c in chamados]
    historicos_por_chamado: dict[int, list] = {i: [] for i in ids}
    historicos = (
        db.query(HistoricoChamado)
        .filter(HistoricoChamado.chamado_id.in_(ids))
        .all()
    )
    for h in historicos:
        historicos_por_chamado[h.chamado_id].append(h)

    for chamado in chamados:
        cfg = configs.get(chamado.prioridade)
        chamado.sla = (
            calcular_sla(
                chamado=chamado,
                historicos=historicos_por_chamado.get(chamado.id, []),
                config=cfg,
            )
            if cfg
            else None
        )

    return chamados


@router.get("/", response_model=List[ChamadoResponse])
def listar_chamados(
    skip: int = 0,
    limit: int = Query(100, ge=1, le=500),
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

    # Ordem determinística: sem ela o Postgres não garante a mesma sequência
    # entre páginas, e o skip/limit repetiria ou puliria registros.
    chamados = query.order_by(Chamado.id.desc()).offset(skip).limit(limit).all()
    return _anexar_sla(chamados, db)


@router.get("/{chamado_id}", response_model=ChamadoResponse)
def buscar_chamado(chamado_id: int, db: Session = Depends(get_db)):
    """
    Busca um chamado específico por ID
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")
    return _anexar_sla([chamado], db)[0]


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

    return _anexar_sla([chamado], db)[0]


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
            chamado.data_resolucao = agora_brasilia()
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

    return _anexar_sla([chamado], db)[0]


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

    return _anexar_sla([chamado], db)[0]


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

    return _anexar_sla([chamado], db)[0]


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

    return _anexar_sla([chamado], db)[0]


@router.delete("/{chamado_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_chamado(
    chamado_id: int,
    _admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Deleta um chamado em definitivo. Restrito a administrador.

    É exclusão real (db.delete), não soft delete — o registro some junto
    com seu histórico. Para tirar da visualização use cancelar ou arquivar.
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    db.delete(chamado)
    db.commit()
    return None
