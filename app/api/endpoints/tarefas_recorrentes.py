from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import timedelta

import logging

from app.api.deps import get_current_user, get_db, require_staff
from app.models.tarefa_recorrente import TarefaRecorrente, TarefaRecorrenteExecucao
from app.models.usuario import Usuario
from app.schemas.tarefa_recorrente import (
    TarefaRecorrenteCreate,
    TarefaRecorrenteUpdate,
    TarefaRecorrenteResponse,
    ExecucaoResponse,
    RealizarTarefaRequest,
)
from app.services.recorrencia_service import calcular_proxima_data
from app.utils.timezone import agora_brasilia

router = APIRouter()

logger = logging.getLogger(__name__)


def _hoje():
    return agora_brasilia().date()


def _montar_response(t: TarefaRecorrente, db: Session) -> dict:
    """Monta o dict de resposta com os agregados (total/última execução) e nomes."""
    total = (
        db.query(func.count(TarefaRecorrenteExecucao.id))
        .filter(TarefaRecorrenteExecucao.tarefa_id == t.id)
        .scalar()
        or 0
    )
    ultima = (
        db.query(func.max(TarefaRecorrenteExecucao.realizada_em))
        .filter(TarefaRecorrenteExecucao.tarefa_id == t.id)
        .scalar()
    )
    categoria_nome = t.categoria.nome if t.categoria else None
    responsavel_nome = (
        db.query(Usuario.nome).filter(Usuario.id == t.responsavel_id).scalar()
        if t.responsavel_id
        else None
    )
    data = {c.name: getattr(t, c.name) for c in t.__table__.columns}
    data.update(
        total_execucoes=total,
        categoria_nome=categoria_nome,
        responsavel_nome=responsavel_nome,
        ultima_execucao=ultima,
    )
    return data


@router.get("/", response_model=List[TarefaRecorrenteResponse])
def listar_tarefas(
    ativo: Optional[bool] = None,
    apenas_atrasadas: bool = False,
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """Lista tarefas recorrentes (ordenadas pela próxima data)."""
    query = db.query(TarefaRecorrente)
    if ativo is not None:
        query = query.filter(TarefaRecorrente.ativo == ativo)
    if apenas_atrasadas:
        query = query.filter(TarefaRecorrente.proxima_data <= _hoje())
    query = query.order_by(TarefaRecorrente.proxima_data.asc())
    tarefas = query.offset(skip).limit(limit).all()
    return [_montar_response(t, db) for t in tarefas]


@router.get("/{tarefa_id}", response_model=TarefaRecorrenteResponse)
def buscar_tarefa(tarefa_id: int, db: Session = Depends(get_db)):
    tarefa = db.query(TarefaRecorrente).filter(TarefaRecorrente.id == tarefa_id).first()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa recorrente não encontrada")
    return _montar_response(tarefa, db)


@router.post("/", response_model=TarefaRecorrenteResponse, status_code=status.HTTP_201_CREATED)
def criar_tarefa(
    dados: TarefaRecorrenteCreate,
    _staff: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    payload = dados.model_dump()
    proxima = payload.pop("proxima_data", None)
    if proxima is None:
        # base = ontem, para permitir HOJE como primeira ocorrência possível
        proxima = calcular_proxima_data(
            dados.tipo_recorrencia,
            dados.intervalo,
            dados.dia_semana,
            dados.dia_mes,
            _hoje() - timedelta(days=1),
        )
    tarefa = TarefaRecorrente(**payload, proxima_data=proxima)
    db.add(tarefa)
    db.commit()
    db.refresh(tarefa)
    return _montar_response(tarefa, db)


@router.put("/{tarefa_id}", response_model=TarefaRecorrenteResponse)
def atualizar_tarefa(
    tarefa_id: int,
    dados: TarefaRecorrenteUpdate,
    _staff: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    tarefa = db.query(TarefaRecorrente).filter(TarefaRecorrente.id == tarefa_id).first()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa recorrente não encontrada")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(tarefa, campo, valor)
    db.commit()
    db.refresh(tarefa)
    return _montar_response(tarefa, db)


@router.delete("/{tarefa_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_tarefa(
    tarefa_id: int,
    _staff: Usuario = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """Exclui a tarefa e, em cascata, todo o histórico de execuções.

    A confirmação (avisando sobre a perda do histórico) é responsabilidade do
    frontend. Aqui a exclusão é definitiva: execuções são removidas junto pelo
    cascade do ORM e pelo ON DELETE CASCADE da FK no banco.
    """
    tarefa = db.query(TarefaRecorrente).filter(TarefaRecorrente.id == tarefa_id).first()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa recorrente não encontrada")
    db.delete(tarefa)
    db.commit()


@router.get("/{tarefa_id}/execucoes", response_model=List[ExecucaoResponse])
def listar_execucoes(tarefa_id: int, db: Session = Depends(get_db)):
    execucoes = (
        db.query(TarefaRecorrenteExecucao)
        .filter(TarefaRecorrenteExecucao.tarefa_id == tarefa_id)
        .order_by(TarefaRecorrenteExecucao.realizada_em.desc())
        .all()
    )
    resultado = []
    for e in execucoes:
        nome = db.query(Usuario.nome).filter(Usuario.id == e.usuario_id).scalar()
        d = {c.name: getattr(e, c.name) for c in e.__table__.columns}
        d["usuario_nome"] = nome
        resultado.append(d)
    return resultado


@router.post("/{tarefa_id}/realizar", response_model=TarefaRecorrenteResponse)
def realizar_tarefa(
    tarefa_id: int,
    dados: RealizarTarefaRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Registra uma execução e avança a próxima data para a próxima ocorrência.

    Quem realizou vem do token: aceitar do corpo permitia registrar a
    execução em nome de outra pessoa.
    """
    # Só `is not None`: o aviso conta quem ainda manda o campo, não quem manda
    # o id de outra pessoa. Ver a nota em chamados.py.
    if dados.usuario_id is not None:
        logger.warning(
            "campo usuario_id depreciado em realizar_tarefa: recebido %s, usando %s (do token)",
            dados.usuario_id,
            current_user.id,
        )

    tarefa = db.query(TarefaRecorrente).filter(TarefaRecorrente.id == tarefa_id).first()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa recorrente não encontrada")

    execucao = TarefaRecorrenteExecucao(
        tarefa_id=tarefa.id,
        usuario_id=current_user.id,
        data_prevista=tarefa.proxima_data,
        observacao=dados.observacao,
    )
    db.add(execucao)

    tarefa.proxima_data = calcular_proxima_data(
        tarefa.tipo_recorrencia,
        tarefa.intervalo,
        tarefa.dia_semana,
        tarefa.dia_mes,
        _hoje(),
    )
    db.commit()
    db.refresh(tarefa)
    return _montar_response(tarefa, db)
