from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db, require_admin
from app.models.setor import Setor
from app.models.usuario import Usuario
from app.schemas.setor import SetorCreate, SetorUpdate, SetorResponse
from app.services.evento_setor_service import (
    instantaneo,
    registrar_alteracoes,
    registrar_criacao,
)

router = APIRouter()


def _buscar(db: Session, setor_id: int) -> Setor:
    setor = db.query(Setor).filter(Setor.id == setor_id).first()
    if not setor:
        raise HTTPException(status_code=404, detail="Setor não encontrado")
    return setor


def _usuarios_ativos(db: Session, setor_id: int) -> int:
    return (
        db.query(Usuario)
        .filter(Usuario.setor_id == setor_id, Usuario.ativo.is_(True))
        .count()
    )


def _garantir_desativacao_segura(db: Session, setor: Setor) -> None:
    """
    Recusa desativar setor que ainda tem gente ativa dentro.

    Um setor inativo some do seletor do formulário, mas não solta os usuários
    que apontam para ele: as contas continuam vinculadas a um setor que a tela
    não oferece mais. O efeito aparece longe da causa — na hora de editar uma
    dessas pessoas, o formulário não consegue exibir o setor atual dela.

    A contagem é de usuários ATIVOS, não de todos. Setor extinto anos atrás
    ainda tem ex-funcionários apontando para ele, e esses vínculos são
    justamente o histórico que não se apaga — contá-los tornaria todo setor
    antigo indesativável, que é o oposto do que se quer.

    Vale para os três caminhos que desativam: PATCH, PUT e DELETE. Em usuários
    essa trava nasceu só no DELETE e o `PUT {"ativo": false}` passava por cima
    dela; aqui ela já entra compartilhada.

    **Setor que já está inativo passa direto**, e a condição mora aqui dentro,
    não nos chamadores. Desativar o que já está desativado não muda nada: o
    estado pedido é o estado final, então a resposta é sucesso e nenhum evento é
    gravado. Recusar seria pior do que inútil — a mensagem falaria de usuários
    ativos vinculados a um setor que ninguém está desativando agora.

    A condição já morou no `PUT`, como `if ... and setor.ativo`, e foi assim que
    as rotas divergiram: `PUT` respondia 200 num setor já inativo e os `PATCH` e
    `DELETE` respondiam 400. Guarda repetida no chamador é a mesma forma de erro
    que este passo inteiro existe para eliminar — quem checa é a trava, uma vez.
    """
    if not setor.ativo:
        return

    vinculados = _usuarios_ativos(db, setor.id)
    if vinculados > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Não é possível desativar setor com {vinculados} usuário(s) "
                "ativo(s) vinculado(s)"
            ),
        )


def _desativar(db: Session, setor: Setor, admin: Usuario, origem: str) -> Setor:
    """
    Corpo compartilhado pelo PATCH de desativar e pelo DELETE, que só diferem
    na `origem` gravada — é por ela que se mede quanto do frontend já migrou.
    """
    _garantir_desativacao_segura(db, setor)

    antes = instantaneo(setor)
    setor.ativo = False
    # Desativar setor já inativo não muda nada e não gera evento; a resposta
    # continua sendo sucesso, porque o estado pedido é o estado final.
    registrar_alteracoes(db, setor=setor, antes=antes, ator=admin, origem=origem)
    db.commit()
    db.refresh(setor)
    return setor


@router.get("/", response_model=List[SetorResponse])
def listar_setores(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    ativo: bool = None,
    db: Session = Depends(get_db)
):
    """
    Lista todos os setores
    """
    query = db.query(Setor)
    if ativo is not None:
        query = query.filter(Setor.ativo == ativo)

    setores = query.offset(skip).limit(limit).all()
    return setores


@router.get("/{setor_id}", response_model=SetorResponse)
def buscar_setor(setor_id: int, db: Session = Depends(get_db)):
    """
    Busca um setor específico por ID
    """
    return _buscar(db, setor_id)


@router.post("/", response_model=SetorResponse, status_code=status.HTTP_201_CREATED)
def criar_setor(
    setor_data: SetorCreate,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Cria um novo setor. Restrito a administrador.
    """
    setor = Setor(**setor_data.model_dump())
    db.add(setor)
    # flush antes do commit: o evento precisa do id, que só existe depois de a
    # linha chegar ao banco. Continua sendo uma transação só — setor criado sem
    # evento não é um estado alcançável.
    db.flush()
    registrar_criacao(db, setor=setor, ator=admin, origem="POST /api/v1/setores/")
    db.commit()
    db.refresh(setor)
    return setor


@router.put("/{setor_id}", response_model=SetorResponse)
def atualizar_setor(
    setor_id: int,
    setor_data: SetorUpdate,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Atualiza um setor existente. Restrito a administrador.

    É por aqui que o frontend edita setor hoje, e por aqui que ele desativa
    quando manda `ativo: false` — daí a trava e a gravação de trilha estarem
    nesta rota também, e não só nas novas.
    """
    setor = _buscar(db, setor_id)

    update_data = setor_data.model_dump(exclude_unset=True)

    # Estado de antes, para a trilha. Precisa ser tirado agora: depois do
    # setattr o valor anterior não existe mais em lugar nenhum.
    antes = instantaneo(setor)

    # Só quando `ativo` chega como false. Reativar é o caminho de volta —
    # aplicar a trava a qualquer mudança de `ativo` bloquearia a recuperação.
    # "Já está inativo" é decidido dentro da trava, não aqui.
    if update_data.get("ativo") is False:
        _garantir_desativacao_segura(db, setor)

    for field, value in update_data.items():
        setattr(setor, field, value)

    registrar_alteracoes(
        db,
        setor=setor,
        antes=antes,
        ator=admin,
        origem="PUT /api/v1/setores/{id}",
    )

    db.commit()
    db.refresh(setor)
    return setor


@router.patch("/{setor_id}/desativar", response_model=SetorResponse)
def desativar_setor(
    setor_id: int,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Desativa um setor. Restrito a administrador.

    Diz no verbo o que sempre fez no corpo: o `DELETE` desta rota nunca apagou
    setor nenhum. Fechar essa distância é o que permite, no passo seguinte, o
    `DELETE` passar a excluir de verdade sem que ninguém confunda as duas
    coisas.

    Devolve o setor para a tela atualizar a linha sem uma segunda requisição.
    """
    return _desativar(
        db, _buscar(db, setor_id), admin, "PATCH /api/v1/setores/{id}/desativar"
    )


@router.patch("/{setor_id}/reativar", response_model=SetorResponse)
def reativar_setor(
    setor_id: int,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Reativa um setor. Restrito a administrador.

    Sem trava: a de desativação existe para não deixar usuários ativos presos a
    um setor que sumiu do formulário, e reativar é justamente o que desfaz esse
    estado.
    """
    setor = _buscar(db, setor_id)

    antes = instantaneo(setor)
    setor.ativo = True
    registrar_alteracoes(
        db,
        setor=setor,
        antes=antes,
        ator=admin,
        origem="PATCH /api/v1/setores/{id}/reativar",
    )
    db.commit()
    db.refresh(setor)
    return setor


@router.delete("/{setor_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_setor(
    setor_id: int,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Desativa um setor. Restrito a administrador.

    Mantido porque o frontend chama esta rota hoje; delega para o mesmo corpo
    do `PATCH .../desativar`, então as duas não têm como divergir.

    ATENÇÃO: esta é a rota que MUDA DE COMPORTAMENTO no passo 3. Lá ela passa a
    excluir o setor de verdade, com checagem de vínculo, como já acontece em
    categorias — e o `PATCH .../desativar` fica sendo o caminho para o que hoje
    ela faz. Quem chamar `DELETE` esperando desativação vai apagar. É por isso
    que o passo 3 só acontece depois de o frontend migrar para o PATCH.

    Uma trava nova entrou junto com esta entrega: desativar setor com usuários
    ativos vinculados devolve 400. Antes passava e deixava as contas presas a
    um setor que a tela não oferece mais.
    """
    _desativar(db, _buscar(db, setor_id), admin, "DELETE /api/v1/setores/{id}")
    return None
