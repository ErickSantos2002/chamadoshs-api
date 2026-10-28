"""
Concorrência real em PostgreSQL, sem sleep como sincronização.

O que este módulo dá aos testes:

- `Pausa`: substitui uma função do endpoint (em geral `conferir_versao`) e faz
  a PRIMEIRA requisição que passar por ela parar ali — depois de executar a
  função de verdade, com a linha já travada pela transação dela — até o teste
  mandar seguir. É o único ponto "falso" da cena: o lock, a transação, o
  UPDATE e o commit são os de produção. A pausa só escolhe o momento.
- `esperar_bloqueio`: espera o PostgreSQL dizer, por `pg_blocking_pids`, que
  alguma sessão está bloqueada por um pid dado. É a prova de que a segunda
  requisição está ESPERANDO o lock, e não só demorando.
- `em_paralelo`: roda uma requisição numa thread e devolve como pegar o
  resultado (ou a exceção) com limite de tempo.
- `sql_emitido`: registra o SQL que um engine manda ao banco, para provar
  pela estrutura — e não pelo relógio — se uma rota pede `FOR UPDATE`.

Todos os limites de espera são `TEMPO_MAXIMO`, bem abaixo do `lock_timeout`
das sessões de teste (`LOCK_TIMEOUT_DOS_TESTES`): uma cena que trave falha
pela espera do teste, com mensagem, e não por erro de lock no meio.
"""

import threading
import time
from contextlib import contextmanager

import psycopg2
from sqlalchemy import event, text
from sqlalchemy.orm import object_session

TEMPO_MAXIMO = 10
LOCK_TIMEOUT_DOS_TESTES = "30s"
# Intervalo de leitura do pg_stat_activity enquanto se espera um bloqueio. Não
# sincroniza nada — quem sincroniza é a condição lida — e só define de quanto
# em quanto tempo se olha.
INTERVALO_DE_OBSERVACAO = 0.02


class Pausa:
    """
    Faz a primeira chamada de `original` parar depois de executada.

    Uso: `monkeypatch.setattr(chamados_endpoint, "conferir_versao", pausa)`;
    dispare a requisição A, `pausa.esperar_parar()`, dispare B, observe,
    `pausa.liberar()`. As chamadas seguintes (a de B) passam direto.

    `pid` é o backend do PostgreSQL da requisição pausada, lido da sessão do
    primeiro argumento que tiver uma (o chamado, ou o `db`).
    """

    def __init__(self, original):
        self.original = original
        self._parou = threading.Event()
        self._seguir = threading.Event()
        self._trava = threading.Lock()
        self._usada = False
        self.pid = None

    def __call__(self, *args, **kwargs):
        resultado = self.original(*args, **kwargs)
        with self._trava:
            primeira = not self._usada
            self._usada = True
        if primeira:
            self.pid = self._sessao(args, kwargs).execute(text("SELECT pg_backend_pid()")).scalar()
            self._parou.set()
            if not self._seguir.wait(TEMPO_MAXIMO):
                raise TimeoutError("a pausa não foi liberada pelo teste")
        return resultado

    @staticmethod
    def _sessao(args, kwargs):
        for valor in (*args, *kwargs.values()):
            if hasattr(valor, "execute"):
                return valor
            sessao = object_session(valor) if hasattr(valor, "_sa_instance_state") else None
            if sessao is not None:
                return sessao
        raise AssertionError("a função pausada não recebeu sessão nem objeto ORM")

    def esperar_parar(self):
        assert self._parou.wait(TEMPO_MAXIMO), "a requisição A não chegou à pausa"

    def liberar(self):
        self._seguir.set()


def em_paralelo(funcao):
    """Roda `funcao` numa thread daemon e devolve `esperar()` -> resultado (ou relança a exceção)."""
    resultado = {}

    def alvo():
        try:
            resultado["valor"] = funcao()
        except BaseException as exc:  # devolvido ao teste, que decide
            resultado["erro"] = exc

    thread = threading.Thread(target=alvo, daemon=True)
    thread.start()

    def esperar():
        thread.join(TEMPO_MAXIMO)
        assert not thread.is_alive(), "a requisição não terminou"
        if "erro" in resultado:
            raise resultado["erro"]
        return resultado["valor"]

    return esperar


def esperar_bloqueio(url, por_pid):
    """
    Espera alguma sessão do banco ficar bloqueada pelo backend `por_pid`.
    Devolve o pid da sessão bloqueada.
    """
    vigia = psycopg2.connect(url)
    vigia.autocommit = True
    try:
        fim = time.monotonic() + TEMPO_MAXIMO
        while time.monotonic() < fim:
            with vigia.cursor() as cur:
                cur.execute(
                    "SELECT pid FROM pg_stat_activity "
                    "WHERE datname = current_database() AND %s = ANY(pg_blocking_pids(pid))",
                    (por_pid,),
                )
                linha = cur.fetchone()
            if linha:
                return linha[0]
            time.sleep(INTERVALO_DE_OBSERVACAO)
        raise AssertionError(f"nenhuma sessão ficou bloqueada pelo pid {por_pid}")
    finally:
        vigia.close()


def pid_de(conexao) -> int:
    with conexao.cursor() as cur:
        cur.execute("SELECT pg_backend_pid()")
        return cur.fetchone()[0]


@contextmanager
def sql_emitido(engine):
    """Registra, em ordem, todo SQL que o engine mandar ao banco dentro do bloco."""
    comandos = []

    def registrar(conn, cursor, statement, parameters, context, executemany):
        comandos.append(statement)

    event.listen(engine, "before_cursor_execute", registrar)
    try:
        yield comandos
    finally:
        event.remove(engine, "before_cursor_execute", registrar)
