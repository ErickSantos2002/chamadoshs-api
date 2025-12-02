from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

# Contexto para hash de senhas com bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verificar_senha(senha_plana: str, senha_hash: str) -> bool:
    """
    Verifica se a senha plana corresponde ao hash
    Trunca para 72 bytes (limite do bcrypt)
    """
    # Truncar para 72 bytes (limite do bcrypt)
    senha_bytes = senha_plana.encode('utf-8')[:72]
    senha_truncada = senha_bytes.decode('utf-8', errors='ignore')
    return pwd_context.verify(senha_truncada, senha_hash)


def gerar_hash_senha(senha: str) -> str:
    """
    Gera hash bcrypt da senha
    Trunca para 72 bytes (limite do bcrypt)
    """
    # Truncar para 72 bytes (limite do bcrypt)
    senha_bytes = senha.encode('utf-8')[:72]
    senha_truncada = senha_bytes.decode('utf-8', errors='ignore')
    return pwd_context.hash(senha_truncada)


def criar_token_acesso(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Cria um token JWT de acesso
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    return encoded_jwt


def decodificar_token(token: str) -> Optional[dict]:
    """
    Decodifica e valida um token JWT
    """
    try:
        print(f"🔵 [Security] Decodificando token...")
        print(f"🔵 [Security] SECRET_KEY length: {len(settings.SECRET_KEY)}")
        print(f"🔵 [Security] ALGORITHM: {settings.ALGORITHM}")
        print(f"🔵 [Security] Token: {token[:50]}...")

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

        print(f"✅ [Security] Token decodificado com sucesso!")
        print(f"✅ [Security] Payload: {payload}")

        return payload
    except JWTError as e:
        print(f"❌ [Security] Erro ao decodificar token: {type(e).__name__}")
        print(f"❌ [Security] Mensagem: {str(e)}")
        return None
