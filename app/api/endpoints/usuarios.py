from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db, require_admin, ROLE_ADMIN, _normalizar_role
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate, UsuarioResponse
from app.core.security import gerar_hash_senha

router = APIRouter()


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
    _admin: Usuario = Depends(require_admin),
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
    db.commit()
    db.refresh(usuario)
    return usuario


@router.put("/{usuario_id}", response_model=UsuarioResponse)
def atualizar_usuario(
    usuario_id: int,
    usuario_data: UsuarioUpdate,
    _admin: Usuario = Depends(require_admin),
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

    # Se está atualizando a senha, gera o hash
    if 'senha' in update_data:
        senha_hash = gerar_hash_senha(update_data.pop('senha'))
        update_data['senha_hash'] = senha_hash

    for field, value in update_data.items():
        setattr(usuario, field, value)

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

    Bloqueia dois casos que deixariam o sistema sem quem administrar:
    desativar a si mesmo e desativar o último administrador ativo. Como
    criar e editar usuário também exigem administrador, não haveria
    recuperação pela aplicação — só por SQL direto no banco.
    """
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    if usuario.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Não é possível desativar o próprio usuário",
        )

    if usuario.ativo and _normalizar_role(usuario.role.nome if usuario.role else None) == _normalizar_role(ROLE_ADMIN):
        admins_ativos = (
            db.query(Usuario)
            .join(Usuario.role)
            .filter(Usuario.ativo.is_(True), Usuario.role_id == usuario.role_id)
            .count()
        )
        if admins_ativos <= 1:
            raise HTTPException(
                status_code=400,
                detail="Não é possível desativar o último administrador ativo",
            )

    usuario.ativo = False
    db.commit()
    return None
