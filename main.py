from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.deps import get_current_user, require_admin
from app.api.endpoints import auth, chamados, usuarios, comentarios, setores, categorias, historico, diagnostico, eventos, health, sla_configs, tarefas_recorrentes

# Docs só em desenvolvimento. openapi_url precisa cair junto: sem isso,
# /openapi.json continuaria servindo o mapa completo da API e o bloqueio
# do /docs seria decorativo.
_docs_habilitados = settings.is_development

# Criar aplicação FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    docs_url="/docs" if _docs_habilitados else None,
    redoc_url="/redoc" if _docs_habilitados else None,
    openapi_url="/openapi.json" if _docs_habilitados else None,
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/")
def read_root():
    return {
        "message": "ChamadosHS API está rodando!",
        "version": settings.API_VERSION,
        "docs": "/docs"
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


# Incluir routers dos endpoints
#
# A autenticação é aplicada no nível do router, e não endpoint a endpoint, de
# propósito: toda a política fica visível nesta tela e qualquer endpoint novo
# nasce protegido. Restrições por perfil (require_admin / require_staff) são
# aplicadas por cima, dentro de cada router.

# Autenticação: único router com rotas públicas (login). As demais rotas dele
# exigem token individualmente.
app.include_router(
    auth.router,
    prefix="/api/v1/auth",
    tags=["Autenticação"]
)

app.include_router(
    chamados.router,
    prefix="/api/v1/chamados",
    tags=["Chamados"],
    dependencies=[Depends(get_current_user)],
)

app.include_router(
    usuarios.router,
    prefix="/api/v1/usuarios",
    tags=["Usuários"],
    dependencies=[Depends(get_current_user)],
)

app.include_router(
    comentarios.router,
    prefix="/api/v1/comentarios",
    tags=["Comentários"],
    dependencies=[Depends(get_current_user)],
)

app.include_router(
    setores.router,
    prefix="/api/v1/setores",
    tags=["Setores"],
    dependencies=[Depends(get_current_user)],
)

app.include_router(
    categorias.router,
    prefix="/api/v1/categorias",
    tags=["Categorias"],
    dependencies=[Depends(get_current_user)],
)

app.include_router(
    historico.router,
    prefix="/api/v1/historico",
    tags=["Histórico"],
    dependencies=[Depends(get_current_user)],
)

# Diagnóstico: ferramenta de debug que enumera usuários e diz quais estão sem
# senha. Registrado em todos os ambientes, porque serve justamente para
# investigar problema de deploy em produção, mas restrito a administrador.
#
# Atenção ao caso de bootstrap: num banco onde ninguém tem senha, não há como
# autenticar e portanto não há como consultar este endpoint. Nessa situação a
# verificação é por SQL direto no banco (ver criar_usuario_inicial.sql).
app.include_router(
    diagnostico.router,
    prefix="/api/v1/diagnostico",
    tags=["Diagnóstico"],
    dependencies=[Depends(require_admin)],
)

# Saúde da API. Único router de /api/v1 sem autenticação: a faixa de status do
# frontend aparece antes do login, e monitor externo não tem credencial. O que
# ele devolve é um contrato fechado de três campos — ver a docstring do módulo.
app.include_router(
    health.router,
    prefix="/api/v1",
    tags=["Saúde"],
)

# Trilha de auditoria dos cadastros (usuários e setores).
#
# Router próprio, e não uma rota dentro de /usuarios, por duas razões: a
# listagem cobre os dois cadastros — ficaria torto sob o prefixo de um deles —
# e `/usuarios/eventos` conviveria com `/usuarios/{usuario_id}` dependendo da
# ordem de declaração para não ser engolida pelo path int.
#
# A restrição de perfil NÃO fica aqui, e isso é exceção deliberada ao padrão
# desta tela: administrador vê a trilha inteira e técnico vê apenas eventos de
# setor, que é o cadastro que ele administra. Uma dependency de router só sabe
# dizer "entra ou não entra" — a distinção depende do parâmetro `alvo` da
# requisição, então mora no handler, junto com a explicação.
app.include_router(
    eventos.router,
    prefix="/api/v1/eventos",
    tags=["Auditoria"],
)

app.include_router(
    sla_configs.router,
    prefix="/api/v1/sla-configs",
    tags=["SLA"],
    dependencies=[Depends(get_current_user)],
)

app.include_router(
    tarefas_recorrentes.router,
    prefix="/api/v1/tarefas-recorrentes",
    tags=["Tarefas Recorrentes"],
    dependencies=[Depends(get_current_user)],
)


# Trava de proteção de rotas.
#
# Percorre as rotas registradas e falha na inicialização se alguma rota
# /api/v1 não exigir get_current_user. É o que impede que um endpoint novo
# entre desprotegido por esquecimento: em vez de virar um buraco silencioso
# em produção, a aplicação não sobe.
ROTAS_PUBLICAS = {
    ("POST", "/api/v1/auth/login"),
    # Saúde: a faixa de status do frontend precisa dele antes do login, e um
    # monitor externo não tem credencial. É público de propósito, e por isso a
    # resposta é um contrato fechado que não devolve nada sobre o ambiente —
    # ver app/api/endpoints/health.py.
    ("GET", "/api/v1/health"),
}


def _rotas_desprotegidas() -> list[str]:
    from fastapi.routing import APIRoute

    desprotegidas = []
    for rota in app.routes:
        if not isinstance(rota, APIRoute) or not rota.path.startswith("/api/v1"):
            continue

        metodos = rota.methods - {"HEAD", "OPTIONS"}
        if all((m, rota.path) in ROTAS_PUBLICAS for m in metodos):
            continue

        if not _exige_autenticacao(rota.dependant):
            desprotegidas.append(f"{','.join(sorted(metodos))} {rota.path}")

    return desprotegidas


def _exige_autenticacao(dependant) -> bool:
    if dependant.call is get_current_user:
        return True
    return any(_exige_autenticacao(sub) for sub in dependant.dependencies)


_desprotegidas = _rotas_desprotegidas()
if _desprotegidas:
    raise RuntimeError(
        "Rotas /api/v1 sem autenticação: "
        + "; ".join(_desprotegidas)
        + ". Adicione dependencies=[Depends(get_current_user)] no include_router "
        "ou registre a rota em ROTAS_PUBLICAS se ela for pública de propósito."
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
