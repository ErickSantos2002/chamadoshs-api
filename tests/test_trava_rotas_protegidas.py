"""
Testes da trava de proteção de rotas do `main.py`.

Esta trava é o único mecanismo que impede um endpoint novo de entrar em
produção sem autenticação: ela percorre as rotas registradas e derruba a
aplicação na inicialização se alguma rota /api/v1 não exigir
`get_current_user`.

Sendo o mecanismo que protege todos os outros, ela precisa de teste próprio.
Uma trava quebrada não avisa que quebrou — ela simplesmente para de pegar, e a
primeira notícia vem na forma de endpoint aberto em produção.

Os testes montam apps sintéticos e trocam o global `main.app` por eles.
`_rotas_desprotegidas` lê esse global na hora da chamada, então dá para
exercitar a trava contra qualquer topologia de rotas sem alterar o `main.py`
nem subir versão nova por causa de teste.
"""

import pytest
from fastapi import Depends, FastAPI

import main
from app.api.deps import get_current_user, require_admin, require_staff


@pytest.fixture
def app_de_teste(monkeypatch):
    """Devolve um app vazio já instalado no lugar do global do main."""
    app = FastAPI()
    monkeypatch.setattr(main, "app", app)
    return app


def test_rota_sem_autenticacao_e_detectada(app_de_teste):
    """O caso que justifica a trava existir: endpoint novo, sem proteção."""
    @app_de_teste.get("/api/v1/esquecido")
    def esquecido():
        return {}

    assert main._rotas_desprotegidas() == ["GET /api/v1/esquecido"]


def test_dependency_no_router_protege(app_de_teste):
    """Padrão adotado no projeto: autenticação no include_router."""
    sub = FastAPI()

    @sub.get("/protegido")
    def protegido():
        return {}

    app_de_teste.include_router(
        sub.router,
        prefix="/api/v1",
        dependencies=[Depends(get_current_user)],
    )

    assert main._rotas_desprotegidas() == []


def test_dependency_no_proprio_handler_protege(app_de_teste):
    """
    Vários handlers declaram `current_user` como parâmetro, além da proteção
    do router. A trava tem de reconhecer as duas formas.
    """
    @app_de_teste.get("/api/v1/protegido")
    def protegido(current_user=Depends(get_current_user)):
        return {}

    assert main._rotas_desprotegidas() == []


@pytest.mark.parametrize("dependency", [require_admin, require_staff])
def test_protecao_indireta_por_perfil_conta(app_de_teste, dependency):
    """
    require_admin e require_staff saem de require_roles, cuja função interna
    depende de get_current_user. A trava só enxerga isso porque desce na
    árvore de dependências — se voltar a comparar só o primeiro nível, estas
    rotas passariam a ser acusadas de desprotegidas e a aplicação não subiria.
    """
    @app_de_teste.get("/api/v1/restrito")
    def restrito(_=Depends(dependency)):
        return {}

    assert main._rotas_desprotegidas() == []


def test_rota_publica_registrada_e_liberada(app_de_teste):
    """O login precisa ser público, e está em ROTAS_PUBLICAS."""
    @app_de_teste.post("/api/v1/auth/login")
    def login():
        return {}

    assert main._rotas_desprotegidas() == []


def test_metodo_fora_da_lista_publica_nao_e_liberado(app_de_teste):
    """
    ROTAS_PUBLICAS libera o par (método, caminho), não o caminho inteiro. Um
    GET no mesmo caminho do login continua exigindo autenticação.
    """
    @app_de_teste.get("/api/v1/auth/login")
    def login_get():
        return {}

    assert main._rotas_desprotegidas() == ["GET /api/v1/auth/login"]


def test_rota_fora_de_api_v1_e_ignorada(app_de_teste):
    """/ e /health são públicas para o healthcheck do Docker e do Easypanel."""
    @app_de_teste.get("/health")
    def health():
        return {}

    assert main._rotas_desprotegidas() == []


def test_varias_desprotegidas_sao_todas_reportadas(app_de_teste):
    """
    A mensagem de erro precisa listar tudo: descobrir uma rota aberta por vez,
    a cada tentativa de subir, é o pior jeito de corrigir isso.
    """
    @app_de_teste.get("/api/v1/um")
    def um():
        return {}

    @app_de_teste.post("/api/v1/dois")
    def dois():
        return {}

    assert sorted(main._rotas_desprotegidas()) == [
        "GET /api/v1/um",
        "POST /api/v1/dois",
    ]


def test_aplicacao_real_nao_tem_rota_desprotegida():
    """
    Sem monkeypatch: roda a trava contra o app de verdade.

    A trava já faz esta checagem no import, então em condições normais este
    teste é redundante — o import do módulo falharia antes. Ele existe para o
    caso de alguém remover a verificação de inicialização e a suíte continuar
    guardando a invariante.
    """
    assert main._rotas_desprotegidas() == []
