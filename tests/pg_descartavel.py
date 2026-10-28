"""
PostgreSQL local e descartável, para o que o SQLite não prova.

O resto da suíte roda em SQLite em memória (ver `tests/conftest.py`), e é o
certo para ela: sem serviço externo, sem flake de ambiente. Mas trigger,
função plpgsql, `pg_trigger` e o bloco DO de uma migration só existem no
PostgreSQL. Os testes que dependem deles usam este módulo.

Como roda:

    CHAMADOSHS_TESTE_PG_URL=postgresql://postgres@127.0.0.1:54329/postgres pytest

A URL é de um SERVIDOR local onde o usuário pode criar banco. Cada teste
recebe um banco novo, com nome aleatório, apagado no fim — nada é feito no
banco da URL em si além de CREATE e DROP DATABASE.

Sem a variável, os testes marcados `postgres` são pulados (e dizem por quê).
Com uma URL que não seja de localhost, eles FALHAM sem abrir conexão: rodar
isto contra produção apagaria e criaria bancos lá, e um skip esconderia o
engano.
"""

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import pytest

VARIAVEL = "CHAMADOSHS_TESTE_PG_URL"
HOSTS_LOCAIS = {"127.0.0.1", "localhost", "::1"}

RAIZ = Path(__file__).resolve().parent.parent


def url_do_servidor() -> str:
    url = os.environ.get(VARIAVEL)
    if not url:
        pytest.skip(f"{VARIAVEL} não definida: os testes em PostgreSQL real não rodaram.")
    host = urlsplit(url).hostname
    if host not in HOSTS_LOCAIS:
        pytest.fail(
            f"{VARIAVEL} aponta para {host!r}. Estes testes criam e apagam bancos: "
            "só servidor local é aceito."
        )
    return url


@contextmanager
def banco_descartavel(prefixo: str = "teste_versao", modelo: str = None):
    """
    Cria um banco, devolve a URL dele e o apaga no fim, haja o que houver.

    Com `modelo` (a URL de outro banco descartável, sem ninguém conectado), o
    banco nasce como cópia dele — `CREATE DATABASE … TEMPLATE`, bem mais
    rápido que rodar o schema de novo a cada teste.
    """
    import psycopg2

    url = url_do_servidor()
    nome = f"{prefixo}_{uuid.uuid4().hex[:12]}"
    origem = f' TEMPLATE "{urlsplit(modelo).path.lstrip("/")}"' if modelo else ""
    admin = psycopg2.connect(url)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{nome}"{origem}')
        yield urlsplit(url)._replace(path=f"/{nome}").geturl()
    finally:
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{nome}" WITH (FORCE)')
        admin.close()


def executar_script(url: str, sql: str) -> list:
    """
    Roda um script inteiro, como o "Execute script" do DBeaver, e devolve os
    NOTICEs. Conexão própria e descartada: um erro no meio de um BEGIN do
    script não contamina a próxima execução.
    """
    import psycopg2

    conexao = psycopg2.connect(url)
    conexao.autocommit = True
    try:
        with conexao.cursor() as cur:
            cur.execute(sql)
        return list(conexao.notices)
    finally:
        conexao.close()


def ler(relativo: str) -> str:
    return (RAIZ / relativo).read_text(encoding="utf-8")


@contextmanager
def modelo_da_api(prefixo: str):
    """
    Banco-modelo criado só pelo `schema_chamados.sql`, para copiar por
    `banco_descartavel(modelo=...)`. Os cadastros semeados pelo schema saem:
    os fixtures da suíte (`dados`, `qualidade`) gravam os seus, com ids fixos.
    """
    with banco_descartavel(prefixo) as url:
        executar_script(url, ler("schema_chamados.sql"))
        executar_script(url, "TRUNCATE roles, setores, categorias RESTART IDENTITY CASCADE")
        yield url
