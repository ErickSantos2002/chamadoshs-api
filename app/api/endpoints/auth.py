import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from datetime import timedelta

from app.api.deps import get_db, get_current_user, require_admin
from app.core.rate_limit import JanelaDeslizante
from app.models.usuario import Usuario
from app.models.role import Role
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    UsuarioCreate,
    AlterarSenhaRequest,
    UsuarioLogado
)
from app.core.security import verificar_senha, gerar_hash_senha, criar_token_acesso
from app.core.config import settings
from app.services.evento_conta_service import (
    instantaneo,
    registrar_alteracoes,
    registrar_criacao,
)

router = APIRouter()

logger = logging.getLogger(__name__)

# Com toda a API exigindo token, o login virou o único ponto de entrada — e
# aceitava tentativas ilimitadas. Os dois limitadores são complementares: o
# por usuário resiste a ataque distribuído, em que o IP muda a cada tentativa;
# o por IP contém a varredura de muitos usuários a partir de uma origem só.
_falhas_por_usuario = JanelaDeslizante(
    max_eventos=settings.LOGIN_MAX_FALHAS_POR_USUARIO,
    janela_segundos=settings.LOGIN_JANELA_SEGUNDOS,
)
_falhas_por_ip = JanelaDeslizante(
    max_eventos=settings.LOGIN_MAX_FALHAS_POR_IP,
    janela_segundos=settings.LOGIN_JANELA_SEGUNDOS,
)


def _ip_do_cliente(request: Request) -> str:
    """
    IP real do cliente, considerando os proxies confiáveis à frente.

    Lê X-Forwarded-For de trás para frente: o último elemento foi escrito pelo
    proxy mais próximo da aplicação e não é falsificável, enquanto o primeiro
    veio do cliente. Ver PROXY_HOPS_CONFIAVEIS em config.py.
    """
    hops = settings.PROXY_HOPS_CONFIAVEIS

    if hops > 0:
        encaminhado = request.headers.get("x-forwarded-for")
        if encaminhado:
            partes = [p.strip() for p in encaminhado.split(",") if p.strip()]
            if partes:
                indice = max(0, len(partes) - hops)
                return partes[indice]

    return request.client.host if request.client else "desconhecido"


def _chave_usuario(nome: str) -> str:
    # O login é case-insensitive (Usuario.nome.ilike), então a contagem também
    # precisa ser, senão alternar a caixa multiplicaria as tentativas.
    return nome.strip().casefold()


@router.post("/login", response_model=TokenResponse)
def login(request: Request, credentials: LoginRequest, db: Session = Depends(get_db)):
    """
    Endpoint de login - retorna token JWT (case-insensitive).

    Protegido contra força bruta por dois limitadores de tentativas falhas,
    um por usuário e outro por IP de origem. Ver config.py para os limites.
    """
    chave_usuario = _chave_usuario(credentials.nome)
    ip = _ip_do_cliente(request)

    # A verificação vem antes de qualquer consulta ao banco: além de proteger a
    # senha, evita que a tentativa bloqueada ainda custe I/O e um hash bcrypt.
    espera = max(
        _falhas_por_usuario.segundos_ate_liberar(chave_usuario),
        _falhas_por_ip.segundos_ate_liberar(ip),
    )
    if espera:
        logger.warning(
            "login bloqueado por excesso de tentativas: usuario=%r ip=%s espera=%ss",
            chave_usuario,
            ip,
            espera,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas de login. Tente novamente mais tarde.",
            headers={"Retry-After": str(espera)},
        )

    def _registrar_falha() -> None:
        _falhas_por_usuario.registrar(chave_usuario)
        _falhas_por_ip.registrar(ip)

    # Buscar usuário pelo nome (case-insensitive)
    usuario = db.query(Usuario).filter(
        Usuario.nome.ilike(credentials.nome)
    ).first()

    if not usuario:
        _registrar_falha()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos"
        )

    # Verificar se o usuário está ativo
    if not usuario.ativo:
        # Conta como falha: sem isso, uma conta desativada viraria um caminho
        # sem limite de tentativas e ainda confirmaria que o nome existe.
        _registrar_falha()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário inativo"
        )

    # Verificar senha
    if not usuario.senha_hash or not verificar_senha(credentials.senha, usuario.senha_hash):
        _registrar_falha()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos"
        )

    # Credencial correta: zera as contagens para não punir quem só errou a
    # senha algumas vezes antes de acertar.
    _falhas_por_usuario.limpar(chave_usuario)
    _falhas_por_ip.limpar(ip)

    # Buscar role do usuário
    role = db.query(Role).filter(Role.id == usuario.role_id).first()
    role_nome = role.nome if role else "Usuario"

    # Criar token JWT
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = criar_token_acesso(
        data={"sub": str(usuario.id), "nome": usuario.nome, "role": role_nome},
        expires_delta=access_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=usuario.id,
        nome=usuario.nome,
        role=role_nome
    )


@router.post("/registro", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def registrar_usuario(
    usuario_data: UsuarioCreate,
    admin: Usuario = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Cria novo usuário e retorna token. Restrito a administrador.

    O corpo aceita role_id, então enquanto este endpoint era público bastava
    uma requisição sem credencial nenhuma para criar uma conta Administrador.

    Duplica POST /api/v1/usuarios/, mantido por compatibilidade. Para criar o
    primeiro usuário num banco vazio, use criar_usuario_inicial.sql.
    """
    # Verificar se o nome de usuário já existe
    usuario_existe = db.query(Usuario).filter(Usuario.nome == usuario_data.nome).first()
    if usuario_existe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome de usuário já cadastrado"
        )

    # Criar hash da senha
    senha_hash = gerar_hash_senha(usuario_data.senha)

    # Criar usuário
    novo_usuario = Usuario(
        nome=usuario_data.nome,
        senha_hash=senha_hash,
        setor_id=usuario_data.setor_id,
        role_id=usuario_data.role_id,
        ativo=usuario_data.ativo
    )

    db.add(novo_usuario)
    # Esta rota duplica POST /api/v1/usuarios/. Enquanto as duas existirem, as
    # duas gravam evento de criação — senão a trilha teria um buraco que só
    # aparece quando alguém usa a rota antiga.
    db.flush()
    registrar_criacao(
        db, usuario=novo_usuario, ator=admin, origem="POST /api/v1/auth/registro"
    )
    db.commit()
    db.refresh(novo_usuario)

    # Buscar role do usuário
    role = db.query(Role).filter(Role.id == novo_usuario.role_id).first()
    role_nome = role.nome if role else "Usuario"

    # Criar token JWT
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = criar_token_acesso(
        data={"sub": str(novo_usuario.id), "nome": novo_usuario.nome, "role": role_nome},
        expires_delta=access_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=novo_usuario.id,
        nome=novo_usuario.nome,
        role=role_nome
    )


@router.get("/me", response_model=UsuarioLogado)
def obter_usuario_logado(current_user: Usuario = Depends(get_current_user)):
    """
    Retorna informações do usuário logado
    """
    return UsuarioLogado(
        id=current_user.id,
        nome=current_user.nome,
        setor_id=current_user.setor_id,
        role_id=current_user.role_id,
        ativo=current_user.ativo
    )


@router.post("/alterar-senha")
def alterar_senha(
    dados: AlterarSenhaRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Altera a senha do usuário logado
    """
    # Verificar senha atual
    if not current_user.senha_hash or not verificar_senha(dados.senha_atual, current_user.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta"
        )

    # Atualizar senha
    antes = instantaneo(current_user)
    current_user.senha_hash = gerar_hash_senha(dados.senha_nova)
    # Ator e alvo são a mesma conta. O que classifica o evento em auditoria,
    # porém, é a `origem`, e NÃO `ator_id == usuario_id`: o botão de resetar
    # senha da aba de Usuários aparece também na linha do próprio
    # administrador, então um reset de si mesmo chega por
    # `PUT /usuarios/{id}` com ator e alvo iguais.
    #
    # A diferença é de fundo, não de forma: esta rota exige a senha atual
    # ("trocou sabendo a antiga") e o PUT não ("sobrescreveu usando poder de
    # administrador"). Só a rota separa as duas.
    registrar_alteracoes(
        db,
        usuario=current_user,
        antes=antes,
        ator=current_user,
        origem="POST /api/v1/auth/alterar-senha",
        senha_alterada=True,
    )
    db.commit()

    return {"message": "Senha alterada com sucesso"}


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Renova o token JWT do usuário logado
    """
    # Buscar role do usuário
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    role_nome = role.nome if role else "Usuario"

    # Criar novo token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = criar_token_acesso(
        data={"sub": str(current_user.id), "nome": current_user.nome, "role": role_nome},
        expires_delta=access_token_expires
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=current_user.id,
        nome=current_user.nome,
        role=role_nome
    )
