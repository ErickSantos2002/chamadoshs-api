import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.api.deps import (
    get_current_user,
    get_db,
    is_admin,
    is_staff,
    require_admin,
    require_staff,
)
from app.models.chamado import Chamado
from app.models.usuario import Usuario
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.schemas.chamado import (
    ChamadoAvaliacao,
    ChamadoCreate,
    ChamadoResponse,
    ChamadoUpdate,
    StatusEnum,
)
from app.services.chamado_service import gerar_protocolo, registrar_historico, calcular_tempo_resolucao
from app.services.sla_service import calcular_sla
from app.services.webhook_service import enviar_webhook_tecnico
from app.utils.timezone import agora_brasilia

router = APIRouter()

logger = logging.getLogger(__name__)

# Parâmetro `usuario_id` depreciado.
#
# Estes endpoints recebiam o autor da ação como query parameter, ou seja, o
# histórico registrava quem o chamador dissesse ser. O autor agora vem do
# token. O parâmetro continua sendo aceito e ignorado apenas para o frontend
# atual não quebrar durante a janela entre os dois deploys (repositórios
# separados). Remover assim que o aviso abaixo parar de aparecer nos logs.
USUARIO_ID_DEPRECIADO = Query(
    None,
    deprecated=True,
    include_in_schema=False,
    description="DEPRECADO: ignorado. O autor da ação vem do token JWT.",
)


def _avisar_usuario_id_depreciado(endpoint: str, usuario_id: Optional[int], atual: Usuario) -> None:
    # A condição é apenas `is not None`, de propósito.
    #
    # Antes havia também `usuario_id != atual.id`, e isso tornava o aviso
    # inútil como sinal de desligamento: o caso normal — a pessoa logada
    # agindo em nome de si mesma, mandando o próprio id — passava silencioso.
    # O log podia estar zerado com o frontend enviando o parâmetro em 100% das
    # chamadas, e remover o suporte no backend quebraria produção.
    #
    # Agora conta o que interessa: quantas chamadas ainda mandam o parâmetro.
    # O volume é alto enquanto o frontend não for atualizado — é o baseline
    # esperado, não um defeito.
    if usuario_id is not None:
        logger.warning(
            "param usuario_id depreciado em %s: recebido %s, usando %s (do token)",
            endpoint,
            usuario_id,
            atual.id,
        )


def _validar_tecnico_responsavel(db: Session, chamado_data: ChamadoUpdate) -> None:
    """
    Recusa atribuir um chamado a uma conta que não é pessoa.

    O seletor do frontend já filtra contas de serviço, mas filtro de tela é
    convenção, não garantia: `tecnico_responsavel_id` é FK crua e a API aceita
    qualquer id que exista na tabela.

    Só valida quando o campo vem na requisição — `model_fields_set`, não o
    valor. Validar o técnico atual em todo PUT tornaria um chamado ineditável
    caso a pessoa atribuída virasse conta de serviço depois: mudar o status ou
    escrever a solução passaria a falhar por causa de um campo que a
    requisição nem toca.

    `None` explícito é desatribuição, e continua permitido.
    """
    if "tecnico_responsavel_id" not in chamado_data.model_fields_set:
        return

    tecnico_id = chamado_data.tecnico_responsavel_id
    if tecnico_id is None:
        return

    tecnico = db.query(Usuario).filter(Usuario.id == tecnico_id).first()
    if tecnico is None:
        # Sem esta checagem o id inexistente só estouraria como violação de
        # chave estrangeira no commit, virando 500 em vez de erro do cliente.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Técnico responsável não encontrado",
        )

    if tecnico.conta_de_servico:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível atribuir um chamado a uma conta de serviço",
        )


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
    skip: int = Query(0, ge=0),
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
def criar_chamado(
    chamado_data: ChamadoCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cria um novo chamado.

    O solicitante vem do token, não do corpo: aceitar do cliente permitia
    abrir chamado em nome de qualquer pessoa. Administrador continua podendo
    abrir em nome de outro, informando solicitante_id.
    """
    if is_admin(current_user) and chamado_data.solicitante_id:
        solicitante_id = chamado_data.solicitante_id
    else:
        solicitante_id = current_user.id

    # Gerar protocolo único
    protocolo = gerar_protocolo(db)

    # Criar chamado
    chamado = Chamado(
        protocolo=protocolo,
        solicitante_id=solicitante_id,
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
        usuario_id=solicitante_id,
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
    usuario_id: Optional[int] = USUARIO_ID_DEPRECIADO,
    current_user: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Atualiza um chamado existente. Restrito a administrador ou técnico.
    """
    _avisar_usuario_id_depreciado("atualizar_chamado", usuario_id, current_user)

    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    # Depois do 404: chamado inexistente é 404, não 400 por causa do técnico.
    _validar_tecnico_responsavel(db, chamado_data)

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
            usuario_id=current_user.id,
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


# Status em que o atendimento já terminou e faz sentido avaliar.
STATUS_AVALIAVEIS = (StatusEnum.RESOLVIDO.value, StatusEnum.FECHADO.value)


@router.patch("/{chamado_id}/avaliar", response_model=ChamadoResponse)
def avaliar_chamado(
    chamado_id: int,
    avaliacao_data: ChamadoAvaliacao,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Registra a avaliação do atendimento pelo solicitante.

    Existe como rota própria porque o PUT /{id} é `require_staff` e vai
    continuar sendo: por ele o solicitante conseguiria alterar status,
    prioridade e técnico responsável do próprio chamado. Aqui o único campo
    gravável é `avaliacao`.

    Só o solicitante avalia. Administrador e técnico não avaliam no lugar
    dele — a nota mede o atendimento que a equipe prestou, então deixar a
    própria equipe preenchê-la esvaziaria o indicador. Por isso a checagem é
    `solicitante_id != current_user.id` puro, sem escape por perfil.
    """
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    if chamado.solicitante_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só o solicitante pode avaliar o próprio chamado",
        )

    if chamado.status not in STATUS_AVALIAVEIS:
        # 409 e não 400: o corpo está correto, o que impede é o estado atual
        # do chamado — resolver o chamado torna a mesma requisição válida.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O chamado só pode ser avaliado quando estiver resolvido ou fechado",
        )

    avaliacao_anterior = chamado.avaliacao
    chamado.avaliacao = avaliacao_data.avaliacao
    db.commit()
    db.refresh(chamado)

    registrar_historico(
        db=db,
        chamado_id=chamado.id,
        usuario_id=current_user.id,
        acao="Avaliação do atendimento",
        descricao=(
            f"Avaliação alterada de {avaliacao_anterior} para {chamado.avaliacao}"
            if avaliacao_anterior is not None
            else f"Chamado avaliado com nota {chamado.avaliacao}"
        ),
    )

    return _anexar_sla([chamado], db)[0]


@router.patch("/{chamado_id}/cancelar", response_model=ChamadoResponse)
def cancelar_chamado(
    chamado_id: int,
    usuario_id: Optional[int] = USUARIO_ID_DEPRECIADO,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Cancela um chamado (soft delete - apenas marca como cancelado).

    O solicitante pode cancelar o próprio chamado; administrador e técnico
    cancelam qualquer um.
    """
    _avisar_usuario_id_depreciado("cancelar_chamado", usuario_id, current_user)

    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if not chamado:
        raise HTTPException(status_code=404, detail="Chamado não encontrado")

    if not is_staff(current_user) and chamado.solicitante_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só é possível cancelar chamados abertos por você",
        )

    if chamado.cancelado:
        raise HTTPException(status_code=400, detail="Chamado já está cancelado")

    chamado.cancelado = True
    db.commit()
    db.refresh(chamado)

    # Registrar no histórico
    registrar_historico(
        db=db,
        chamado_id=chamado.id,
        usuario_id=current_user.id,
        acao="Cancelamento de chamado",
        descricao=f"Chamado #{chamado.protocolo} foi cancelado"
    )

    return _anexar_sla([chamado], db)[0]


@router.patch("/{chamado_id}/arquivar", response_model=ChamadoResponse)
def arquivar_chamado(
    chamado_id: int,
    usuario_id: Optional[int] = USUARIO_ID_DEPRECIADO,
    current_user: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Arquiva um chamado (remove da visualização padrão mas mantém no banco).
    Restrito a administrador ou técnico.
    """
    _avisar_usuario_id_depreciado("arquivar_chamado", usuario_id, current_user)

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
        usuario_id=current_user.id,
        acao="Arquivamento de chamado",
        descricao=f"Chamado #{chamado.protocolo} foi arquivado"
    )

    return _anexar_sla([chamado], db)[0]


@router.patch("/{chamado_id}/desarquivar", response_model=ChamadoResponse)
def desarquivar_chamado(
    chamado_id: int,
    usuario_id: Optional[int] = USUARIO_ID_DEPRECIADO,
    current_user: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """
    Desarquiva um chamado (volta a exibir na visualização padrão).
    Restrito a administrador ou técnico.
    """
    _avisar_usuario_id_depreciado("desarquivar_chamado", usuario_id, current_user)

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
        usuario_id=current_user.id,
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
