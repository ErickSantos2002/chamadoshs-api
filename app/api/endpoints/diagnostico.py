from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db
from app.models.usuario import Usuario
from app.models.role import Role

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
    except Exception as e:
        diagnostico["database"]["conexao"] = f"❌ ERRO: {str(e)}"
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
    except Exception as e:
        diagnostico["auth"]["migration_executada"] = f"❌ ERRO: {str(e)}"
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

    except Exception as e:
        diagnostico["usuarios"]["erro"] = f"❌ ERRO: {str(e)}"
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
