"""
A política de leitura (API-5) em PostgreSQL real.

Os mesmos testes de `test_politica_de_leitura.py` e das rotas
(`test_leitura_por_chamado.py`), importados para cá e rodados com um `sessao`
diferente: um PostgreSQL descartável criado pelo `schema_chamados.sql`. O
SQLite já prova a regra; aqui o que se prova é o SQL dela no banco de
produção — o OR do escopo, o IN do setor, a paginação sobre o conjunto
filtrado, os arquivados e cancelados — e o trigger da versão na reatribuição.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from leitura_cenario import cenario_de_leitura  # noqa: F401
from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_politica_de_leitura import (  # noqa: F401
    TestCasosDeBorda,
    test_escopo_sql_e_predicado_dizem_o_mesmo,
    test_matriz_do_predicado,
)
from test_leitura_por_chamado import (  # noqa: F401
    TestContas,
    TestExResponsavel,
    TestForaDoEscopo,
    TestListagem,
    como,
    test_a_recusa_nao_diz_nada_do_chamado,
    test_leitura_de_um_chamado_em_todas_as_rotas,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_leitura") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_leitura", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
