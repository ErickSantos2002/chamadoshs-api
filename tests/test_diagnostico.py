"""
Testes do relatório administrativo (`GET /api/v1/diagnostico/`).

Dois assuntos, e nenhum deles é o conteúdo do relatório em si — o valor dele é
justamente mudar conforme o estado do banco.

O primeiro é o acesso: ele conta usuários, lê `information_schema` e devolve
amostra de contas. É a informação que um relatório de investigação precisa ter
e que ninguém além de administrador precisa ver.

O segundo é o vazamento de mensagem de exceção, que é o motivo destes testes
existirem. Até 13/08/2026 os três blocos `try` devolviam `str(e)` dentro do
JSON, e o texto de um `OperationalError` do psycopg2 traz host, porta, usuário e
nome do banco. Ser restrito a administrador ameniza, mas não resolve: a resposta
ainda viaja por HTTP e para em log de proxy, histórico de navegador e print
colado em conversa.

O formato do relatório (chaves, emojis) foi preservado de propósito na correção:
é ferramenta que alguém pode estar consumindo, e o defeito era o conteúdo de um
campo, não a forma.
"""

import pytest
from sqlalchemy.exc import OperationalError

import main
from app.api.deps import get_db, require_admin

CAMINHO = "/api/v1/diagnostico/"

# Imita o texto real do psycopg2 quando o banco recusa conexão: é dele que os
# fragmentos procurados abaixo saem.
ERRO_DO_DRIVER = (
    'connection to server at "db.interno.local" (10.0.0.7), port 5432 failed: '
    'FATAL: password authentication failed for user "chamados_prod"'
)

VAZAMENTOS = ("db.interno.local", "10.0.0.7", "chamados_prod", "FATAL", "password")


@pytest.fixture
def banco_fora(sessao):
    """
    Sessão que estoura como o driver estouraria, em qualquer consulta.

    O `require_admin` do router também é substituído, e não por conveniência:
    ele resolve o usuário do token consultando o banco, então com a sessão
    quebrada a requisição morre na autenticação e nunca chega ao relatório —
    que é o que estes testes precisam exercitar. A restrição de acesso é
    verificada em `TestAcesso`, com o banco funcionando.
    """
    class SessaoQuebrada:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception(ERRO_DO_DRIVER))

        def query(self, *args, **kwargs):
            raise OperationalError("SELECT", {}, Exception(ERRO_DO_DRIVER))

    def _get_db_quebrado():
        yield SessaoQuebrada()

    main.app.dependency_overrides[get_db] = _get_db_quebrado
    # O valor não é usado: a dependency é de router e o handler não a recebe.
    main.app.dependency_overrides[require_admin] = lambda: None
    yield
    main.app.dependency_overrides.pop(require_admin, None)
    main.app.dependency_overrides[get_db] = lambda: (yield sessao)


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


class TestAcesso:
    def test_administrador_recebe_o_relatorio(self, cliente, dados, autenticar):
        """
        O `status` não é verificado aqui, e sim as seções: a suíte roda em
        SQLite, que não tem `information_schema`, então aquele bloco do
        relatório sempre acusa erro neste ambiente. Exigir `status == "ok"`
        seria escrever um teste sobre o banco de teste, não sobre o endpoint.
        """
        resposta = cliente.get(CAMINHO, headers=_como_admin(autenticar, dados))

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["database"]["conexao"] == "✅ OK"
        assert corpo["usuarios"]["total"] == 3
        assert {"id", "nome", "tem_senha", "ativo"} <= set(corpo["usuarios"]["amostra"][0])

    def test_tecnico_nao_passa(self, cliente, dados, autenticar):
        """
        O relatório enumera contas e diz quais estão sem senha — é mapa de
        onde entrar, não informação de operação.
        """
        resposta = cliente.get(
            CAMINHO, headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico")
        )

        assert resposta.status_code == 403

    def test_sem_token_nao_passa(self, cliente, dados):
        assert cliente.get(CAMINHO).status_code == 401

    def test_a_lista_de_contas_sem_senha_tambem_e_restrita(self, cliente, dados, autenticar):
        resposta = cliente.get(
            "/api/v1/diagnostico/usuarios-sem-senha",
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 403


class TestNaoVazaOTextoDoDriver:
    """
    O defeito corrigido em 13/08/2026: `str(e)` dentro do JSON de resposta.

    Cada bloco `try` do relatório tem seu próprio teste porque cada um vazava
    por conta própria — corrigir um e esquecer outro era o modo de falha
    provável.
    """

    def test_o_relatorio_responde_mesmo_com_o_banco_fora(self, cliente, dados, autenticar, banco_fora):
        """
        Antes de checar o que ele NÃO diz: ele precisa dizer alguma coisa. Um
        500 aqui tornaria o resto vacuamente verdadeiro — e um diagnóstico que
        morre quando o sistema quebra é inútil exatamente quando é aberto.
        """
        resposta = cliente.get(CAMINHO, headers=_como_admin(autenticar, dados))

        assert resposta.status_code == 200
        assert resposta.json()["status"] == "erro"

    def test_nenhum_fragmento_do_driver_aparece(self, cliente, dados, autenticar, banco_fora):
        corpo = cliente.get(CAMINHO, headers=_como_admin(autenticar, dados)).text

        for vazamento in VAZAMENTOS:
            assert vazamento not in corpo, (
                f"o relatório voltou a repassar o texto da exceção: {vazamento!r} "
                "apareceu na resposta. O detalhe vai para o log, não para o JSON."
            )

    def test_diz_que_falhou_e_onde_procurar(self, cliente, dados, autenticar, banco_fora):
        """
        A correção não pode ter emudecido o relatório: sem apontar o log, quem
        abre a ferramenta fica sabendo que algo falhou e sem para onde ir.
        """
        corpo = cliente.get(CAMINHO, headers=_como_admin(autenticar, dados)).json()

        assert corpo["database"]["conexao"].startswith("❌")
        assert "log" in corpo["database"]["conexao"].lower()

    def test_os_tres_blocos_falham_sem_vazar(self, cliente, dados, autenticar, banco_fora):
        """
        Conexão, `information_schema` e consulta de usuários vazavam em três
        pontos independentes. Este teste exige que os três tenham reportado
        falha — se algum parar de ser exercitado, a cobertura some sem aviso.
        """
        corpo = cliente.get(CAMINHO, headers=_como_admin(autenticar, dados)).json()

        assert corpo["database"]["conexao"].startswith("❌")
        assert corpo["auth"]["migration_executada"].startswith("❌")
        assert corpo["usuarios"]["erro"].startswith("❌")
