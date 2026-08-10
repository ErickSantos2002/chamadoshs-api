"""
Fixtures de banco e de cliente HTTP para os testes de endpoint.

Por que existe um banco aqui, se o conftest da raiz diz que nenhum teste toca
o banco: aquela regra é sobre não depender de um PostgreSQL rodando — nada de
serviço externo, nada de flake por ambiente. SQLite em memória preserva isso
inteiro. Sobe e morre dentro do processo, sem rede, e cada teste recebe um
banco novo, então a ordem de execução não influencia resultado.

Os models são usados de verdade, não imitados. O ponto destes testes é provar
o que o handler grava no banco — com uma sessão falsa, metade do teste estaria
verificando a imitação em vez do handler.

Os models não usam nenhum tipo específico de PostgreSQL, o que torna o
`create_all` no SQLite fiel o suficiente para o que se quer verificar aqui.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from app.api.deps import get_db
from app.core.database import Base
from app.core.security import criar_token_acesso
from app.models import (
    Categoria,
    Chamado,
    Role,
    Setor,
    TarefaRecorrente,
    Usuario,
)

# Nomes das roles como gravados na tabela (ver schema_chamados.sql). As
# dependencies de perfil leem daqui, então errar o nome faria todo require_staff
# devolver 403 e os testes falhariam por motivo errado.
ROLES = [
    (1, "Administrador"),
    (2, "Tecnico"),
    (3, "Usuario"),
]


@pytest.fixture
def sessao():
    """
    Banco em memória com o schema dos models, isolado por teste.

    StaticPool é obrigatório: sem ele cada conexão nova receberia um banco
    :memory: próprio e vazio, e o que o handler gravasse sumiria antes da
    verificação.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = Session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def dados(sessao):
    """
    Popula o mínimo para exercitar autoria: três perfis, um chamado e uma
    tarefa recorrente.

    Devolve um dicionário simples em vez dos objetos ORM: depois de um commit
    dentro do handler, instâncias presas a outra sessão expiram, e comparar
    ids evita esse tipo de falso negativo.
    """
    for role_id, nome in ROLES:
        sessao.add(Role(id=role_id, nome=nome))
    sessao.add(Setor(id=1, nome="TI"))
    sessao.add(Categoria(id=1, nome="Hardware"))
    sessao.flush()

    admin = Usuario(id=10, nome="admin.teste", role_id=1, setor_id=1, ativo=True)
    tecnico = Usuario(id=20, nome="tecnico.teste", role_id=2, setor_id=1, ativo=True)
    comum = Usuario(id=30, nome="usuario.teste", role_id=3, setor_id=1, ativo=True)
    sessao.add_all([admin, tecnico, comum])
    sessao.flush()

    chamado = Chamado(
        id=100,
        protocolo="CH-TESTE-100",
        solicitante_id=comum.id,
        categoria_id=1,
        titulo="Impressora não liga",
        descricao="Não dá sinal de vida",
        status="Aberto",
        prioridade="Média",
    )
    tarefa = TarefaRecorrente(
        id=200,
        titulo="Backup semanal",
        tipo_recorrencia="semanal",
        intervalo=1,
        dia_semana=1,
        proxima_data=date(2026, 8, 10),
        prioridade="Média",
        ativo=True,
    )
    sessao.add_all([chamado, tarefa])
    sessao.commit()

    return {
        "admin_id": admin.id,
        "tecnico_id": tecnico.id,
        "comum_id": comum.id,
        "chamado_id": chamado.id,
        "tarefa_id": tarefa.id,
    }


@pytest.fixture
def cliente(sessao):
    """TestClient com o get_db apontando para o banco em memória."""
    def _get_db_de_teste():
        yield sessao

    main.app.dependency_overrides[get_db] = _get_db_de_teste
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


@pytest.fixture
def autenticar():
    """
    Devolve o header Authorization de um usuário, com token de verdade.

    Token real em vez de sobrescrever get_current_user: assim o caminho
    completo é exercitado, incluindo a leitura da role no banco — que é o que
    require_staff consulta.
    """
    def _para(usuario_id: int, nome: str = "usuario", role: str = "Usuario"):
        token = criar_token_acesso(data={"sub": str(usuario_id), "nome": nome, "role": role})
        return {"Authorization": f"Bearer {token}"}

    return _para
