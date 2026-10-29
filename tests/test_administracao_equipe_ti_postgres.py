"""
As regras da API-7 em PostgreSQL real.

Os testes da dependência, da matriz administrativa e do `/auth/me`,
importados para cá e rodados com um `sessao` diferente: um PostgreSQL
descartável criado pelo `schema_chamados.sql`. O SQLite já prova a regra;
aqui o que se prova é ela com o banco de produção — as chaves estrangeiras
de verdade na exclusão de setor e de categoria, o `ON DELETE CASCADE` das
execuções de rotina, e a recusa sem escrita conferida contra ele.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from leitura_cenario import cenario_de_leitura  # noqa: F401
from pg_descartavel import banco_descartavel, modelo_da_api

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_administracao_equipe_ti import (  # noqa: F401
    TestEventos,
    TestRegrasDeSempre,
    TestTarefas,
    administracao,
    como,
    configurar,
    saidas,
    test_leituras_de_cadastro_seguem_abertas,
    test_matriz_com_configuracao_valida,
    test_matriz_por_configuracao,
    test_sem_token_continua_401,
    test_token_invalido_continua_401,
)
from test_me_equipe_ti import (  # noqa: F401
    TestClienteNaoManda,
    test_administrador_fora_da_lista_administra_com_o_campo_false,
    test_campo_e_trava_dizem_o_mesmo,
    test_mudanca_de_configuracao_vale_no_proximo_pedido,
    test_mudanca_de_setor_vale_no_proximo_pedido,
    test_valor_por_perfil_e_configuracao,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def banco_novo():
    with modelo_da_api("modelo_api7") as url:
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel("teste_api7", modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()
