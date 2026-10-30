import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_current_user, get_db, is_admin
from app.models.chamado import Chamado
from app.models.comentario import ComentarioChamado
from app.models.usuario import Usuario
from app.schemas.comentario import ComentarioCreate, ComentarioUpdate, ComentarioResponse
from app.services.leitura_service import (
    buscar_chamado_legivel,
    pode_acessar_comentario_interno,
    pode_ler_chamado,
)

router = APIRouter()

logger = logging.getLogger(__name__)

COMENTARIO_NAO_ENCONTRADO = "Comentário não encontrado"
CRIAR_INTERNO_NEGADO = "Apenas administrador ou técnico da TI pode criar comentário interno"
MARCAR_INTERNO_NEGADO = "Apenas administrador ou técnico da TI pode marcar comentário como interno"


def _buscar_comentario_visivel(db: Session, comentario_id: int, usuario: Usuario) -> ComentarioChamado:
    """
    O comentário, se `usuario` pode vê-lo HOJE; senão o 404 de um id que não
    existe.

    Ver é ler o chamado dele (API-5) e, se for interno, poder o interno —
    administrador ou técnico da TI (API-8, `pode_acessar_comentario_interno`).
    As duas, nessa ordem. Vale para buscar, editar e excluir (API-6, D11):
    quem perdeu a leitura do chamado — o ex-responsável, o autor de um
    comentário de antes da API-5, o técnico da Qualidade num chamado da TI —
    não mexe mais no que escreveu lá, e quem não pode o interno não o vê, não
    o edita nem o exclui, nem sendo o autor. A recusa não diz que o
    comentário existe.
    """
    comentario = db.query(ComentarioChamado).filter(ComentarioChamado.id == comentario_id).first()
    chamado = db.query(Chamado).filter(Chamado.id == comentario.chamado_id).first() if comentario else None
    if chamado is None or not pode_ler_chamado(usuario, chamado):
        raise HTTPException(status_code=404, detail=COMENTARIO_NAO_ENCONTRADO)

    # `is not False`: NULL conta como interno, como no filtro da listagem
    # (`is_(False)`) — na dúvida, fecha.
    if comentario.is_interno is not False and not pode_acessar_comentario_interno(usuario):
        # 404 em vez de 403: um 403 confirmaria que existe um comentário
        # interno naquele id.
        raise HTTPException(status_code=404, detail=COMENTARIO_NAO_ENCONTRADO)

    return comentario


@router.get("/chamado/{chamado_id}", response_model=List[ComentarioResponse])
def listar_comentarios_chamado(
    chamado_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Lista os comentários de um chamado, se o usuário puder ler o chamado.

    Chamado que não existe e chamado que a pessoa não lê dão o mesmo 404
    (API-5). Comentários internos só aparecem para administrador e técnico
    da TI (API-8): para o resto, a lista é a dos públicos, sem erro e sem
    sinal de que há internos.
    """
    buscar_chamado_legivel(db, chamado_id, current_user)
    query = db.query(ComentarioChamado).filter(
        ComentarioChamado.chamado_id == chamado_id
    )

    if not pode_acessar_comentario_interno(current_user):
        query = query.filter(ComentarioChamado.is_interno.is_(False))

    return query.offset(skip).limit(limit).all()


@router.get("/{comentario_id}", response_model=ComentarioResponse)
def buscar_comentario(
    comentario_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Busca um comentário específico por ID.

    O comentário segue a leitura do chamado dele: pedir pelo id do comentário
    não contorna a regra (API-5). Comentário interno só é devolvido para
    administrador e técnico da TI (API-8); para o resto, o 404 de um id que
    não existe.
    """
    return _buscar_comentario_visivel(db, comentario_id, current_user)


@router.post("/", response_model=ComentarioResponse, status_code=status.HTTP_201_CREATED)
def criar_comentario(
    comentario_data: ComentarioCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Adiciona um novo comentário a um chamado.

    O autor vem do token. O chamado tem de existir e o usuário tem de poder
    lê-lo (API-5): antes qualquer conta comentava em qualquer chamado. Quem
    não pode recebe o mesmo 404 de um chamado que não existe. Só
    administrador e técnico da TI criam comentário interno (API-8); o resto
    recebe 403 e nada é gravado. O comentário público segue de quem lê o
    chamado.
    """
    # Só `is not None`: o aviso conta quem ainda manda o campo, não quem manda
    # o id de outra pessoa. Ver a nota em chamados.py.
    if comentario_data.usuario_id is not None:
        logger.warning(
            "campo usuario_id depreciado em criar_comentario: recebido %s, usando %s (do token)",
            comentario_data.usuario_id,
            current_user.id,
        )

    # A leitura antes da regra do interno: um 403 aqui diria que o chamado
    # existe a quem nem pode vê-lo.
    buscar_chamado_legivel(db, comentario_data.chamado_id, current_user)

    # 403 e não 404: quem chega aqui lê o chamado, e não há o que esconder.
    if comentario_data.is_interno and not pode_acessar_comentario_interno(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CRIAR_INTERNO_NEGADO)

    # exclude do usuario_id é obrigatório: sem ele o valor enviado pelo
    # cliente ainda chegaria ao banco, mesmo o campo sendo ignorado acima.
    comentario = ComentarioChamado(
        **comentario_data.model_dump(exclude={"usuario_id"}),
        usuario_id=current_user.id,
    )
    db.add(comentario)
    db.commit()
    db.refresh(comentario)
    return comentario


@router.put("/{comentario_id}", response_model=ComentarioResponse)
def atualizar_comentario(
    comentario_id: int,
    comentario_data: ComentarioUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Atualiza um comentário existente. Só o autor ou um administrador, e só
    quem vê o comentário hoje (API-6, D11): quem não vê recebe o 404 de um id
    que não existe, antes do 403 de autoria. Isso inclui o interno para quem
    não pode o interno (API-8), autor ou não: não o edita nem o torna
    público. Tornar interno um comentário público é só de administrador e
    técnico da TI.
    """
    comentario = _buscar_comentario_visivel(db, comentario_id, current_user)

    if comentario.usuario_id != current_user.id and not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só é possível editar comentários de sua autoria",
        )

    if comentario_data.is_interno and not pode_acessar_comentario_interno(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=MARCAR_INTERNO_NEGADO)

    update_data = comentario_data.model_dump(exclude_unset=True)
    # `is_interno: null` não é uma visibilidade: vale como não enviado. Sem
    # isto o NULL ia para o banco (a coluna aceita) e a resposta quebrava.
    if update_data.get("is_interno", False) is None:
        del update_data["is_interno"]
    for field, value in update_data.items():
        setattr(comentario, field, value)

    db.commit()
    db.refresh(comentario)
    return comentario


@router.delete("/{comentario_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_comentario(
    comentario_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deleta um comentário. Só o autor ou um administrador, e só quem vê o
    comentário hoje — como na edição: o interno, só quem pode o interno
    (API-8).
    """
    comentario = _buscar_comentario_visivel(db, comentario_id, current_user)

    if comentario.usuario_id != current_user.id and not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Só é possível excluir comentários de sua autoria",
        )

    db.delete(comentario)
    db.commit()
    return None
