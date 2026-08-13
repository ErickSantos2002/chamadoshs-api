"""
Testes do `GET /api/v1/health`.

A faixa de status do frontend só entra se disser a verdade, e "a verdade" aqui
tem duas metades que se testam separadas: o que ele responde quando está tudo
bem, e o que ele responde quando o banco não responde. A segunda é a razão de o
endpoint existir — se ele devolvesse 200 com o banco fora, a faixa mostraria
verde durante o incidente, que é pior do que não ter faixa.

A terceira família é sobre o endpoint ser **público**. Ele é o único `/api/v1`
sem token, então cada campo do corpo é legível por qualquer pessoa na internet.
`TestNaoServeParaReconhecimento` trava o contrato pelo que ele NÃO pode conter:
esse é o teste que impede alguém de, no futuro, "melhorar o diagnóstico"
acrescentando versão, host ou contagem — a mudança pareceria útil e passaria
despercebida sem uma asserção que a recuse.
"""

from datetime import datetime

import pytest
from sqlalchemy.exc import OperationalError

import main
from app.api.deps import get_db

CAMINHO = "/api/v1/health"


@pytest.fixture
def banco_fora(sessao):
    """
    Substitui a sessão por uma que estoura como o driver estouraria.

    `OperationalError` é a classe que o psycopg2 levanta quando o banco não
    aceita conexão, e a mensagem imita a dele: traz host, porta, usuário e nome
    do banco. Isso não é enfeite — é o que
    `test_a_mensagem_do_driver_nao_vaza_no_corpo` precisa procurar na resposta.
    """
    class SessaoQuebrada:
        def execute(self, *args, **kwargs):
            raise OperationalError(
                "SELECT 1",
                {},
                Exception(
                    'connection to server at "db.interno.local" (10.0.0.7), '
                    'port 5432 failed: FATAL: password authentication failed '
                    'for user "chamados_prod"'
                ),
            )

    def _get_db_quebrado():
        yield SessaoQuebrada()

    main.app.dependency_overrides[get_db] = _get_db_quebrado
    yield
    main.app.dependency_overrides[get_db] = lambda: (yield sessao)


class TestSaudavel:
    def test_responde_200_com_o_contrato(self, cliente):
        resposta = cliente.get(CAMINHO)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["status"] == "ok"
        assert corpo["banco"] == "ok"

    def test_a_hora_tem_fuso(self, cliente):
        """
        Sem fuso, quem lê precisa adivinhar entre UTC e Brasília — o container
        roda em UTC e o sistema opera em Brasília, então o erro é de três horas
        e passa despercebido.
        """
        hora = cliente.get(CAMINHO).json()["hora"]

        # fromisoformat aceita o formato; tzinfo preenchido prova o deslocamento.
        assert datetime.fromisoformat(hora).tzinfo is not None

    def test_nao_exige_autenticacao(self, cliente):
        """
        A faixa de status aparece antes do login, e monitor externo não tem
        credencial. Este é o único `/api/v1` assim, e `main.ROTAS_PUBLICAS`
        registra a exceção.
        """
        assert "Authorization" not in cliente.headers
        assert cliente.get(CAMINHO).status_code == 200

    def test_o_caminho_exato_responde_sem_redirecionar(self, cliente):
        """
        Sem barra final e sem 307. Alguns monitores tratam 3xx como falha, e um
        redirect num endpoint chamado a cada 60s é ruído permanente.
        """
        resposta = cliente.get(CAMINHO, follow_redirects=False)

        assert resposta.status_code == 200


class TestBancoFora:
    """
    A metade que dá sentido ao endpoint: distinguir "API caiu" de "API no ar,
    banco fora". Sem isto, a faixa mostraria verde durante o incidente.
    """

    def test_responde_503(self, cliente, banco_fora):
        resposta = cliente.get(CAMINHO)

        assert resposta.status_code == 503

    def test_o_corpo_diz_qual_metade_falhou(self, cliente, banco_fora):
        corpo = cliente.get(CAMINHO).json()

        assert corpo["status"] == "degradado"
        assert corpo["banco"] == "erro"

    def test_e_503_exato_e_nao_um_5xx_qualquer(self, cliente, banco_fora):
        """
        **Este é o teste que protege o contrato com o frontend.**

        A faixa de status lê o CÓDIGO, nunca o corpo, e o traduz assim:

            200          -> "sistema ativo"
            503          -> "banco fora"
            outro / erro -> "sem resposta"

        A terceira linha é a que torna `>= 500` insuficiente, que era a
        asserção daqui: um 500 no lugar do 503 continuaria passando e mudaria
        em silêncio o que a tela diz — "banco fora" viraria "sem resposta". E o
        front está certo em fazer assim, porque num 500 ou 502 quem respondeu
        pode nem ter sido a API, e afirmar "o banco caiu" a partir de um 502 do
        proxy seria inventar diagnóstico.

        Consequência para quem mexer aqui: **mudar este código de status é
        mudar a interface**, e exige avisar quem cuida do frontend. O contrato
        do corpo, travado em `TestNaoServeParaReconhecimento`, é uma trava de
        segurança; esta é a de compatibilidade.
        """
        resposta = cliente.get(CAMINHO)

        assert resposta.status_code == 503, (
            f"o frontend traduz 503 como 'banco fora' e qualquer outro 5xx como "
            f"'sem resposta'; este endpoint respondeu {resposta.status_code}"
        )

    def test_saudavel_e_200_exato(self, cliente):
        """
        A outra ponta do mesmo contrato: só 200 vira "sistema ativo". Um 204 ou
        um 302 aqui apagariam a faixa sem que nada falhasse do lado da API.
        """
        assert cliente.get(CAMINHO).status_code == 200

    def test_a_mensagem_do_driver_nao_vaza_no_corpo(self, cliente, banco_fora):
        """
        O `OperationalError` do psycopg2 traz host, porta, usuário e nome do
        banco no texto. Repassar isso num endpoint público entrega a topologia
        interna a quem só precisou de um GET.
        """
        corpo = cliente.get(CAMINHO).text

        for vazamento in ("db.interno.local", "10.0.0.7", "5432", "chamados_prod", "FATAL"):
            assert vazamento not in corpo


class TestNaoServeParaReconhecimento:
    """
    O endpoint é público. Cada campo do corpo é legível por qualquer pessoa na
    internet, então o contrato é fechado: três chaves e nada além.
    """

    def test_o_corpo_tem_exatamente_tres_campos(self, cliente):
        assert set(cliente.get(CAMINHO).json()) == {"status", "banco", "hora"}

    def test_nao_devolve_nada_do_ambiente(self, cliente):
        """
        A lista do que não pode aparecer, por nome: versão da API, identidade do
        banco, hostname, contagem de registros, variável de ambiente. Uma
        "melhoria de diagnóstico" que acrescentasse qualquer um deles pareceria
        útil e passaria sem esta asserção.
        """
        corpo = cliente.get(CAMINHO).text.lower()

        for proibido in (
            "version", "versao", "versão",
            "postgres", "database", "database_url", "host", "port",
            "secret", "environment", "ambiente",
            "usuarios", "total", "count",
        ):
            assert proibido not in corpo

    def test_o_relatorio_administrativo_continua_restrito(self, cliente):
        """
        A saúde pública não abriu porta para o `diagnostico.py`, que conta
        usuários e lê `information_schema` — ele segue exigindo administrador.
        Os dois existem separados justamente por isso.
        """
        assert cliente.get("/api/v1/diagnostico/").status_code == 401


class TestATravaDeRotasProtegidas:
    """
    `main.py` derruba a aplicação na inicialização se uma rota `/api/v1` não
    exigir token. Abrir esta exigiu registrar a exceção à mão — e é bom que
    tenha exigido.
    """

    def test_a_excecao_esta_registrada_e_e_so_esta(self):
        assert ("GET", "/api/v1/health") in main.ROTAS_PUBLICAS
        # Login e saúde. Uma terceira entrada aqui é uma decisão de segurança
        # que precisa ser deliberada, não herdada.
        assert main.ROTAS_PUBLICAS == {
            ("POST", "/api/v1/auth/login"),
            ("GET", "/api/v1/health"),
        }

    def test_nenhuma_outra_rota_ficou_aberta(self):
        assert main._rotas_desprotegidas() == []
