"""
Setor de destino do chamado (TI | QUALIDADE) — primeira etapa.

O chamado passa a dizer para qual setor ele vai. Esta etapa cria o campo, o
expõe nas respostas e permite filtrar a listagem por ele. A abertura de
chamado para a Qualidade NÃO existe ainda: ela depende de atendente
obrigatório, título derivado e validação de elegibilidade, que entram na
etapa seguinte.

Enquanto isso, QUALIDADE na criação é recusada com 422. A alternativa óbvia
— deixar o campo fora de `ChamadoCreate` — é pior do que parece: o Pydantic
descarta campo desconhecido em silêncio, e um frontend que mandasse
QUALIDADE antes da hora criaria o chamado como TI sem ninguém perceber.

`setor_destino` não é o setor do solicitante (`usuarios.setor_id`). Um não
substitui o outro, e nenhum teste aqui depende do setor de quem abre.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Chamado

TITULO_OK = "Impressora do RH não liga"
DESCRICAO_OK = "Não dá sinal de vida desde ontem à tarde"


def corpo(solicitante_id, **sobrescreve):
    """Corpo de criação idêntico ao que o frontend atual manda — sem o campo novo."""
    base = {
        "titulo": TITULO_OK,
        "descricao": DESCRICAO_OK,
        "categoria_id": 1,
        "solicitante_id": solicitante_id,
    }
    base.update(sobrescreve)
    return base


def _comum(autenticar, dados):
    return autenticar(dados["comum_id"], "usuario.teste", "Usuario")


def _tecnico(autenticar, dados):
    return autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico")


def _recusou_o_setor(resposta):
    """422 pelo campo certo — e não por outro campo que o teste estragou sem querer."""
    if resposta.status_code != 422:
        return False
    return any(erro["loc"][-1] == "setor_destino" for erro in resposta.json()["detail"])


def _semear(sessao, solicitante_id, setores):
    """Grava chamados direto pelo ORM, um por item de `setores`, e devolve os ids."""
    ids = []
    for i, setor in enumerate(setores):
        chamado = Chamado(
            protocolo=f"CH-SEMENTE-{i:03d}",
            solicitante_id=solicitante_id,
            titulo="Chamado de semente",
            descricao="Gravado direto no banco para o teste",
            status="Aberto",
            prioridade="Média",
            setor_destino=setor,
        )
        sessao.add(chamado)
        sessao.flush()
        ids.append(chamado.id)
    sessao.commit()
    return ids


class TestPadraoTI:
    def test_cliente_antigo_sem_o_campo_cria_chamado_de_ti(
        self, cliente, dados, sessao, autenticar
    ):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"]),
            headers=_comum(autenticar, dados),
        )

        assert resposta.status_code == 201
        assert resposta.json()["setor_destino"] == "TI"
        gravado = sessao.get(Chamado, resposta.json()["id"])
        sessao.refresh(gravado)
        assert gravado.setor_destino == "TI"

    def test_ti_explicito_cria_chamado_de_ti(self, cliente, dados, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], setor_destino="TI"),
            headers=_comum(autenticar, dados),
        )

        assert resposta.status_code == 201
        assert resposta.json()["setor_destino"] == "TI"

    def test_chamado_gravado_sem_o_campo_pelo_orm_e_ti(self, cliente, dados, autenticar):
        """O chamado da fixture nasce sem `setor_destino`, como todo chamado anterior a ele."""
        resposta = cliente.get(
            f"/api/v1/chamados/{dados['chamado_id']}",
            headers=_comum(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert resposta.json()["setor_destino"] == "TI"

    def test_insert_por_sql_sem_a_coluna_cai_no_default_do_banco(
        self, cliente, dados, sessao, autenticar
    ):
        """
        É o caso da API antiga durante um rollback de imagem, e de qualquer
        INSERT por SQL direto: só o `server_default` responde por ele — o
        `default` do model só vale para linhas criadas pelo ORM.

        As datas vão explícitas porque, no banco dos testes, elas só têm default
        do lado do Python; no PostgreSQL o schema dá `DEFAULT CURRENT_TIMESTAMP`.
        """
        sessao.execute(
            text(
                "INSERT INTO chamados (id, protocolo, solicitante_id, titulo, descricao, "
                "status, prioridade, cancelado, arquivado, data_abertura, "
                "data_atualizacao, created_at, updated_at) VALUES "
                "(900, 'CH-SQL-900', :solicitante, 'Gravado por SQL', "
                "'INSERT que não conhece a coluna nova', 'Aberto', 'Média', false, false, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"solicitante": dados["comum_id"]},
        )
        sessao.commit()

        resposta = cliente.get("/api/v1/chamados/900", headers=_comum(autenticar, dados))

        assert resposta.status_code == 200
        assert resposta.json()["setor_destino"] == "TI"


class TestQualidadeBloqueadaAteAProximaEtapa:
    def test_qualidade_na_criacao_e_422_e_nada_e_gravado(
        self, cliente, dados, sessao, autenticar
    ):
        antes = sessao.query(Chamado).count()

        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], setor_destino="QUALIDADE"),
            headers=_comum(autenticar, dados),
        )

        assert _recusou_o_setor(resposta)
        assert sessao.query(Chamado).count() == antes

    def test_equipe_tambem_nao_cria_qualidade(self, cliente, dados, sessao, autenticar):
        """O bloqueio não é de perfil: ninguém abre para a Qualidade antes das validações."""
        antes = sessao.query(Chamado).count()

        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], setor_destino="QUALIDADE"),
            headers=_tecnico(autenticar, dados),
        )

        assert _recusou_o_setor(resposta)
        assert sessao.query(Chamado).count() == antes


class TestValorInvalido:
    @pytest.mark.parametrize("valor", ["XYZ", "ti", "Qualidade", "", None, 1])
    def test_criacao_recusa(self, cliente, dados, sessao, autenticar, valor):
        """
        `"ti"` e `"Qualidade"`: o valor é exatamente o do CHECK do banco, sem
        normalizar caixa. `None` explícito também é recusado — a coluna é
        NOT NULL, e "não enviar" já é o jeito de pedir o padrão.
        """
        antes = sessao.query(Chamado).count()

        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], setor_destino=valor),
            headers=_comum(autenticar, dados),
        )

        assert _recusou_o_setor(resposta)
        assert sessao.query(Chamado).count() == antes

    def test_check_do_banco_recusa_valor_fora_da_lista(self, dados, sessao):
        """O CHECK vale também para quem grava sem passar pela API."""
        sessao.add(
            Chamado(
                protocolo="CH-INVALIDO",
                solicitante_id=dados["comum_id"],
                titulo="Setor inválido",
                descricao="Gravação direta com valor fora do CHECK",
                setor_destino="RH",
            )
        )

        with pytest.raises(IntegrityError):
            sessao.commit()
        sessao.rollback()

    def test_filtro_recusa(self, cliente, dados, autenticar):
        resposta = cliente.get(
            "/api/v1/chamados/?setor_destino=XYZ",
            headers=_comum(autenticar, dados),
        )

        assert _recusou_o_setor(resposta)


class TestRespostaExpoeOCampo:
    def test_listagem_traz_o_setor_em_todo_chamado(self, cliente, dados, sessao, autenticar):
        _semear(sessao, dados["comum_id"], ["TI", "QUALIDADE"])

        resposta = cliente.get("/api/v1/chamados/", headers=_comum(autenticar, dados))

        assert resposta.status_code == 200
        assert {c["setor_destino"] for c in resposta.json()} == {"TI", "QUALIDADE"}

    def test_detalhe_de_chamado_da_qualidade_gravado_pelo_banco(
        self, cliente, dados, sessao, autenticar
    ):
        """Ler um chamado da Qualidade já funciona; só a criação pela API espera a etapa 2."""
        (chamado_id,) = _semear(sessao, dados["comum_id"], ["QUALIDADE"])

        resposta = cliente.get(
            f"/api/v1/chamados/{chamado_id}", headers=_comum(autenticar, dados)
        )

        assert resposta.status_code == 200
        assert resposta.json()["setor_destino"] == "QUALIDADE"


class TestFiltroDaListagem:
    def test_filtra_por_setor(self, cliente, dados, sessao, autenticar):
        # O chamado da fixture é o sexto TI.
        _semear(sessao, dados["comum_id"], ["TI"] * 5 + ["QUALIDADE"] * 3)
        headers = _comum(autenticar, dados)

        qualidade = cliente.get("/api/v1/chamados/?setor_destino=QUALIDADE", headers=headers)
        ti = cliente.get("/api/v1/chamados/?setor_destino=TI", headers=headers)
        todos = cliente.get("/api/v1/chamados/", headers=headers)

        assert len(qualidade.json()) == 3
        assert all(c["setor_destino"] == "QUALIDADE" for c in qualidade.json())
        assert len(ti.json()) == 6
        assert all(c["setor_destino"] == "TI" for c in ti.json())
        assert len(todos.json()) == 9

    def test_filtro_pagina_sem_repetir_nem_pular(self, cliente, dados, sessao, autenticar):
        setores = ["QUALIDADE", "TI", "QUALIDADE", "TI", "QUALIDADE"]
        ids = _semear(sessao, dados["comum_id"], setores)
        # A listagem ordena por id decrescente.
        esperados = sorted(
            (i for i, s in zip(ids, setores) if s == "QUALIDADE"), reverse=True
        )
        headers = _comum(autenticar, dados)

        pagina_1 = cliente.get(
            "/api/v1/chamados/?setor_destino=QUALIDADE&limit=2&skip=0", headers=headers
        ).json()
        pagina_2 = cliente.get(
            "/api/v1/chamados/?setor_destino=QUALIDADE&limit=2&skip=2", headers=headers
        ).json()

        assert [c["id"] for c in pagina_1] + [c["id"] for c in pagina_2] == esperados

    def test_combina_com_os_filtros_existentes(self, cliente, dados, sessao, autenticar):
        ids = _semear(sessao, dados["comum_id"], ["QUALIDADE", "QUALIDADE"])
        cancelado = sessao.get(Chamado, ids[0])
        cancelado.cancelado = True
        sessao.commit()
        headers = _comum(autenticar, dados)

        padrao = cliente.get("/api/v1/chamados/?setor_destino=QUALIDADE", headers=headers)
        com_cancelados = cliente.get(
            "/api/v1/chamados/?setor_destino=QUALIDADE&incluir_cancelados=true",
            headers=headers,
        )
        outro_status = cliente.get(
            "/api/v1/chamados/?setor_destino=QUALIDADE&status=Resolvido", headers=headers
        )

        assert [c["id"] for c in padrao.json()] == [ids[1]]
        assert len(com_cancelados.json()) == 2
        assert outro_status.json() == []


class TestNadaMaisMuda:
    def test_tecnico_responsavel_continua_ignorado_na_criacao(
        self, cliente, dados, sessao, autenticar
    ):
        """
        O frontend manda `tecnico_responsavel_id` quando a equipe abre chamado,
        e a API sempre descartou o campo. Continuar descartando é o que mantém
        a TI igual — aceitá-lo aqui atribuiria chamados que hoje nascem sem
        responsável.
        """
        resposta = cliente.post(
            "/api/v1/chamados/",
            json=corpo(dados["comum_id"], tecnico_responsavel_id=dados["tecnico_id"]),
            headers=_tecnico(autenticar, dados),
        )

        assert resposta.status_code == 201
        assert resposta.json()["tecnico_responsavel_id"] is None
        assert sessao.get(Chamado, resposta.json()["id"]).tecnico_responsavel_id is None

    def test_put_nao_muda_o_setor(self, cliente, dados, sessao, autenticar):
        """O setor é decidido na abertura; o PUT não o conhece."""
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"setor_destino": "QUALIDADE", "status": "Em Andamento"},
            headers=_tecnico(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert resposta.json()["setor_destino"] == "TI"
        assert resposta.json()["status"] == "Em Andamento"
        chamado = sessao.get(Chamado, dados["chamado_id"])
        sessao.refresh(chamado)
        assert chamado.setor_destino == "TI"

    def test_usuario_comum_continua_sem_put(self, cliente, dados, autenticar):
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"status": "Em Andamento"},
            headers=_comum(autenticar, dados),
        )

        assert resposta.status_code == 403
