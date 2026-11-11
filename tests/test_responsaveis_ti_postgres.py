"""
As regras da API-9 em PostgreSQL real.

Os testes da lista de responsáveis da TI e da recusa do inativo, importados
para cá e rodados com um `sessao` diferente: um PostgreSQL descartável criado
pelo `schema_chamados.sql`. O SQLite já prova a regra; aqui o que se prova é
ela com o banco de produção — a ordem por nome na collation do PostgreSQL, o
`IN` dos setores, o `joinedload` da role sem N+1, as chaves estrangeiras de
verdade, e a recusa sem escrita conferida contra o trigger que incrementa a
versão.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from leitura_cenario import cenario_de_leitura  # noqa: F401
from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_responsaveis_ti_lista import (  # noqa: F401
    TestListaEValidacaoNaoDiscordam,
    TestOQueVem,
    TestQuemPede,
    TestRota,
    candidatos,
    como,
    configurar,
)
from test_responsavel_ti_inativo import (  # noqa: F401
    TestChamadoAntigoComResponsavelInativo,
    TestNovaAtribuicao,
    TestOrdemDasRespostas,
    inativos,
    test_abertura_da_ti_continua_ignorando_o_responsavel_do_corpo,
    test_qualidade_continua_recusando_o_inativo_com_a_mensagem_dela,
    webhook,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_api9") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_api9", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
