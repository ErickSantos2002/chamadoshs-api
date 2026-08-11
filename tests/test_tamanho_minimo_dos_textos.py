"""
Tamanho mínimo dos campos de texto do chamado, na criação.

O frontend passou a exigir, em 11/08/2026: título com 10 caracteres,
descrição com 20. A API aceitava qualquer coisa, então a regra valia só
enquanto a pessoa usasse a tela.

A contagem é sobre o texto sem espaço nas pontas — sem isso, segurar a barra
de espaço satisfaz o mínimo e a validação vira enfeite.

Escopo: **só a criação**. A regra no update depende de quantos chamados
antigos ficariam abaixo desses números, o que exige contar em produção; até
lá, exigir no update travaria a edição de registro legado. `solucao` é campo
exclusivo do update, então também está fora por enquanto.
"""

import pytest

from app.models import Chamado

TITULO_OK = "Impressora do RH não liga"
DESCRICAO_OK = "Não dá sinal de vida desde ontem à tarde"


def corpo(solicitante_id, **sobrescreve):
    """
    Corpo válido de criação, para cada teste estragar só o campo que examina.

    `solicitante_id` é obrigatório em `ChamadoCreate` (o handler ignora o valor
    para quem não é administrador, mas o schema exige que venha). Omiti-lo aqui
    faria os testes negativos passarem por campo faltando em vez de por tamanho
    — 422 pelo motivo errado, que é um teste que não testa nada.
    """
    base = {
        "titulo": TITULO_OK,
        "descricao": DESCRICAO_OK,
        "categoria_id": 1,
        "solicitante_id": solicitante_id,
    }
    base.update(sobrescreve)
    return base


def recusou_por_tamanho(resposta, campo):
    """Confere que o 422 fala do campo esperado, e por tamanho."""
    if resposta.status_code != 422:
        return False
    return any(
        erro["loc"][-1] == campo and erro["type"] == "string_too_short"
        for erro in resposta.json()["detail"]
    )


class TestCriacaoRecusaTextoCurto:
    def test_titulo_com_menos_de_10_e_422(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], titulo="a" * 9),
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert recusou_por_tamanho(resposta, "titulo"), resposta.text
        assert sessao.query(Chamado).count() == 1  # só o do fixture

    def test_descricao_com_menos_de_20_e_422(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], descricao="a" * 19),
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert recusou_por_tamanho(resposta, "descricao"), resposta.text
        assert sessao.query(Chamado).count() == 1

    @pytest.mark.parametrize(
        "campo,texto",
        [
            ("titulo", "   " + "a" * 9 + "   "),
            ("descricao", "   " + "a" * 19 + "   "),
        ],
    )
    def test_espaco_nas_pontas_nao_completa_o_minimo(
        self, cliente, dados, sessao, autenticar, campo, texto
    ):
        """
        O motivo de a regra ser sobre o texto aparado: com o comprimento cru,
        estes valores passariam (15 e 25 caracteres) sem conteúdo que preste.
        """
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], **{campo: texto}),
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert recusou_por_tamanho(resposta, campo), resposta.text
        assert sessao.query(Chamado).count() == 1


class TestCriacaoAceitaOMinimo:
    def test_exatamente_no_limite_passa(self, cliente, dados, sessao, autenticar):
        """A borda é `>=`: 10 e 20 são válidos, não o primeiro valor recusado."""
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], titulo="a" * 10, descricao="b" * 20),
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 201

    def test_texto_e_gravado_sem_espaco_nas_pontas(
        self, cliente, dados, sessao, autenticar
    ):
        """
        Aparar não é só para medir: o valor guardado também vai limpo. Antes,
        o que o formulário mandasse ia para o banco como veio.
        """
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(
                dados["comum_id"],
                titulo=f"  {TITULO_OK}  ",
                descricao=f"\n{DESCRICAO_OK}\t",
            ),
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 201

        criado = sessao.query(Chamado).filter(Chamado.id != dados["chamado_id"]).one()
        assert criado.titulo == TITULO_OK
        assert criado.descricao == DESCRICAO_OK


class TestLegadoContinuaLegivel:
    """
    A armadilha que decidiu onde a validação mora.

    `ChamadoResponse` herda de `ChamadoBase`, e o FastAPI valida a resposta
    contra o response_model. Se o mínimo estivesse em `ChamadoBase` — o lugar
    óbvio, já que é onde `titulo` e `descricao` são declarados —, todo chamado
    antigo com título curto passaria a estourar `ResponseValidationError`: 500
    no GET de registro que hoje abre normalmente.

    A API aceitou texto de qualquer tamanho até 11/08/2026, então esses
    registros existem. Estes testes falham se alguém "arrumar" o schema
    movendo a restrição para a base.
    """

    @pytest.fixture
    def chamado_legado(self, sessao, dados):
        """Criado direto no banco: é assim que o legado entrou, sem validação."""
        legado = Chamado(
            id=101,
            protocolo="CH-LEGADO-101",
            solicitante_id=dados["comum_id"],
            categoria_id=1,
            titulo="pc quebrou",  # 10 — mas a descrição abaixo tem 3
            descricao="nao liga",
            status="Aberto",
            prioridade="Média",
        )
        legado.titulo = "sem net"  # 7, abaixo do mínimo
        sessao.add(legado)
        sessao.commit()
        return legado.id

    def test_get_de_chamado_legado_curto_responde_200(
        self, cliente, dados, autenticar, chamado_legado
    ):
        resposta = cliente.get(
            f"/api/v1/chamados/{chamado_legado}",
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 200
        assert resposta.json()["titulo"] == "sem net"

    def test_listagem_com_chamado_legado_curto_responde_200(
        self, cliente, dados, autenticar, chamado_legado
    ):
        """
        Pior que o GET individual: um único registro curto derrubaria a
        listagem inteira, e com ela a tela inicial de todo mundo.
        """
        resposta = cliente.get(
            "/api/v1/chamados/",
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 200
        assert len(resposta.json()) == 2
