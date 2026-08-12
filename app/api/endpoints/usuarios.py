from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db, require_admin, ROLE_ADMIN, _normalizar_role
from app.models.role import Role
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate, UsuarioResponse
from app.core.security import gerar_hash_senha
from app.services.evento_conta_service import (
    instantaneo,
    registrar_alteracoes,
    registrar_criacao,
)

router = APIRouter()


def _e_administrador(role: Role) -> bool:
    return _normalizar_role(role.nome if role else None) == _normalizar_role(ROLE_ADMIN)


def _admins_ativos(db: Session, role_id: int) -> int:
    return (
        db.query(Usuario)
        .filter(Usuario.ativo.is_(True), Usuario.role_id == role_id)
        .count()
    )


def _garantir_desativacao_segura(db: Session, usuario: Usuario, admin: Usuario) -> None:
    """
    Recusa as duas desativações que deixariam o sistema sem quem administrar:
    a de si mesmo e a do último administrador ativo. Como criar e editar
    usuário também exigem administrador, não haveria recuperação pela
    aplicação — só por SQL direto no banco.

    Vale para os dois caminhos que desativam. Enquanto a checagem morava só no
    DELETE, um PUT {"ativo": false} passava por cima dela e derrubava o último
    administrador — a porta ao lado da que o DELETE trancava.
    """
    if usuario.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Não é possível desativar o próprio usuário",
        )

    if usuario.ativo and _e_administrador(usuario.role):
        if _admins_ativos(db, usuario.role_id) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Não é possível desativar o último administrador ativo",
            )


def _garantir_rebaixamento_seguro(db: Session, usuario: Usuario, novo_role_id: int) -> None:
    """
    Recusa tirar o perfil de administrador do último administrador ativo.

    Deixa o sistema no mesmo estado que a desativação — sem ninguém para
    administrar — mas a recuperação é pior: quem se rebaixa perde o acesso à
    tela de Cadastros, que é exclusiva de administrador, e some da própria
    condição de consertar. O desativado ao menos continua listado para outro
    administrador reativar.

    E o caminho é de tela, não de API: o modal de usuário envia o perfil em
    toda gravação, então trocar o próprio para "Usuario" e salvar são três
    cliques.

    A regra é sobre o último, não sobre si mesmo: quem sai da equipe rebaixa a
    própria conta, e isso é legítimo enquanto houver outro administrador ativo.
    Reenviar o mesmo perfil também passa — é o que o modal faz em toda
    gravação, inclusive quando só se mexeu no setor.
    """
    if not usuario.ativo or not _e_administrador(usuario.role):
        return

    if novo_role_id == usuario.role_id:
        return

    # Perfil inexistente cai aqui como "não é administrador", que é a leitura
    # segura: o INSERT falha adiante na FK de qualquer forma.
    if _e_administrador(db.query(Role).filter(Role.id == novo_role_id).first()):
        return

    if _admins_ativos(db, usuario.role_id) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Não é possível rebaixar o último administrador ativo",
        )


@router.get("/", response_model=List[UsuarioResponse])
def listar_usuarios(
    skip: int = 0,
    limit: int = 100,
    setor_id: int = None,
    role_id: int = None,
    ativo: bool = None,
    db: Session = Depends(get_db)
):
    """
    Lista todos os usuários com filtros opcionais
    """
    query = db.query(Usuario)

    if setor_id:
        query = query.filter(Usuario.setor_id == setor_id)
    if role_id:
        query = query.filter(Usuario.role_id == role_id)
    if ativo is not None:
        query = query.filter(Usuario.ativo == ativo)

    usuarios = query.offset(skip).limit(limit).all()
    return usuarios


@router.get("/{usuario_id}", response_model=UsuarioResponse)
def buscar_usuario(usuario_id: int, db: Session = Depends(get_db)):
    """
    Busca um usuário específico por ID
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return usuario


@router.post("/", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def criar_usuario(
    usuario_data: UsuarioCreate,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Cria um novo usuário. Restrito a administrador.
    """
    # Verifica se já existe usuário com esse nome
    usuario_existente = db.query(Usuario).filter(Usuario.nome == usuario_data.nome).first()
    if usuario_existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Usuário com nome '{usuario_data.nome}' já existe"
        )

    # Cria dicionário com os dados, excluindo a senha em texto plano
    usuario_dict = usuario_data.model_dump(exclude={'senha'})

    # Gera hash da senha e adiciona ao dicionário
    usuario_dict['senha_hash'] = gerar_hash_senha(usuario_data.senha)

    # Cria o usuário com senha hasheada
    usuario = Usuario(**usuario_dict)
    db.add(usuario)
    # flush antes do commit: o evento precisa do id, que só existe depois de a
    # linha chegar ao banco. Continua sendo uma transação só — conta criada sem
    # evento não é um estado alcançável.
    db.flush()
    registrar_criacao(
        db, usuario=usuario, ator=admin, origem="POST /api/v1/usuarios/"
    )
    db.commit()
    db.refresh(usuario)
    return usuario


@router.put("/{usuario_id}", response_model=UsuarioResponse)
def atualizar_usuario(
    usuario_id: int,
    usuario_data: UsuarioUpdate,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Atualiza um usuário existente. Restrito a administrador.

    Aceita senha e role_id. Enquanto este endpoint era público, uma única
    requisição sem token trocava a senha de qualquer conta, inclusive a do
    administrador — era o caminho mais direto de tomada do sistema.

    Não precisa de exceção para o próprio usuário: quem quer trocar a
    própria senha usa POST /api/v1/auth/alterar-senha, que exige a senha
    atual.
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    update_data = usuario_data.model_dump(exclude_unset=True)

    # Estado de antes, para a trilha de auditoria. Precisa ser tirado agora:
    # depois do setattr o valor anterior não existe mais em lugar nenhum.
    antes = instantaneo(usuario)
    senha_alterada = "senha" in update_data

    # Só quando `ativo` chega como false. Reativar é hoje o único caminho de
    # volta pela interface — aplicar as travas a qualquer mudança de `ativo`
    # bloquearia justamente a recuperação, em vez do dano.
    if update_data.get("ativo") is False:
        _garantir_desativacao_segura(db, usuario, admin)

    if update_data.get("role_id") is not None:
        _garantir_rebaixamento_seguro(db, usuario, update_data["role_id"])

    # Se está atualizando a senha, gera o hash
    if 'senha' in update_data:
        senha_hash = gerar_hash_senha(update_data.pop('senha'))
        update_data['senha_hash'] = senha_hash

    for field, value in update_data.items():
        setattr(usuario, field, value)

    # O PUT também desativa e troca perfil, e é por ele que o cadastro é
    # editado hoje. Registrar só nas rotas novas deixaria invisível justamente
    # o caminho em uso.
    registrar_alteracoes(
        db,
        usuario=usuario,
        antes=antes,
        ator=admin,
        origem="PUT /api/v1/usuarios/{id}",
        senha_alterada=senha_alterada,
    )

    db.commit()
    db.refresh(usuario)
    return usuario


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_usuario(
    usuario_id: int,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Desativa um usuário (soft delete). Restrito a administrador.

    As travas ficam em `_garantir_desativacao_segura`, compartilhadas com o
    PUT: era a duplicação que permitia as duas rotas divergirem.
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    _garantir_desativacao_segura(db, usuario, admin)

    antes = instantaneo(usuario)
    usuario.ativo = False
    # Mesma função do PUT: o evento gravado é o mesmo, só muda a `origem`.
    # Desativar quem já estava inativo não muda nada e, por isso, não gera
    # evento — a trilha registra mudança, não requisição.
    registrar_alteracoes(
        db,
        usuario=usuario,
        antes=antes,
        ator=admin,
        origem="DELETE /api/v1/usuarios/{id}",
    )
    db.commit()
    return None
