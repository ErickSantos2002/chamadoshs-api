"""
Abertura de chamado para a Qualidade.

O formulário da Qualidade tem descrição, prioridade e responsável — sem título
e sem categoria. A API completa o que falta: o título sai da descrição, a
categoria fica nula, e o responsável escolhido é validado contra a regra de
elegibilidade (ver `test_atendentes_qualidade.py`).

A TI não muda em nada, e isso é o que mais se testa aqui: o corpo de TI passa
pela mesma classe `ChamadoCreate` de antes, e os erros de validação dela são
conferidos campo a campo contra o que a API devolvia antes desta entrega.

Título e categoria ENVIADOS para a Qualidade são recusados, mesmo nulos. É a
presença do campo que conta, não o valor: o formulário da Qualidade não tem
esses campos, então recebê-los indica um cliente montando o corpo errado — e
aceitar em silêncio esconderia o defeito.
"""

import pytest

import main
from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado
from app.models.historico import HistoricoChamado
from app.services.chamado_service import derivar_titulo

DESCRICAO_OK = "Não dá sinal de vida desde ontem à tarde"
TITULO_OK = "Impressora do RH não liga"


def _comum(autenticar, dados):
    return autenticar(dados["comum_id"], "usuario.teste", "Usuario")


def _tecnico(autenticar, dados):
    return autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico")


def _admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


def corpo_qualidade(dados, **sobrescreve):
    """Corpo do formulário da Qualidade: sem título e sem categoria."""
    base = {
        "setor_destino": "QUALIDADE",
        "descricao": DESCRICAO_OK,
        "solicitante_id": dados["comum_id"],
        "tecnico_responsavel_id": dados["atendente_id"],
    }
    base.update(sobrescreve)
    return base


def corpo_ti(dados, **sobrescreve):
    """Corpo idêntico ao que o frontend atual manda."""
    base = {
        "titulo": TITULO_OK,
        "descricao": DESCRICAO_OK,
        "categoria_id": 1,
        "solicitante_id": dados["comum_id"],
    }
    base.update(sobrescreve)
    return base


@pytest.fixture
def webhook(monkeypatch):
    """Registra as chamadas ao webhook da TI em vez de enviá-las."""
    chamadas = []
    monkeypatch.setattr(
        chamados_endpoint, "enviar_webhook_tecnico", lambda **kwargs: chamadas.append(kwargs)
    )
    return chamadas


def _sem_url(detail):
    """
    Erros de validação sem o campo `url`, que aponta para a documentação da
    versão instalada do Pydantic e mudaria numa atualização dele sem que o
    contrato mudasse.
    """
    return [{k: v for k, v in erro.items() if k != "url"} for erro in detail]


class TestTituloDerivado:
    def test_primeira_linha_util_vira_titulo(self):
        assert derivar_titulo("Balança da linha 3 descalibrada\nDetalhes: ...") == (
            "Balança da linha 3 descalibrada"
        )

    def test_crlf_e_linhas_em_branco_no_inicio(self):
        assert derivar_titulo("\r\n\r\nLaudo do lote 42 sem assinatura\r\nResto") == (
            "Laudo do lote 42 sem assinatura"
        )

    def test_espacos_e_tabs_repetidos_viram_um_espaco(self):
        assert derivar_titulo("Laudo \t do   lote\t\t42 pendente\nResto") == (
            "Laudo do lote 42 pendente"
        )

    def test_primeira_linha_curta_usa_o_comeco_da_descricao_inteira(self):
        assert derivar_titulo("Oi\nO laudo do lote 42 está sem assinatura") == (
            "Oi O laudo do lote 42 está sem assinatura"
        )

    def test_primeira_linha_com_exatamente_10_caracteres_e_usada_sozinha(self):
        assert derivar_titulo("0123456789\nsegunda linha") == "0123456789"

    def test_exatamente_80_caracteres_nao_e_cortado(self):
        linha = "a" * 80
        assert derivar_titulo(linha + "\nresto") == linha

    def test_mais_de_80_e_cortado_com_reticencias_dentro_do_limite(self):
        titulo = derivar_titulo("b" * 81)
        assert len(titulo) == 80
        assert titulo == "b" * 79 + "…"

    def test_corte_nao_deixa_espaco_antes_das_reticencias(self):
        titulo = derivar_titulo("x" * 78 + " palavra que passa do limite")
        assert titulo == "x" * 78 + "…"
        assert len(titulo) <= 80

    def test_unicode_conta_caractere_e_nao_byte(self):
        titulo = derivar_titulo("ç" * 100)
        assert titulo == "ç" * 79 + "…"

    def test_primeira_linha_curta_e_descricao_longa_tambem_respeita_o_limite(self):
        titulo = derivar_titulo("Oi\n" + "palavra " * 30)
        assert titulo.startswith("Oi palavra")
        assert len(titulo) == 80
        assert titulo.endswith("…")

    def test_nunca_vazio(self):
        assert derivar_titulo("   texto   ") == "texto"


class TestTIExatamenteComoAntes:
    """
    Os valores esperados abaixo são os que a API devolvia antes desta entrega
    (`main` em f0e045a), copiados da resposta real. Se um deles mudar, o
    frontend em produção passa a receber outro erro.
    """

    def test_titulo_ausente(self, cliente, dados, autenticar):
        corpo = corpo_ti(dados)
        del corpo["titulo"]

        resposta = cliente.post("/api/v1/chamados/", json=corpo, headers=_comum(autenticar, dados))

        assert resposta.status_code == 422
        assert _sem_url(resposta.json()["detail"]) == [
            {"type": "missing", "loc": ["body", "titulo"], "msg": "Field required", "input": corpo}
        ]

    def test_titulo_nulo(self, cliente, dados, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/", json=corpo_ti(dados, titulo=None), headers=_comum(autenticar, dados)
        )

        assert resposta.status_code == 422
        assert _sem_url(resposta.json()["detail"]) == [
            {
                "type": "string_type",
                "loc": ["body", "titulo"],
                "msg": "Input should be a valid string",
                "input": None,
            }
        ]

    def test_titulo_curto(self, cliente, dados, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/", json=corpo_ti(dados, titulo="curto"), headers=_comum(autenticar, dados)
        )

        assert resposta.status_code == 422
        assert _sem_url(resposta.json()["detail"]) == [
            {
                "type": "string_too_short",
                "loc": ["body", "titulo"],
                "msg": "String should have at least 10 characters",
                "input": "curto",
                "ctx": {"min_length": 10},
            }
        ]

    def test_descricao_curta(self, cliente, dados, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/", json=corpo_ti(dados, descricao="curta"), headers=_comum(autenticar, dados)
        )

        assert resposta.status_code == 422
        assert _sem_url(resposta.json()["detail"]) == [
            {
                "type": "string_too_short",
                "loc": ["body", "descricao"],
                "msg": "String should have at least 20 characters",
                "input": "curta",
                "ctx": {"min_length": 20},
            }
        ]

    def test_corpo_que_nao_e_objeto(self, cliente, dados, autenticar):
        resposta = cliente.post("/api/v1/chamados/", json=[], headers=_comum(autenticar, dados))

        assert resposta.status_code == 422
        assert _sem_url(resposta.json()["detail"]) == [
            {
                "type": "model_attributes_type",
                "loc": ["body"],
                "msg": "Input should be a valid dictionary or object to extract fields from",
                "input": [],
            }
        ]

    def test_sem_corpo(self, cliente, dados, autenticar):
        resposta = cliente.post("/api/v1/chamados/", headers=_comum(autenticar, dados))

        assert resposta.status_code == 422
        assert _sem_url(resposta.json()["detail"]) == [
            {"type": "missing", "loc": ["body"], "msg": "Field required", "input": None}
        ]

    def test_criacao_valida_continua_igual(self, cliente, dados, sessao, autenticar, webhook):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo_ti(dados, prioridade="Alta", tecnico_responsavel_id=dados["tecnico_id"]),
            headers=_tecnico(autenticar, dados),
        )

        assert resposta.status_code == 201
        criado = resposta.json()
        assert criado["setor_destino"] == "TI"
        assert criado["titulo"] == TITULO_OK
        assert criado["categoria_id"] == 1
        assert criado["prioridade"] == "Alta"
        # Ignorado na criação de TI, como sempre foi.
        assert criado["tecnico_responsavel_id"] is None
        # Técnico não escolhe solicitante: vale o dono do token.
        assert criado["solicitante_id"] == dados["tecnico_id"]
        assert webhook == [
            {
                "db": webhook[0]["db"],
                "protocolo": criado["protocolo"],
                "titulo": TITULO_OK,
                "tecnico_id": None,
                "acao": "criado",
            }
        ]

    def test_historico_de_ti_registra_o_setor(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/", json=corpo_ti(dados), headers=_comum(autenticar, dados)
        )

        historico = sessao.query(HistoricoChamado).filter_by(chamado_id=resposta.json()["id"]).one()
        assert historico.acao == "Abertura de chamado"
        assert historico.status_novo == "Aberto"
        assert historico.usuario_id == dados["comum_id"]
        assert historico.descricao == (
            f"Chamado aberto com protocolo {resposta.json()['protocolo']} | Setor de destino: TI"
        )

    def test_ti_continua_abrindo_sem_a_qualidade_configurada(
        self, cliente, dados, autenticar, monkeypatch
    ):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)

        resposta = cliente.post(
            "/api/v1/chamados/", json=corpo_ti(dados), headers=_comum(autenticar, dados)
        )

        assert resposta.status_code == 201


class TestCriacaoDaQualidade:
    def test_abertura_valida(self, cliente, qualidade, sessao, autenticar, webhook):
        descricao = "Balança da linha 3 descalibrada\nLeitura 2% acima no peso padrão."

        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo_qualidade(qualidade, descricao=descricao, prioridade="Alta"),
            headers=_comum(autenticar, qualidade),
        )

        assert resposta.status_code == 201
        criado = resposta.json()
        assert criado["setor_destino"] == "QUALIDADE"
        assert criado["titulo"] == "Balança da linha 3 descalibrada"
        assert criado["descricao"] == descricao
        assert criado["categoria_id"] is None
        assert criado["prioridade"] == "Alta"
        assert criado["tecnico_responsavel_id"] == qualidade["atendente_id"]
        assert criado["solicitante_id"] == qualidade["comum_id"]
        assert criado["status"] == "Aberto"

        gravado = sessao.get(Chamado, criado["id"])
        sessao.refresh(gravado)
        assert gravado.setor_destino == "QUALIDADE"
        assert gravado.tecnico_responsavel_id == qualidade["atendente_id"]
        assert gravado.categoria_id is None

    def test_prioridade_padrao_e_a_de_hoje(self, cliente, qualidade, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/", json=corpo_qualidade(qualidade), headers=_comum(autenticar, qualidade)
        )

        assert resposta.json()["prioridade"] == "Média"

    def test_nao_dispara_o_webhook_da_ti(self, cliente, qualidade, autenticar, webhook):
        resposta = cliente.post(
            "/api/v1/chamados/", json=corpo_qualidade(qualidade), headers=_comum(autenticar, qualidade)
        )

        assert resposta.status_code == 201
        assert webhook == []

    def test_historico_registra_setor_e_responsavel(self, cliente, qualidade, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/", json=corpo_qualidade(qualidade), headers=_comum(autenticar, qualidade)
        )

        historico = sessao.query(HistoricoChamado).filter_by(chamado_id=resposta.json()["id"]).one()
        assert historico.acao == "Abertura de chamado"
        assert historico.status_novo == "Aberto"
        assert historico.usuario_id == qualidade["comum_id"]
        assert historico.descricao == (
            f"Chamado aberto com protocolo {resposta.json()['protocolo']}"
            " | Setor de destino: Qualidade | Responsável: ana.qualidade"
        )

    @pytest.mark.parametrize(
        "chave", ["atendente_id", "tecnico_da_qualidade_id", "admin_da_qualidade_id"]
    )
    def test_responsavel_com_qualquer_perfil(self, cliente, qualidade, autenticar, chave):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo_qualidade(qualidade, tecnico_responsavel_id=qualidade[chave]),
            headers=_comum(autenticar, qualidade),
        )

        assert resposta.status_code == 201
        assert resposta.json()["tecnico_responsavel_id"] == qualidade[chave]


class TestSolicitanteSegueARegraAtual:
    def test_usuario_comum_abre_para_si_mesmo(self, cliente, qualidade, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo_qualidade(qualidade, solicitante_id=qualidade["tecnico_id"]),
            headers=_comum(autenticar, qualidade),
        )

        assert resposta.json()["solicitante_id"] == qualidade["comum_id"]

    def test_tecnico_abre_para_si_mesmo(self, cliente, qualidade, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo_qualidade(qualidade, solicitante_id=qualidade["comum_id"]),
            headers=_tecnico(autenticar, qualidade),
        )

        assert resposta.json()["solicitante_id"] == qualidade["tecnico_id"]

    def test_administrador_escolhe_o_solicitante(self, cliente, qualidade, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo_qualidade(qualidade, solicitante_id=qualidade["comum_id"]),
            headers=_admin(autenticar, qualidade),
        )

        assert resposta.status_code == 201
        assert resposta.json()["solicitante_id"] == qualidade["comum_id"]
        historico = sessao.query(HistoricoChamado).filter_by(chamado_id=resposta.json()["id"]).one()
        assert historico.usuario_id == qualidade["comum_id"]


class TestRecusasNaoGravamNada:
    """Toda recusa acontece antes do INSERT: nenhum chamado e nenhum histórico."""

    @pytest.fixture
    def nada_gravado(self, sessao):
        antes = (sessao.query(Chamado).count(), sessao.query(HistoricoChamado).count())

        def _conferir():
            assert (sessao.query(Chamado).count(), sessao.query(HistoricoChamado).count()) == antes

        return _conferir

    def _post(self, cliente, autenticar, qualidade, corpo):
        return cliente.post("/api/v1/chamados/", json=corpo, headers=_comum(autenticar, qualidade))

    def _campos_com_erro(self, resposta):
        return {(tuple(e["loc"]), e["type"]) for e in resposta.json()["detail"]}

    def test_sem_responsavel_e_422(self, cliente, qualidade, autenticar, nada_gravado, webhook):
        corpo = corpo_qualidade(qualidade)
        del corpo["tecnico_responsavel_id"]

        resposta = self._post(cliente, autenticar, qualidade, corpo)

        assert resposta.status_code == 422
        assert (("body", "tecnico_responsavel_id"), "missing") in self._campos_com_erro(resposta)
        nada_gravado()
        assert webhook == []

    def test_responsavel_nulo_e_422(self, cliente, qualidade, autenticar, nada_gravado):
        resposta = self._post(
            cliente, autenticar, qualidade, corpo_qualidade(qualidade, tecnico_responsavel_id=None)
        )

        assert resposta.status_code == 422
        assert any(loc == ("body", "tecnico_responsavel_id") for loc, _ in self._campos_com_erro(resposta))
        nada_gravado()

    @pytest.mark.parametrize("descricao", [None, "", "   ", "curta demais"])
    def test_descricao_invalida_e_422(self, cliente, qualidade, autenticar, nada_gravado, descricao):
        resposta = self._post(cliente, autenticar, qualidade, corpo_qualidade(qualidade, descricao=descricao))

        assert resposta.status_code == 422
        assert any(loc == ("body", "descricao") for loc, _ in self._campos_com_erro(resposta))
        nada_gravado()

    def test_sem_descricao_e_422(self, cliente, qualidade, autenticar, nada_gravado):
        corpo = corpo_qualidade(qualidade)
        del corpo["descricao"]

        resposta = self._post(cliente, autenticar, qualidade, corpo)

        assert (("body", "descricao"), "missing") in self._campos_com_erro(resposta)
        nada_gravado()

    @pytest.mark.parametrize("prioridade", ["Urgentíssima", "media", ""])
    def test_prioridade_invalida_e_422(self, cliente, qualidade, autenticar, nada_gravado, prioridade):
        resposta = self._post(
            cliente, autenticar, qualidade, corpo_qualidade(qualidade, prioridade=prioridade)
        )

        assert (("body", "prioridade"), "enum") in self._campos_com_erro(resposta)
        nada_gravado()

    @pytest.mark.parametrize(
        "campo,valor",
        [
            ("titulo", "Título que o formulário da Qualidade não tem"),
            ("titulo", None),
            ("categoria_id", 1),
            ("categoria_id", None),
        ],
    )
    def test_titulo_ou_categoria_enviados_sao_422(
        self, cliente, qualidade, autenticar, nada_gravado, campo, valor
    ):
        resposta = self._post(cliente, autenticar, qualidade, corpo_qualidade(qualidade, **{campo: valor}))

        assert resposta.status_code == 422
        erro = next(e for e in resposta.json()["detail"] if e["loc"] == ["body", campo])
        assert erro["type"] == "nao_se_aplica"
        assert erro["input"] == valor
        nada_gravado()

    def test_responsavel_inexistente_e_400(self, cliente, qualidade, autenticar, nada_gravado, webhook):
        resposta = self._post(
            cliente, autenticar, qualidade, corpo_qualidade(qualidade, tecnico_responsavel_id=9999)
        )

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Atendente não encontrado"
        nada_gravado()
        assert webhook == []

    @pytest.mark.parametrize(
        "chave", ["inativo_id", "conta_de_servico_id", "sem_setor_id", "tecnico_id", "comum_id"]
    )
    def test_responsavel_inelegivel_e_400(self, cliente, qualidade, autenticar, nada_gravado, chave):
        resposta = self._post(
            cliente, autenticar, qualidade, corpo_qualidade(qualidade, tecnico_responsavel_id=qualidade[chave])
        )

        assert resposta.status_code == 400
        assert resposta.json()["detail"] == "Atendente não é elegível para a Qualidade"
        nada_gravado()

    @pytest.mark.parametrize("configuracao", [None, 999, "inativo"])
    def test_qualidade_nao_configurada_e_503(
        self, cliente, qualidade, autenticar, nada_gravado, monkeypatch, configuracao
    ):
        valor = qualidade["setor_inativo_id"] if configuracao == "inativo" else configuracao
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", valor)

        resposta = self._post(cliente, autenticar, qualidade, corpo_qualidade(qualidade))

        assert resposta.status_code == 503
        assert resposta.json()["detail"] == (
            "Abertura de chamados para a Qualidade não está disponível neste ambiente"
        )
        nada_gravado()

    def test_sem_token_e_401(self, cliente, qualidade, nada_gravado):
        assert cliente.post("/api/v1/chamados/", json=corpo_qualidade(qualidade)).status_code == 401
        nada_gravado()


class TestNadaMaisMuda:
    def test_usuario_comum_continua_sem_put_no_chamado_da_qualidade(
        self, cliente, qualidade, autenticar
    ):
        """Atender chamado da Qualidade é a etapa seguinte; aqui o PUT segue só da equipe."""
        criado = cliente.post(
            "/api/v1/chamados/", json=corpo_qualidade(qualidade), headers=_comum(autenticar, qualidade)
        ).json()

        resposta = cliente.put(
            f"/api/v1/chamados/{criado['id']}",
            json={"status": "Em Andamento"},
            headers=autenticar(qualidade["atendente_id"], "ana.qualidade", "Usuario"),
        )

        assert resposta.status_code == 403

    def test_documentacao_do_corpo_de_criacao_resolve(self, cliente):
        """
        O corpo de criação é validado à mão (ver `criar_chamado`), então o
        schema dele no OpenAPI é declarado à mão também. Toda referência
        precisa existir em `components`, senão o /docs quebra em silêncio.
        """
        openapi = cliente.get("/openapi.json").json()
        corpo = openapi["paths"]["/api/v1/chamados/"]["post"]["requestBody"]
        alternativas = corpo["content"]["application/json"]["schema"]["oneOf"]

        assert {a["title"] for a in alternativas} == {"ChamadoCreate", "ChamadoCreateQualidade"}

        def referencias(no):
            if isinstance(no, dict):
                for chave, valor in no.items():
                    if chave == "$ref":
                        yield valor
                    else:
                        yield from referencias(valor)
            elif isinstance(no, list):
                for item in no:
                    yield from referencias(item)

        componentes = openapi["components"]["schemas"]
        for ref in referencias(alternativas):
            assert ref.startswith("#/components/schemas/")
            assert ref.rsplit("/", 1)[-1] in componentes


class TestDocumentacaoBateComAValidacao:
    """
    O schema do corpo no OpenAPI tem de dizer o que a validação faz. Cada
    corpo vale por uma alternativa do `oneOf`, e só uma: com as duas
    aceitando o mesmo corpo, quem gera cliente ou valida pelo /docs fica sem
    saber qual regra vale.
    """

    @pytest.fixture
    def alternativas(self, cliente):
        openapi = cliente.get("/openapi.json").json()
        corpo = openapi["paths"]["/api/v1/chamados/"]["post"]["requestBody"]
        return {a["title"]: a for a in corpo["content"]["application/json"]["schema"]["oneOf"]}

    def test_ti_documenta_so_o_setor_ti(self, alternativas):
        setor = alternativas["ChamadoCreate"]["properties"]["setor_destino"]

        assert setor["enum"] == ["TI"]
        assert setor["default"] == "TI"
        assert "allOf" not in setor and "$ref" not in setor
        # Omitir continua sendo o jeito de pedir TI.
        assert "setor_destino" not in alternativas["ChamadoCreate"]["required"]

    @pytest.mark.parametrize("campo", ["titulo", "categoria_id"])
    def test_qualidade_documenta_titulo_e_categoria_como_proibidos(self, alternativas, campo):
        qualidade = alternativas["ChamadoCreateQualidade"]
        propriedade = qualidade["properties"][campo]

        # `not: {}` recusa qualquer valor, null incluído — como o 422 real.
        assert propriedade["not"] == {}
        assert set(propriedade) <= {"not", "description", "title"}
        assert campo not in qualidade["required"]

    def test_as_alternativas_nao_se_sobrepoem(self, alternativas):
        ti = alternativas["ChamadoCreate"]
        qualidade = alternativas["ChamadoCreateQualidade"]

        assert "setor_destino" in qualidade["required"]
        assert qualidade["properties"]["setor_destino"]["const"] == "QUALIDADE"
        assert "QUALIDADE" not in ti["properties"]["setor_destino"]["enum"]

    def test_validacao_da_ti_nao_estreitou(self, cliente, dados, autenticar):
        """
        O schema documenta só TI, mas o tipo segue sendo o enum inteiro: o
        erro de valor inválido continua listando os dois valores, como antes.
        """
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo_ti(dados, setor_destino="XYZ"),
            headers=_comum(autenticar, dados),
        )

        assert resposta.status_code == 422
        erro = next(e for e in resposta.json()["detail"] if e["loc"] == ["body", "setor_destino"])
        assert erro["type"] == "enum"
        assert erro["ctx"] == {"expected": "'TI' or 'QUALIDADE'"}
