import unicodedata
from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from app.core.config import settings
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


_require_perfil_admin = require_roles(ROLE_ADMIN)
require_staff = require_roles(ROLE_ADMIN, ROLE_TECNICO)


def is_admin(usuario: Usuario) -> bool:
    """
    O perfil de administrador, só o perfil. Vale para a LEITURA (o
    administrador lê todos os chamados), inclusive na conta de serviço: o
    painel de parede pode ser uma. Para administrar, `is_admin_humano`.
    """
    return _normalizar_role(usuario.role.nome if usuario.role else None) == _normalizar_role(ROLE_ADMIN)


def is_admin_humano(usuario: Usuario) -> bool:
    """
    Administrador que é pessoa (API-11, S3): o perfil e `conta_de_servico`
    igual a `False`.

    O perfil sozinho não faz da conta de serviço um operador humano
    privilegiado. A conta compartilhada de administração (migration de
    `conta_de_servico`) resetava a senha de qualquer um, excluía chamado de
    vez e mudava perfil — e a trilha dizia "foi a conta", não quem. Só
    `False` conta como pessoa, como em `integra_equipe_ti`.
    """
    return is_admin(usuario) and usuario.conta_de_servico is False


CONTA_DE_SERVICO_SEM_ADMINISTRACAO = "Conta de serviço não executa administração"


def require_admin(current_user: Usuario = Depends(_require_perfil_admin)) -> Usuario:
    """
    Exige administrador humano (API-11, S3): o perfil, e não ser conta de
    serviço.

    Cobre tudo o que é só do administrador: usuários (criar, editar — senha,
    perfil, setor, `conta_de_servico` —, desativar, reativar, eventos),
    `POST /auth/registro`, excluir chamado e setor, e o diagnóstico. A conta de
    serviço administradora continua autenticando e lendo; recebe 403 aqui,
    com um motivo próprio — quem não tem o perfil recebe o de sempre.
    """
    if current_user.conta_de_servico is not False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CONTA_DE_SERVICO_SEM_ADMINISTRACAO)
    return current_user


def is_staff(usuario: Usuario) -> bool:
    atual = _normalizar_role(usuario.role.nome if usuario.role else None)
    return atual in {_normalizar_role(ROLE_ADMIN), _normalizar_role(ROLE_TECNICO)}


EQUIPE_TI_NEGADA = "Requer perfil: Administrador ou Técnico da TI"


def require_equipe_ti(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """
    Exige administrador ou técnico da TI (API-7, D13): a administração global
    — setores, categorias, SLA, tarefas recorrentes e a trilha de setor.

    Até a API-6 essas rotas usavam `require_staff`, e técnico de QUALQUER
    setor as administrava: o da Qualidade, o de outro setor, o sem setor. O
    perfil sozinho não diz de qual equipe a pessoa é.

    Quem é da TI sai de `integra_equipe_ti`, a mesma regra da API-6 que decide
    o responsável de chamado da TI e que `/auth/me` devolve à tela — uma regra
    só, para que a tela, a atribuição e a administração não discordem. Sem
    `SETORES_TI_IDS` válida, nenhum técnico passa; o administrador passa
    sempre, pelo perfil, esteja em que setor estiver.

    403, e não 404: são recursos globais, cuja existência não é segredo (D6
    vale para chamados e comentários). Mesmo corpo para toda recusa.

    O administrador é o humano (API-11, S3): a conta de serviço
    administradora não passa mais pelo perfil, e a técnica já não passava
    (API-10). Nenhuma conta de serviço administra o que esta dependency guarda.
    """
    # Import tardio: `leitura_service` importa `is_admin` e `is_staff` daqui.
    from app.services.leitura_service import integra_equipe_ti

    # `integra_equipe_ti` já exige perfil de equipe: usuário comum e perfil
    # desconhecido não passam, nem num setor da TI.
    if is_admin_humano(current_user) or integra_equipe_ti(current_user):
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=EQUIPE_TI_NEGADA)


def is_conta_do_painel(usuario: Usuario) -> bool:
    """
    Conta de serviço do painel de parede (API-11, S1): ativa, com
    `conta_de_servico` verdadeiro e com o id em `PAINEL_CONTAS_IDS`.

    As três vêm do usuário que `get_current_user` leu do banco pelo `sub` do
    token — nada do pedido, nem nome, perfil, setor, IP ou User-Agent. O
    `ativo` é conferido de novo aqui, embora `get_current_user` já recuse o
    inativo: esta exceção não pode depender de quem a chama. Um id de pessoa
    na lista não vale: a lista não é autorização por id, é a identificação da
    TV entre as contas de serviço.
    """
    return (
        usuario.conta_de_servico is True
        and usuario.ativo is True
        and usuario.id in settings.painel_contas_ids
    )


def require_leitura_dos_lembretes(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    """
    Quem lê `GET /tarefas-recorrentes/lembretes-do-dia` (API-11, S1): quem
    passa em `require_equipe_ti`, e a conta do painel (`is_conta_do_painel`).

    Só esta rota usa esta dependency. A conta do painel não vira equipe —
    `integra_equipe_ti`, `/auth/me` e as sete rotas do módulo não mudam — nem
    administradora, qualquer que seja o perfil dela. A recusa é a de
    `require_equipe_ti`, o mesmo corpo para todos: estar ou não na lista não
    aparece na resposta.
    """
    if is_conta_do_painel(current_user):
        return current_user
    return require_equipe_ti(current_user)
