from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.endpoints import chamados, usuarios, comentarios, setores, categorias, historico

# Criar aplicação FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
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
app.include_router(
    chamados.router,
    prefix="/api/v1/chamados",
    tags=["Chamados"]
)

app.include_router(
    usuarios.router,
    prefix="/api/v1/usuarios",
    tags=["Usuários"]
)

app.include_router(
    comentarios.router,
    prefix="/api/v1/comentarios",
    tags=["Comentários"]
)

app.include_router(
    setores.router,
    prefix="/api/v1/setores",
    tags=["Setores"]
)

app.include_router(
    categorias.router,
    prefix="/api/v1/categorias",
    tags=["Categorias"]
)

app.include_router(
    historico.router,
    prefix="/api/v1/historico",
    tags=["Histórico"]
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
