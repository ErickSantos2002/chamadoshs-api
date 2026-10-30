"""
As regras do comentário interno (API-8) em PostgreSQL real.

Os testes de leitura, criação, edição e exclusão do interno, importados para
cá e rodados com um `sessao` diferente: um PostgreSQL descartável criado pelo
`schema_chamados.sql`. O SQLite já prova a regra; aqui o que se prova é ela
com o banco de produção — o filtro `is_interno IS false` da listagem, o NULL
que a coluna aceita, e a recusa sem escrita conferida contra ele.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from leitura_cenario import cenario_de_leitura  # noqa: F401
from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_comentarios_internos import (  # noqa: F401
    TestCasosNomeados,
    como,
    configurar,
    internos,
    saidas,
    test_criacao,
    test_leitura_por_configuracao_e_perfil,
    test_o_interno_nao_vaza_por_outra_resposta,
)
from test_comentarios_internos import test_sem_token_continua_401 as test_sem_token_na_leitura  # noqa: F401
from test_comentarios_internos_edicao import (  # noqa: F401
    TestPoderesDeSempre,
    TestVisibilidade,
    proprios,
    test_autor_sem_acesso_ao_chamado,
    test_o_proprio_comentario,
)
from test_comentarios_internos_edicao import test_sem_token_continua_401 as test_sem_token_na_edicao  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_api8") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_api8", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
