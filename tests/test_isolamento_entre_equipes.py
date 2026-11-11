"""
Cada equipe no seu setor de destino (API-13).

A TI e a Qualidade passam a ser publicadas juntas, e a separação entre as
duas equipes mora aqui, no backend: o técnico da TI não lê, não altera e não
vê o interno dos chamados da Qualidade, e o da Qualidade não altera os da TI
— nem mexendo no corpo. Até a API-12 o técnico da TI lia e alterava os dois
setores (D1); o caminho inverso já era fechado (D2).

A abertura também está aqui: o front 1.8.0 manda o setor sempre, e a
ausência, que só o front antigo produz, segue valendo TI com um aviso no log.
"""

import logging

import pytest

from leitura_cenario import CHAMADOS, cenario_de_leitura, comentario_interno  # noqa: F401
from test_leitura_por_chamado import API, como  # noqa: F401


def _versao(cliente, h, cid):
    return cliente.get(f"{API}/chamados/{cid}", headers=h).json()["versao"]


class TestAlterarComoEquipe:
    def test_tecnico_ti_nao_altera_chamado_da_qualidade(self, cliente, como):
        """Ele nem lê: o 404 de um chamado que não existe, em toda rota da equipe."""
        h = como("tecnico_ti")
        cid = CHAMADOS["q_atribuido"]
        assert cliente.put(f"{API}/chamados/{cid}", headers=h, json={"prioridade": "Alta", "versao_esperada": 1}).status_code == 404
        assert cliente.patch(f"{API}/chamados/{cid}/arquivar", headers=h, json={"versao_esperada": 1}).status_code == 404
        assert cliente.patch(f"{API}/chamados/{cid}/cancelar", headers=h, json={"versao_esperada": 1}).status_code == 404

    def test_tecnico_ti_altera_chamado_da_ti(self, cliente, como):
        h = como("tecnico_ti")
        cid = CHAMADOS["ti_sem_responsavel"]
        r = cliente.put(f"{API}/chamados/{cid}", headers=h, json={"prioridade": "Alta", "versao_esperada": _versao(cliente, h, cid)})
        assert r.status_code == 200, r.text

    def test_tecnico_qualidade_nao_altera_chamado_da_ti_que_nao_le(self, cliente, como):
        h = como("tecnico_qualidade")
        cid = CHAMADOS["ti_sem_responsavel"]
        assert cliente.put(f"{API}/chamados/{cid}", headers=h, json={"prioridade": "Alta"}).status_code == 404

    def test_tecnico_qualidade_nao_altera_chamado_da_ti_que_le_pelo_vinculo(self, cliente, como):
        """Ser o responsável dá a leitura, não o poder da equipe da TI."""
        h = como("tecnico_qualidade")
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        assert cliente.get(f"{API}/chamados/{cid}", headers=h).status_code == 200
        r = cliente.put(f"{API}/chamados/{cid}", headers=h, json={"prioridade": "Alta"})
        assert r.status_code == 403
        assert r.json()["detail"] == "Este chamado não é da sua equipe"

    def test_tecnico_qualidade_altera_chamado_da_qualidade(self, cliente, como):
        h = como("tecnico_qualidade")
        cid = CHAMADOS["q_atribuido"]
        r = cliente.put(f"{API}/chamados/{cid}", headers=h, json={"prioridade": "Alta", "versao_esperada": _versao(cliente, h, cid)})
        assert r.status_code == 200, r.text

    def test_administrador_humano_altera_os_dois(self, cliente, como):
        h = como("admin")
        for nome in ("ti_sem_responsavel", "q_atribuido"):
            cid = CHAMADOS[nome]
            r = cliente.put(f"{API}/chamados/{cid}", headers=h, json={"prioridade": "Alta", "versao_esperada": _versao(cliente, h, cid)})
            assert r.status_code == 200, (nome, r.text)

    def test_o_corpo_nao_muda_o_setor_do_chamado(self, cliente, como):
        """`setor_destino` no PUT é ignorado: mudar o setor não é edição de equipe."""
        h = como("admin")
        cid = CHAMADOS["ti_sem_responsavel"]
        r = cliente.put(f"{API}/chamados/{cid}", headers=h, json={"setor_destino": "QUALIDADE", "prioridade": "Baixa"})
        assert r.status_code == 200, r.text
        assert r.json()["setor_destino"] == "TI"
        # E o técnico da Qualidade continua sem lê-lo.
        assert cliente.get(f"{API}/chamados/{cid}", headers=como("tecnico_qualidade")).status_code == 404


class TestComentarioInternoPorSetor:
    @pytest.mark.parametrize(
        "quem,nome,esperado",
        [
            ("tecnico_qualidade", "q_atribuido", 201),
            ("tecnico_ti", "ti_sem_responsavel", 201),
            ("admin", "q_atribuido", 201),
            ("admin", "ti_sem_responsavel", 201),
            # Lê pelo vínculo, mas o interno é da equipe da TI.
            ("tecnico_qualidade", "ti_com_tecnico_da_q", 403),
            # A responsável de perfil Usuário atende pela rota dela, sem interno.
            ("atendente", "q_atribuido", 403),
        ],
    )
    def test_criar_interno(self, cliente, como, quem, nome, esperado):
        r = cliente.post(
            f"{API}/comentarios/",
            headers=como(quem),
            json={"chamado_id": CHAMADOS[nome], "comentario": "Nota interna fictícia", "is_interno": True},
        )
        assert r.status_code == esperado, r.text

    def test_marcar_como_interno_segue_o_setor(self, cliente, como):
        """Tornar interno um comentário público dele, num chamado da TI que ele lê pelo vínculo: 403."""
        h = como("tecnico_qualidade")
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        criado = cliente.post(f"{API}/comentarios/", headers=h, json={"chamado_id": cid, "comentario": "Público fictício", "is_interno": False})
        assert criado.status_code == 201, criado.text
        r = cliente.put(f"{API}/comentarios/{criado.json()['id']}", headers=h, json={"is_interno": True})
        assert r.status_code == 403

    def test_interno_da_qualidade_pelo_id(self, cliente, como):
        cid = CHAMADOS["q_atribuido"]
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=como("tecnico_qualidade")).status_code == 200
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=como("tecnico_ti")).status_code == 404


class TestAbertura:
    def _ti(self, solicitante, **extra):
        return {"titulo": "Impressora fictícia sem papel", "descricao": "Descrição fictícia longa o bastante.", "prioridade": "Baixa", "solicitante_id": solicitante, **extra}

    def test_ti_explicita(self, cliente, como, cenario_de_leitura):
        r = cliente.post(f"{API}/chamados/", headers=como("solicitante"), json=self._ti(cenario_de_leitura["solicitante"], setor_destino="TI"))
        assert r.status_code == 201, r.text
        assert r.json()["setor_destino"] == "TI"

    def test_sem_setor_e_ti_e_avisa_no_log(self, cliente, como, cenario_de_leitura, caplog):
        """Transição: o front antigo não manda o campo, e a abertura dele não pode quebrar."""
        with caplog.at_level(logging.WARNING, logger="app.api.endpoints.chamados"):
            r = cliente.post(f"{API}/chamados/", headers=como("solicitante"), json=self._ti(cenario_de_leitura["solicitante"]))
        assert r.status_code == 201, r.text
        assert r.json()["setor_destino"] == "TI"
        assert any("sem setor_destino" in m.getMessage() for m in caplog.records)

    def test_com_setor_nao_avisa(self, cliente, como, cenario_de_leitura, caplog):
        with caplog.at_level(logging.WARNING, logger="app.api.endpoints.chamados"):
            cliente.post(f"{API}/chamados/", headers=como("solicitante"), json=self._ti(cenario_de_leitura["solicitante"], setor_destino="TI"))
        assert not any("sem setor_destino" in m.getMessage() for m in caplog.records)

    @pytest.mark.parametrize("valor", ["RH", "qualidade", "", None, 1])
    def test_setor_invalido_422(self, cliente, como, cenario_de_leitura, valor):
        r = cliente.post(f"{API}/chamados/", headers=como("solicitante"), json=self._ti(cenario_de_leitura["solicitante"], setor_destino=valor))
        assert r.status_code == 422, r.text

    def test_qualidade_com_responsavel_da_ti_400(self, cliente, como, cenario_de_leitura):
        """O responsável da Qualidade sai da equipe da Qualidade: o técnico da TI não serve."""
        r = cliente.post(
            f"{API}/chamados/",
            headers=como("solicitante"),
            json={
                "setor_destino": "QUALIDADE",
                "descricao": "Desvio fictício na calibração da balança.",
                "solicitante_id": cenario_de_leitura["solicitante"],
                "tecnico_responsavel_id": cenario_de_leitura["tecnico_ti"],
            },
        )
        assert r.status_code == 400
        assert r.json()["detail"] == "Atendente não é elegível para a Qualidade"

    def test_qualidade_aberta_pelo_usuario_ele_acompanha(self, cliente, como, cenario_de_leitura):
        h = como("solicitante")
        r = cliente.post(
            f"{API}/chamados/",
            headers=h,
            json={
                "setor_destino": "QUALIDADE",
                "descricao": "Desvio fictício na calibração da balança.",
                "solicitante_id": cenario_de_leitura["solicitante"],
                "tecnico_responsavel_id": cenario_de_leitura["tecnico_qualidade"],
            },
        )
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert r.json()["setor_destino"] == "QUALIDADE"
        assert cliente.get(f"{API}/chamados/{cid}", headers=h).status_code == 200
        assert cliente.get(f"{API}/chamados/{cid}", headers=como("tecnico_qualidade")).status_code == 200
        assert cliente.get(f"{API}/chamados/{cid}", headers=como("tecnico_ti")).status_code == 404
