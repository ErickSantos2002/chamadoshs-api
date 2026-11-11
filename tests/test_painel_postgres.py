"""
A conta do painel (API-11, S1) em PostgreSQL real.

As classes que passam pelo banco, importadas de `test_painel_lembretes.py` e
`test_painel_isolamento.py` e rodadas com um `sessao` diferente: um
PostgreSQL descartável criado pelo `schema_chamados.sql`. Aqui o
`conta_de_servico` é o NOT NULL de verdade, o `ativo` e o id vêm do banco de
produção em forma, e cada leitura sem escrita é conferida contra os triggers.

A leitura de `PAINEL_CONTAS_IDS` e o contrato do OpenAPI não tocam o banco e
ficam só no SQLite.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from leitura_cenario import cenario_de_leitura  # noqa: F401
from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_conta_de_servico_administradora import cenario  # noqa: F401
from test_conta_de_servico_escritas import webhooks  # noqa: F401
from test_conta_de_servico_rotas import como, configurar, saidas, servicos  # noqa: F401
from test_lembretes_do_dia import tarefas  # noqa: F401
from test_painel_isolamento import TestListadaNaoGanhaNadaAlemDoLembrete, listada, painel_listado  # noqa: F401
from test_painel_lembretes import TestDiagnostico, TestMatriz, TestQuemLe, TestResposta, contas  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_painel") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_painel", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
