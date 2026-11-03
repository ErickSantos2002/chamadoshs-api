"""
A C1 da API-10 em PostgreSQL real.

Os testes das contas de serviço nas rotas da equipe da TI, importados para cá
e rodados com um `sessao` diferente: um PostgreSQL descartável criado pelo
`schema_chamados.sql`. O SQLite já prova a regra; aqui o que se prova é ela
com o banco de produção — o `conta_de_servico` NOT NULL de verdade, as chaves
estrangeiras, e cada recusa sem escrita conferida contra o trigger que
incrementa a versão.

A matriz de `test_conta_de_servico_equipe_ti` não fica aqui: não toca o banco.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from leitura_cenario import cenario_de_leitura  # noqa: F401
from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_conta_de_servico_rotas import (  # noqa: F401
    TestAdministracao,
    TestAuthMe,
    TestComentariosInternos,
    TestOCasoDaHomologacao,
    TestAlcanceDePerfil,
    TestPendenciaContaDeServicoAdministradora,
    TestResponsaveisDaTI,
    como,
    configurar,
    saidas,
    servicos,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_api10") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_api10", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
