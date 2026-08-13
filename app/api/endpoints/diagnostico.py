"""
Relatório administrativo do estado do sistema. Restrito a administrador (o
router inteiro, em main.py).

**Não confundir com `GET /api/v1/health`.** Os dois olham para o banco e param
de se parecer aí:

    /api/v1/health      público, um SELECT 1, chamado a cada 60s pela faixa de
                        status do frontend. Contrato fechado de três campos.
    /api/v1/diagnostico só administrador, conta usuários, lê information_schema
                        e monta amostra. Ferramenta de investigação, cara por
                        resposta, feita para ser aberta quando algo deu errado.

**As mensagens de exceção não entram na resposta.** Um `OperationalError` do
psycopg2 traz host, porta, usuário e nome do banco no texto. Aqui isso é menos
grave do que seria num endpoint público — quem lê já é administrador — mas
continua sendo detalhe de infraestrutura viajando por HTTP e parando em log de
proxy, histórico de navegador e print colado em conversa. O texto vai para o
log da aplicação, onde o acesso já é controlado, e a resposta diz o que falhou
sem dizer onde mora.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db
from app.models.usuario import Usuario
from app.models.role import Role

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def diagnostico_geral(db: Session = Depends(get_db)):
    """
    Endpoint de diagnóstico para verificar o estado do sistema
    """
    diagnostico = {
        "status": "ok",
        "database": {},
        "usuarios": {},
        "auth": {}
    }

    try:
        # 1. Verificar conexão com banco
        db.execute(text("SELECT 1"))
        diagnostico["database"]["conexao"] = "✅ OK"
    except Exception:
        logger.error("Diagnóstico: conexão com o banco falhou", exc_info=True)
        diagnostico["database"]["conexao"] = "❌ ERRO na conexão (detalhe no log da aplicação)"
        diagnostico["status"] = "erro"

    try:
        # 2. Verificar se coluna senha_hash existe
        result = db.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'usuarios' AND column_name = 'senha_hash'
        """)).fetchone()

        if result:
            diagnostico["auth"]["migration_executada"] = "✅ OK - Campo senha_hash existe"
        else:
            diagnostico["auth"]["migration_executada"] = "❌ FALTA - Execute migrations/add_auth_fields.sql"
            diagnostico["status"] = "erro"
    except Exception:
        logger.error("Diagnóstico: leitura de information_schema falhou", exc_info=True)
        diagnostico["auth"]["migration_executada"] = "❌ ERRO ao verificar (detalhe no log da aplicação)"
        diagnostico["status"] = "erro"

    try:
        # 3. Contar total de usuários
        total_usuarios = db.query(Usuario).count()
        diagnostico["usuarios"]["total"] = total_usuarios

        # 4. Contar usuários com senha
        usuarios_com_senha = db.query(Usuario).filter(
            Usuario.senha_hash.isnot(None),
            Usuario.senha_hash != ''
        ).count()
        diagnostico["usuarios"]["com_senha"] = usuarios_com_senha

        # 5. Contar usuários sem senha
        usuarios_sem_senha = db.query(Usuario).filter(
            (Usuario.senha_hash.is_(None)) | (Usuario.senha_hash == '')
        ).count()
        diagnostico["usuarios"]["sem_senha"] = usuarios_sem_senha

        # 6. Contar usuários ativos
        usuarios_ativos = db.query(Usuario).filter(Usuario.ativo == True).count()
        diagnostico["usuarios"]["ativos"] = usuarios_ativos

        # 7. Listar primeiros 5 usuários (sem senha_hash)
        usuarios = db.query(Usuario).limit(5).all()
        diagnostico["usuarios"]["amostra"] = [
            {
                "id": u.id,
                "nome": u.nome,
                "role_id": u.role_id,
                "tem_senha": "✅" if u.senha_hash else "❌",
                "ativo": "✅" if u.ativo else "❌"
            }
            for u in usuarios
        ]

        # 8. Verificar roles
        roles = db.query(Role).all()
        diagnostico["usuarios"]["roles_disponiveis"] = [
            {"id": r.id, "nome": r.nome}
            for r in roles
        ]

        # 9. Alertas
        alertas = []
        if total_usuarios == 0:
            alertas.append("⚠️ Nenhum usuário cadastrado. Crie um usuário primeiro.")
        if usuarios_com_senha == 0:
            alertas.append("⚠️ Nenhum usuário tem senha. Execute criar_usuario_inicial.sql")
        if usuarios_sem_senha > 0:
            alertas.append(f"⚠️ {usuarios_sem_senha} usuário(s) sem senha configurada")

        diagnostico["alertas"] = alertas

    except Exception:
        logger.error("Diagnóstico: consulta de usuários falhou", exc_info=True)
        diagnostico["usuarios"]["erro"] = "❌ ERRO ao consultar (detalhe no log da aplicação)"
        diagnostico["status"] = "erro"

    return diagnostico


@router.get("/usuarios-sem-senha")
def listar_usuarios_sem_senha(db: Session = Depends(get_db)):
    """
    Lista usuários que não têm senha configurada
    """
    usuarios = db.query(Usuario).filter(
        (Usuario.senha_hash.is_(None)) | (Usuario.senha_hash == '')
    ).all()

    return {
        "total": len(usuarios),
        "usuarios": [
            {
                "id": u.id,
                "nome": u.nome,
                "role_id": u.role_id,
                "ativo": u.ativo
            }
            for u in usuarios
        ],
        "instrucoes": "Execute o script criar_usuario_inicial.sql para adicionar senhas"
    }
