"""
A API-11 em PostgreSQL real: S1, S2, S3 e S5.

Os testes do menor privilégio das contas de serviço, importados para cá e
rodados com um `sessao` diferente: um PostgreSQL descartável criado pelo
`schema_chamados.sql`. O SQLite já prova a regra; aqui o que se prova é ela
com o banco de produção — o `conta_de_servico` NOT NULL de verdade, as chaves
estrangeiras, e cada recusa sem escrita conferida contra o trigger que
incrementa a versão do chamado.

A S4 (último administrador humano) tem módulo próprio, com a concorrência:
`test_ultimo_administrador_humano_postgres.py`.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from leitura_cenario import cenario_de_leitura  # noqa: F401
from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_conta_de_servico_administradora import (  # noqa: F401
    TestAdministradorHumano,
    TestNaoAdministra,
    TestOQueContinua as TestAdministradoraOQueContinua,
    cenario,
)
from test_conta_de_servico_escritas import (  # noqa: F401
    TestOQueContinua as TestEscritasOQueContinua,
    TestPessoasNaoMudam,
    TestRecusaSemEfeito,
    webhooks,
)
from test_conta_de_servico_rotas import como, configurar, saidas, servicos  # noqa: F401
from test_lembretes_do_dia import TestContrato, TestNaoAbreOModulo, TestQuemLe, tarefas  # noqa: F401
from test_registro_sem_conta_de_servico import (  # noqa: F401
    test_alterar_senha_continua,
    test_o_registro_legitimo_continua,
    test_post_usuarios_ainda_cria_conta_de_servico,
    test_qualquer_presenca_da_chave_e_422_sem_criar,
    test_sem_token_continua_401,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_api11") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_api11", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
