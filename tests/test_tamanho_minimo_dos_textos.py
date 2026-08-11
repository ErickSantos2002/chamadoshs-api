"""
Tamanho mínimo dos campos de texto do chamado, na criação.

O frontend passou a exigir, em 11/08/2026: título com 10 caracteres,
descrição com 20. A API aceitava qualquer coisa, então a regra valia só
enquanto a pessoa usasse a tela.

A contagem é sobre o texto sem espaço nas pontas — sem isso, segurar a barra
de espaço satisfaz o mínimo e a validação vira enfeite.

Vale na criação e na edição. Exigir na edição não trava registro legado
porque o frontend não reenvia valor intocado — `titulo` e `descricao` ele
nunca manda, e `solucao` só vai quando muda. O que garante isso do lado da
API é o `exclude_unset`: campo ausente da requisição não é validado nem
gravado. `TestLegadoContinuaEditavel` é o teste que segura essa promessa.

`solucao` guarda também o motivo do cancelamento — o `PATCH /cancelar` não
tem corpo, então o motivo chega por `PUT {solucao}`, na mesma coluna. O
mínimo vale para os dois.
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


class TestEdicaoRecusaTextoCurto:
    """
    PUT /chamados/{id} — restrito a administrador ou técnico, então os testes
    autenticam como técnico.
    """

    @pytest.mark.parametrize(
        "campo,valor",
        [
            ("titulo", "a" * 9),
            ("descricao", "a" * 19),
            ("solucao", "a" * 9),
            ("titulo", "   " + "a" * 9 + "   "),
            ("solucao", "         "),
        ],
    )
    def test_texto_curto_e_422(self, cliente, dados, sessao, autenticar, campo, valor):
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={campo: valor},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert recusou_por_tamanho(resposta, campo), resposta.text

    def test_motivo_de_cancelamento_curto_e_422(self, cliente, dados, autenticar):
        """
        O motivo do cancelamento é gravado em `solucao` (o PATCH /cancelar não
        tem corpo), então cai no mesmo mínimo. Sem isso, cancelar com "x"
        passaria por uma porta que resolver com "x" não passa.
        """
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"solucao": "x"},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert recusou_por_tamanho(resposta, "solucao"), resposta.text

    def test_solucao_valida_e_gravada_sem_espaco_nas_pontas(
        self, cliente, dados, sessao, autenticar
    ):
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"solucao": "  Troquei a fonte do equipamento  "},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 200
        assert sessao.query(Chamado).one().solucao == "Troquei a fonte do equipamento"


class TestLegadoContinuaEditavel:
    """
    A promessa que sustentou a decisão de exigir o mínimo também no update.

    Um chamado antigo de título curto continua editável, porque o que não vem
    na requisição não é validado. Se algum dia o schema passar a exigir os
    campos em vez de aceitá-los como opcionais, ou se o handler deixar de usar
    `exclude_unset`, estes testes caem — e o sintoma em produção seria a
    equipe não conseguir mexer no status de chamado antigo.
    """

    @pytest.fixture
    def chamado_legado(self, sessao, dados):
        legado = Chamado(
            id=102,
            protocolo="CH-LEGADO-102",
            solicitante_id=dados["comum_id"],
            categoria_id=1,
            titulo="sem net",       # 7, abaixo do mínimo de hoje
            descricao="nao liga",   # 8, idem
            solucao="reiniciei",    # 9, idem
            status="Aberto",
            prioridade="Média",
        )
        sessao.add(legado)
        sessao.commit()
        return legado.id

    def test_mudar_so_o_status_funciona(
        self, cliente, dados, sessao, autenticar, chamado_legado
    ):
        resposta = cliente.put(
            f"/api/v1/chamados/{chamado_legado}",
            json={"status": "Em Andamento"},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 200, resposta.text
        assert sessao.query(Chamado).filter(Chamado.id == chamado_legado).one().status == "Em Andamento"

    def test_atribuir_tecnico_funciona(
        self, cliente, dados, autenticar, chamado_legado
    ):
        resposta = cliente.put(
            f"/api/v1/chamados/{chamado_legado}",
            json={"tecnico_responsavel_id": dados["tecnico_id"]},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 200, resposta.text

    def test_reenviar_o_titulo_legado_intocado_e_que_seria_recusado(
        self, cliente, dados, autenticar, chamado_legado
    ):
        """
        O outro lado da promessa, registrado de propósito.

        Se o frontend voltar a mandar o objeto inteiro no PUT, este 422 é o
        que a equipe veria ao editar chamado antigo. O teste existe para que a
        causa esteja escrita quando isso acontecer, em vez de virar
        investigação.
        """
        resposta = cliente.put(
            f"/api/v1/chamados/{chamado_legado}",
            json={"status": "Em Andamento", "titulo": "sem net"},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert recusou_por_tamanho(resposta, "titulo"), resposta.text


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
