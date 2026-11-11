"""
As regras da API-6 em PostgreSQL real.

Os testes de `SETORES_TI_IDS`, das escritas por alcance, do responsável da
TI e da edição de comentários, importados para cá e rodados com um `sessao`
diferente: um PostgreSQL descartável criado pelo `schema_chamados.sql`. O
SQLite já prova a regra; aqui o que se prova é ela com o banco de produção —
o `FOR UPDATE` antes da conferência de versão na Qualidade, o trigger que
incrementa a versão (a matriz lê a versão antes de cada pedido e confere que
a recusa não a mudou), o histórico no mesmo commit, as chaves estrangeiras
de verdade nos comentários.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from leitura_cenario import cenario_de_leitura  # noqa: F401
from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_setores_ti import TestClassificacao, TestConfiguracao, TestDiagnostico  # noqa: F401
from test_escritas_por_alcance import (  # noqa: F401
    TestEstados,
    TestPrecedencia,
    TestVinculoNaoDaPoderDeEquipe,
    como,
    test_matriz_de_escrita,
)
from test_responsavel_ti import (  # noqa: F401
    TestAutoatribuicao,
    TestChamadoAntigo,
    TestQualidadeInalterada,
    TestQuemPodeSerResponsavel,
    test_abertura_da_ti_continua_ignorando_responsavel_no_corpo,
    webhook,
)
from test_comentarios_edicao import (  # noqa: F401
    TestRegrasDeSempre,
    comentarios,
    test_edicao_e_exclusao,
    test_ex_responsavel_perde_a_edicao_quando_e_reatribuido,
    test_recusa_de_quem_nao_ve_e_igual_a_de_inexistente,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_api6") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_api6", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
