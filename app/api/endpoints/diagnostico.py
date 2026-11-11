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

from app.api.deps import get_db, is_admin, is_conta_do_painel, is_staff
from app.core.config import settings
from app.models.setor import Setor
from app.models.usuario import Usuario
from app.models.role import Role
from app.services.leitura_service import setores_lidos_pelo_perfil

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

    try:
        # 10. Setores da TI (API-6): o que a configuração diz e se o cadastro
        # confirma. A configuração não enxerga o banco — é aqui que um id
        # inexistente ou inativo aparece.
        diagnostico["equipes"] = _diagnostico_das_equipes(db)
    except Exception:
        logger.error("Diagnóstico: conferência dos setores da TI falhou", exc_info=True)
        diagnostico["equipes"] = {"erro": "❌ ERRO ao consultar (detalhe no log da aplicação)"}
        diagnostico["status"] = "erro"

    try:
        # 11. Contas do painel (API-11, S1): a mesma conferência, para
        # PAINEL_CONTAS_IDS contra `usuarios`.
        diagnostico["painel"] = _diagnostico_do_painel(db)
    except Exception:
        logger.error("Diagnóstico: conferência das contas do painel falhou", exc_info=True)
        diagnostico["painel"] = {"erro": "❌ ERRO ao consultar (detalhe no log da aplicação)"}
        diagnostico["status"] = "erro"

    return diagnostico


def _diagnostico_do_painel(db: Session) -> dict:
    """
    `PAINEL_CONTAS_IDS` contra o cadastro: quais ids leem os lembretes agora
    e por que os outros não leem. Só ids — nem nome, nem perfil, nem setor:
    reconhecer qual conta é a TV é dos SELECTs de docs/contas-de-servico.md.
    """
    lidos = settings.painel_contas
    contas = {u.id: u for u in db.query(Usuario).filter(Usuario.id.in_(lidos.ids)).all()} if lidos.ids else {}
    inexistentes = sorted(i for i in lidos.ids if i not in contas)
    inativas = sorted(i for i, u in contas.items() if u.ativo is not True)
    humanas = sorted(i for i, u in contas.items() if u.conta_de_servico is not True)
    autorizadas = sorted(i for i, u in contas.items() if is_conta_do_painel(u))

    alertas = []
    if lidos.estado != "valida":
        alertas.append(f"⚠️ PAINEL_CONTAS_IDS {lidos.estado}: nenhuma conta lê os lembretes como painel")
    if inexistentes:
        alertas.append(f"⚠️ PAINEL_CONTAS_IDS cita usuário(s) inexistente(s): {inexistentes}")
    if inativas:
        alertas.append(f"⚠️ PAINEL_CONTAS_IDS cita conta(s) inativa(s), que não leem: {inativas}")
    if humanas:
        alertas.append(f"⚠️ PAINEL_CONTAS_IDS cita conta(s) que não são de serviço, que não leem como painel: {humanas}")

    return {
        "painel_contas_ids": {
            "estado": lidos.estado,
            "configurados": sorted(lidos.ids),
            "autorizadas": autorizadas,
            "inexistentes": inexistentes,
            "inativas": inativas,
            "nao_sao_de_servico": humanas,
        },
        "alertas": alertas,
    }


def _diagnostico_das_equipes(db: Session) -> dict:
    """
    `SETORES_TI_IDS` contra o cadastro, e quantos técnicos ativos ficam sem
    alcance por perfil — os que só leem pelo vínculo (H1, D10).

    Só ids e contagens: os nomes das pessoas ficam para os SELECTs de
    diagnóstico do CHANGELOG, rodados por quem administra o banco.
    """
    lidos = settings.setores_ti
    setores = {s.id: s for s in db.query(Setor).filter(Setor.id.in_(lidos.ids)).all()} if lidos.ids else {}
    qualidade = settings.SETOR_QUALIDADE_ID
    tecnicos = [
        u for u in db.query(Usuario).filter(Usuario.ativo.is_(True)).all()
        if is_staff(u) and not is_admin(u)
    ]
    sem_alcance = sum(1 for u in tecnicos if not setores_lidos_pelo_perfil(u))

    alertas = []
    if lidos.estado != "valida" or not settings.setores_ti_ids:
        alertas.append(
            f"⚠️ SETORES_TI_IDS {lidos.estado}: nenhum técnico tem alcance de TI "
            "nem administra cadastros; só o administrador"
        )
    inexistentes = sorted(i for i in lidos.ids if i not in setores)
    inativos = sorted(i for i, s in setores.items() if not s.ativo)
    if inexistentes:
        alertas.append(f"⚠️ SETORES_TI_IDS cita setor(es) inexistente(s): {inexistentes}")
    if inativos:
        alertas.append(f"⚠️ SETORES_TI_IDS cita setor(es) inativo(s): {inativos}")
    if qualidade is not None and qualidade in lidos.ids:
        alertas.append("⚠️ SETORES_TI_IDS inclui o setor da Qualidade, que não vale como TI")
    if sem_alcance:
        alertas.append(f"⚠️ {sem_alcance} técnico(s) ativo(s) sem alcance por perfil: só leem pelo vínculo")

    return {
        "setores_ti_ids": {
            "estado": lidos.estado,
            "configurados": sorted(lidos.ids),
            "validos_como_ti": sorted(settings.setores_ti_ids),
            "inexistentes": inexistentes,
            "inativos": inativos,
        },
        "setor_qualidade_id": qualidade,
        "tecnicos_ativos": len(tecnicos),
        "tecnicos_ativos_sem_alcance": sem_alcance,
        "alertas": alertas,
    }


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
