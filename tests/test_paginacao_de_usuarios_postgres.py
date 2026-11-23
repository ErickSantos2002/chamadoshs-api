"""
A paginação da listagem de usuários (API-17) em PostgreSQL real.

Os testes de `test_paginacao_de_usuarios.py`, importados para cá e rodados
com um `sessao` diferente: um PostgreSQL descartável criado pelo
`schema_chamados.sql`. É aqui que a falta de `ORDER BY` aparece de fato — no
SQLite a varredura já sai por `id`. A fixture `muitos` regrava parte das
linhas depois da carga, e no PostgreSQL a versão nova da linha vai para o fim
da tabela: sem ordem declarada, as páginas deixam de seguir o `id`.

Também é aqui que o teto importa: `LIMIT` grande demais no banco de produção
é varredura da tabela inteira a partir de query string.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_paginacao_de_usuarios import (  # noqa: F401
    TestAConsultaDeclaraAOrdem,
    TestFiltrosMantemAOrdem,
    TestFormatoDaResposta,
    TestLimite,
    TestOrdem,
    TestPaginasCompletas,
    TestPermissoesNaoMudam,
    TestSkip,
    muitos,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_api17") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_api17", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
