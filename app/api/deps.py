import unicodedata
from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from app.core.database import SessionLocal
from app.core.security import decodificar_token
from app.models.usuario import Usuario

# Nomes das roles como gravados na tabela `roles` (ver schema_chamados.sql).
ROLE_ADMIN = "Administrador"
ROLE_TECNICO = "Tecnico"
ROLE_USUARIO = "Usuario"

# auto_error=False é obrigatório: com o padrão (True), a ausência do header
# Authorization gera 403, não 401. O frontend só trata 401 (redireciona para
# o login) — um 403 aqui deixaria a tela quebrada em silêncio.
security = HTTPBearer(auto_error=False)


def get_db() -> Generator:
    """
    Dependency que fornece uma sessão do banco de dados
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> Usuario:
    """
    Dependency que retorna o usuário autenticado a partir do token JWT
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decodificar_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # joinedload da role: require_roles() lê current_user.role.nome em toda
    # requisição protegida — sem isso seria uma query extra por request.
    usuario = (
        db.query(Usuario)
        .options(joinedload(Usuario.role))
        .filter(Usuario.id == user_id)
        .first()
    )
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado"
        )

    if not usuario.ativo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo"
        )

    return usuario


def _normalizar_role(nome: Optional[str]) -> str:
    """
    Compara nomes de role sem depender de acento ou caixa.

    A tabela grava "Tecnico", mas se algum dia virar "Técnico" a comparação
    literal passaria a rejeitar todos os técnicos com um 403 que parece bug.
    """
    sem_acento = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return sem_acento.strip().casefold()


def require_roles(*nomes: str):
    """
    Fábrica de dependency que exige que o usuário tenha uma das roles dadas.

    A role vem do banco (current_user.role.nome), não da claim do JWT: a claim
    fica congelada até o token expirar, então rebaixar um administrador só
    surtiria efeito na renovação. O banco é autoritativo na hora.
    """
    permitidos = {_normalizar_role(n) for n in nomes}

    def _verificar(current_user: Usuario = Depends(get_current_user)) -> Usuario:
        atual = _normalizar_role(current_user.role.nome if current_user.role else None)
        if atual not in permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requer perfil: {', '.join(nomes)}",
            )
        return current_user

    return _verificar


require_admin = require_roles(ROLE_ADMIN)
require_staff = require_roles(ROLE_ADMIN, ROLE_TECNICO)


def is_admin(usuario: Usuario) -> bool:
    return _normalizar_role(usuario.role.nome if usuario.role else None) == _normalizar_role(ROLE_ADMIN)


def is_staff(usuario: Usuario) -> bool:
    atual = _normalizar_role(usuario.role.nome if usuario.role else None)
    return atual in {_normalizar_role(ROLE_ADMIN), _normalizar_role(ROLE_TECNICO)}
