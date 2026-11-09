"""
Leitura por chamado nas rotas (API-5, correção do O-1).

O detalhe, a listagem e o histórico passam pela política de
`leitura_service`, e quem não pode ler recebe o mesmo 404 de um chamado que
não existe (D6). Os comentários estão em `test_comentarios_por_chamado.py`.

A matriz vem de `leitura_cenario.LEITURA_ESPERADA`, escrita à mão a partir das
decisões D1–D5 (a D1 refeita na API-13: o técnico da TI lê só a TI). As
escritas não mudam: os testes do fim só conferem que
continuam respondendo como antes.
"""

import pytest

from leitura_cenario import (  # noqa: F401
    CHAMADOS,
    EX_RESPONSAVEL,
    INTRUSO,
    LEITURA_ESPERADA,
    ROLE_DE,
    cenario_de_leitura,
    historico_de,
)

API = "/api/v1"
INEXISTENTE = 999_999

PARES = [(quem, nome) for quem in sorted(LEITURA_ESPERADA) for nome in sorted(CHAMADOS)]


@pytest.fixture
def como(cenario_de_leitura, autenticar):
    def _headers(quem):
        return autenticar(cenario_de_leitura[quem], quem, ROLE_DE.get(quem, "Usuario"))

    return _headers


def _recusas_de_inexistente(cliente, headers):
    """O que cada rota responde para ids que não existem: é o que a recusa tem de imitar."""
    return {
        "detalhe": cliente.get(f"{API}/chamados/{INEXISTENTE}", headers=headers),
        "historico": cliente.get(f"{API}/historico/chamado/{INEXISTENTE}", headers=headers),
        "historico_id": cliente.get(f"{API}/historico/{INEXISTENTE}", headers=headers),
    }


def _mesma_recusa(resposta, modelo):
    assert resposta.status_code == 404, resposta.text
    assert resposta.json() == modelo.json()


@pytest.mark.parametrize("quem,nome", PARES)
def test_leitura_de_um_chamado_em_todas_as_rotas(cliente, como, quem, nome):
    h = como(quem)
    cid = CHAMADOS[nome]
    detalhe = cliente.get(f"{API}/chamados/{cid}", headers=h)
    historico = cliente.get(f"{API}/historico/chamado/{cid}", headers=h)
    historico_id = cliente.get(f"{API}/historico/{historico_de(cid)}", headers=h)

    if nome in LEITURA_ESPERADA[quem]:
        assert detalhe.status_code == 200, detalhe.text
        assert detalhe.json()["id"] == cid
        assert isinstance(detalhe.json()["versao"], int)
        assert historico.status_code == 200
        assert [r["id"] for r in historico.json()] == [historico_de(cid)]
        assert historico_id.status_code == 200
    else:
        modelo = _recusas_de_inexistente(cliente, h)
        _mesma_recusa(detalhe, modelo["detalhe"])
        _mesma_recusa(historico, modelo["historico"])
        _mesma_recusa(historico_id, modelo["historico_id"])


def test_a_recusa_nao_diz_nada_do_chamado(cliente, como):
    """D6: corpo igual ao do inexistente, sem versão, protocolo nem setor."""
    h = como("intruso")
    alheio = cliente.get(f"{API}/chamados/{CHAMADOS['q_atribuido']}", headers=h)
    inexistente = cliente.get(f"{API}/chamados/{INEXISTENTE}", headers=h)
    assert alheio.status_code == inexistente.status_code == 404
    assert alheio.json() == inexistente.json() == {"detail": "Chamado não encontrado"}
    assert alheio.headers.get("content-length") == inexistente.headers.get("content-length")


class TestListagem:
    TUDO = {"incluir_arquivados": "true", "incluir_cancelados": "true"}

    def _ids(self, cliente, h, **params):
        r = cliente.get(f"{API}/chamados/", headers=h, params=params)
        assert r.status_code == 200, r.text
        return [c["id"] for c in r.json()]

    @pytest.mark.parametrize("quem", sorted(LEITURA_ESPERADA))
    def test_devolve_so_o_que_pode_ler(self, cliente, como, quem):
        ids = self._ids(cliente, como(quem), **self.TUDO)
        assert set(ids) == {CHAMADOS[n] for n in LEITURA_ESPERADA[quem]}

    @pytest.mark.parametrize("quem", sorted(LEITURA_ESPERADA))
    def test_padrao_continua_sem_arquivado_e_cancelado(self, cliente, como, quem):
        ids = self._ids(cliente, como(quem))
        esperados = {CHAMADOS[n] for n in LEITURA_ESPERADA[quem]} - {
            CHAMADOS["ti_arquivado"], CHAMADOS["ti_cancelado"]
        }
        assert set(ids) == esperados

    @pytest.mark.parametrize("quem", sorted(LEITURA_ESPERADA))
    def test_paginacao_corta_do_conjunto_permitido(self, cliente, como, quem):
        """Página a página, de um em um: a soma é a lista inteira, na mesma ordem."""
        h = como(quem)
        inteira = self._ids(cliente, h, **self.TUDO)
        paginas = []
        for skip in range(len(CHAMADOS) + 1):
            paginas += self._ids(cliente, h, skip=skip, limit=1, **self.TUDO)
        assert paginas == inteira
        assert inteira == sorted(inteira, reverse=True)

    def test_filtro_por_outro_solicitante_nao_amplia(self, cliente, como, cenario_de_leitura):
        h = como("solicitante")
        alheio = self._ids(cliente, h, solicitante_id=cenario_de_leitura["outro_solicitante"], **self.TUDO)
        assert alheio == []

    def test_filtro_por_responsavel_alheio_nao_amplia(self, cliente, como, cenario_de_leitura):
        h = como("intruso")
        assert self._ids(cliente, h, tecnico_id=cenario_de_leitura["atendente"], **self.TUDO) == []

    def test_filtro_por_setor_nao_amplia(self, cliente, como):
        assert self._ids(cliente, como("intruso"), setor_destino="QUALIDADE", **self.TUDO) == []
        # Técnico da Qualidade pedindo a TI: só o chamado da TI que ele atende.
        assert self._ids(cliente, como("tecnico_qualidade"), setor_destino="TI", **self.TUDO) == [
            CHAMADOS["ti_com_tecnico_da_q"]
        ]

    def test_filtros_estreitam_dentro_do_permitido(self, cliente, como, cenario_de_leitura):
        # API-13: do outro solicitante, só os que o técnico da TI lê — o da
        # Qualidade fica de fora. Até a API-12 eram todos.
        h = como("tecnico_ti")
        do_outro = self._ids(cliente, h, solicitante_id=cenario_de_leitura["outro_solicitante"], **self.TUDO)
        assert set(do_outro) == {
            CHAMADOS[n] for n in LEITURA_ESPERADA["outro_solicitante"] & LEITURA_ESPERADA["tecnico_ti"]
        }
        assert "q_reatribuido" in LEITURA_ESPERADA["outro_solicitante"]

    def test_os_pedidos_do_frontend_para_usuario_comum(self, cliente, como, cenario_de_leitura):
        """
        Os dois pedidos que o ChamadosContext faz para o perfil Usuário dão o
        mesmo de antes: os próprios, e os da Qualidade atribuídos a ele.
        """
        h = como("atendente")
        atendente = cenario_de_leitura["atendente"]
        assert self._ids(cliente, h, solicitante_id=atendente) == []
        assert set(self._ids(cliente, h, tecnico_id=atendente, setor_destino="QUALIDADE")) == {
            CHAMADOS["q_atribuido"], CHAMADOS["q_reatribuido"]
        }
        h = como("solicitante")
        assert set(self._ids(cliente, h, solicitante_id=cenario_de_leitura["solicitante"])) == {
            CHAMADOS["ti_do_solicitante"], CHAMADOS["q_atribuido"]
        }


class TestExResponsavel:
    def test_reatribuir_tira_a_leitura_de_quem_saiu(self, cliente, como, autenticar, sessao, cenario_de_leitura):
        """
        D4, pela rota real: a eva atende o 103, a administradora passa o
        chamado para a ana, e a eva deixa de ler — detalhe, listagem,
        e histórico (os comentários estão em
        `test_comentarios_por_chamado.py`).
        """
        from app.models import Chamado

        cid = CHAMADOS["q_reatribuido"]
        chamado = sessao.get(Chamado, cid)
        chamado.tecnico_responsavel_id = EX_RESPONSAVEL
        sessao.commit()
        eva = autenticar(EX_RESPONSAVEL, "eva.qualidade", "Usuario")
        antes = cliente.get(f"{API}/chamados/{cid}", headers=eva)
        assert antes.status_code == 200

        r = cliente.put(
            f"{API}/chamados/{cid}",
            headers=como("admin"),
            json={"tecnico_responsavel_id": cenario_de_leitura["atendente"], "versao_esperada": antes.json()["versao"]},
        )
        assert r.status_code == 200, r.text

        assert cliente.get(f"{API}/chamados/{cid}", headers=eva).status_code == 404
        assert cliente.get(f"{API}/historico/chamado/{cid}", headers=eva).status_code == 404
        lista = cliente.get(f"{API}/chamados/", headers=eva, params={"tecnico_id": EX_RESPONSAVEL})
        assert lista.json() == []

    def test_ex_responsavel_que_e_solicitante_continua_lendo(self, cliente, autenticar, sessao, cenario_de_leitura):
        """A exceção de D4: quem abriu continua lendo, atenda ou não."""
        from app.models import Chamado

        cid = CHAMADOS["q_reatribuido"]
        chamado = sessao.get(Chamado, cid)
        chamado.solicitante_id = EX_RESPONSAVEL
        sessao.commit()
        eva = autenticar(EX_RESPONSAVEL, "eva.qualidade", "Usuario")
        assert cliente.get(f"{API}/chamados/{cid}", headers=eva).status_code == 200


class TestContas:
    def test_usuario_inativo_nao_le_nada(self, cliente, cenario_de_leitura, autenticar):
        h = autenticar(cenario_de_leitura["inativo_id"], "carla.qualidade", "Usuario")
        for rota in (
            f"{API}/chamados/{CHAMADOS['q_atribuido']}",
            f"{API}/chamados/",
            f"{API}/historico/chamado/{CHAMADOS['q_atribuido']}",
            f"{API}/comentarios/chamado/{CHAMADOS['q_atribuido']}",
        ):
            assert cliente.get(rota, headers=h).status_code == 403

    def test_varios_vinculos_nao_duplicam_na_listagem(self, cliente, como, sessao, cenario_de_leitura):
        """Solicitante e responsável do mesmo chamado: aparece uma vez."""
        from app.models import Chamado

        chamado = sessao.get(Chamado, CHAMADOS["ti_sem_responsavel"])
        chamado.tecnico_responsavel_id = cenario_de_leitura["outro_solicitante"]
        sessao.commit()
        r = cliente.get(f"{API}/chamados/", headers=como("outro_solicitante"))
        ids = [c["id"] for c in r.json()]
        assert len(ids) == len(set(ids))
        assert CHAMADOS["ti_sem_responsavel"] in ids


class TestForaDoEscopo:
    def test_diretorio_de_usuarios_continua_aberto(self, cliente, como, sessao):
        """D7: `GET /usuarios/` fica como está nesta etapa."""
        from app.models import Usuario

        h = como("intruso")
        r = cliente.get(f"{API}/usuarios/", headers=h, params={"limit": 500})
        assert r.status_code == 200
        assert {u["id"] for u in r.json()} == {u.id for u in sessao.query(Usuario).all()}
        assert cliente.get(f"{API}/usuarios/{EX_RESPONSAVEL}", headers=h).status_code == 200

    def test_atendentes_da_qualidade_continuam_abertos(self, cliente, como):
        assert cliente.get(f"{API}/chamados/atendentes-qualidade", headers=como("intruso")).status_code == 200

    def test_sonda_do_atendimento_continua_405(self, cliente, como):
        """A sonda D-6 do frontend não pode virar 404."""
        r = cliente.get(f"{API}/chamados/0/atendimento", headers=como("intruso"))
        assert r.status_code == 405

    def test_leitura_da_qualidade_nao_da_atendimento_ao_tecnico_ti(self, cliente, como):
        """
        API-13: o técnico da TI nem lê o chamado da Qualidade — o 404 de um
        que não existe. Até a API-12 lia (D1) e recebia 403.
        """
        r = cliente.patch(
            f"{API}/chamados/{CHAMADOS['q_atribuido']}/atendimento",
            headers=como("tecnico_ti"),
            json={"status": "Em Andamento", "versao_esperada": 1},
        )
        assert r.status_code == 404

    def test_leitura_da_qualidade_nao_da_atendimento_ao_tecnico_da_qualidade(self, cliente, como):
        """A leitura pelo perfil não dá atendimento: ele continua do responsável."""
        r = cliente.patch(
            f"{API}/chamados/{CHAMADOS['q_atribuido']}/atendimento",
            headers=como("tecnico_qualidade"),
            json={"status": "Em Andamento", "versao_esperada": 1},
        )
        assert r.status_code == 403

    def test_responsavel_continua_atendendo(self, cliente, como):
        r = cliente.patch(
            f"{API}/chamados/{CHAMADOS['q_atribuido']}/atendimento",
            headers=como("atendente"),
            json={"status": "Em Andamento", "versao_esperada": 1},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "Em Andamento"
