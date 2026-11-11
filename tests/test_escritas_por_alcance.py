"""
Escritas de chamado pelo alcance de quem pede (API-6, D8 e D12).

A auditoria da API-5 achou o técnico da Qualidade editando, cancelando e
arquivando chamado da TI — e recebendo na resposta o chamado que ele não
podia ler, inclusive a versão no 409. E qualquer conta descobria se um id
existia pelas recusas de cancelar, avaliar e atender, que davam 403 a um id
existente e 404 a um inexistente.

A matriz aqui é perfil × chamado × operação, com o esperado escrito à mão a
partir das decisões (`ESCRITA_DA_EQUIPE` e as regras de `_esperado`), não
derivado do código. Cada caso confere também que a recusa não gravou nada —
nem campo, nem histórico, nem versão — e que o 404 de quem não lê é idêntico
ao de um id que não existe.

Desde a API-13 o técnico da TI altera só os chamados da TI: os da Qualidade
ele nem lê, e recebe o 404. Até a API-12 alterava os dois setores (D1).
"""

import pytest

from app.models import Chamado
from app.models.historico import HistoricoChamado
from leitura_cenario import CHAMADOS, DA_TI, LEITURA_ESPERADA, ROLE_DE, cenario_de_leitura  # noqa: F401

API = "/api/v1"
INEXISTENTE = 999_999
NAO_ENCONTRADO = {"detail": "Chamado não encontrado"}
FORA_DA_EQUIPE = {"detail": "Este chamado não é da sua equipe"}

# D8: o que cada conta altera pelas rotas da equipe. Só o alcance do perfil;
# o vínculo (solicitante, responsável) não entra.
ESCRITA_DA_EQUIPE = {
    "admin": set(CHAMADOS),
    "admin_da_qualidade": set(CHAMADOS),
    "tecnico_ti": DA_TI,  # API-13, setor em SETORES_TI_IDS; até a API-12, os dois setores (D1)
    "tecnico_qualidade": {"q_atribuido", "q_reatribuido"},  # D2: não o ti_com_tecnico_da_q, que ele lê
    "tecnico_sem_setor": set(),  # H1
    "tecnico_outro_setor": set(),  # D10
}

# O estado de cada chamado do cenário, por nome de conta.
SOLICITANTE = {
    "ti_do_solicitante": "solicitante",
    "q_atribuido": "solicitante",
}
RESPONSAVEL = {
    "q_atribuido": "atendente",
    "q_reatribuido": "atendente",
    "ti_com_tecnico_da_q": "tecnico_qualidade",
}
QUALIDADE = {"q_atribuido", "q_reatribuido"}
# Elegíveis para a Qualidade: setor dela, ativos, sem conta de serviço e com
# perfil Técnico (API-13). Até a API-12 valia qualquer perfil, e entravam
# também a atendente e a ex-responsável (comuns) e o administrador da
# Qualidade. Com isso a atendente, responsável do q_atribuido e do
# q_reatribuido no cenário (estado legado), passa a receber 403 no atendimento.
ELEGIVEIS_DA_QUALIDADE = {"tecnico_qualidade"}

OPERACOES = ["put", "put_versao_velha", "cancelar", "arquivar", "desarquivar", "avaliar", "atendimento"]
ALVOS = sorted(CHAMADOS) + ["inexistente"]


def _esperado(quem: str, alvo: str, op: str) -> int:
    existe = alvo != "inexistente"
    le = existe and alvo in LEITURA_ESPERADA[quem]
    altera = existe and alvo in ESCRITA_DA_EQUIPE.get(quem, set())
    arquivado = alvo == "ti_arquivado"
    cancelado = alvo == "ti_cancelado"

    if op in ("put", "put_versao_velha", "arquivar", "desarquivar"):
        if quem not in ROLE_DE:
            return 403  # require_staff, antes de buscar o chamado: não distingue ids
        if not le:
            return 404
        if not altera:
            return 403
        if op == "put_versao_velha":
            return 409
        if op == "arquivar":
            return 400 if arquivado else 200
        if op == "desarquivar":
            return 200 if arquivado else 400
        return 200

    if not le:
        return 404

    if op == "cancelar":
        if not (altera or SOLICITANTE.get(alvo, "outro_solicitante") == quem):
            return 403
        return 400 if cancelado else 200

    if op == "avaliar":
        if SOLICITANTE.get(alvo, "outro_solicitante") != quem:
            return 403
        return 409  # todos abertos: ainda não avaliáveis

    # atendimento
    if alvo not in QUALIDADE or quem not in ELEGIVEIS_DA_QUALIDADE or RESPONSAVEL.get(alvo) != quem:
        return 403
    return 200


CASOS = [(quem, alvo, op) for quem in sorted(LEITURA_ESPERADA) for alvo in ALVOS for op in OPERACOES]


def _versao(sessao, cid) -> int:
    sessao.expire_all()
    chamado = sessao.get(Chamado, cid)
    return chamado.versao if chamado is not None else 1


def _foto(sessao, cid):
    sessao.expire_all()
    chamado = sessao.get(Chamado, cid)
    if chamado is None:
        return None
    campos = ("status", "prioridade", "tecnico_responsavel_id", "cancelado", "arquivado", "avaliacao", "solucao", "versao")
    historicos = sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == cid).count()
    return tuple(getattr(chamado, campo) for campo in campos) + (historicos,)


def _requisicao(cliente, op, cid, versao, headers):
    url = f"{API}/chamados/{cid}"
    if op == "put":
        return cliente.put(url, headers=headers, json={"prioridade": "Alta", "versao_esperada": versao})
    if op == "put_versao_velha":
        return cliente.put(url, headers=headers, json={"prioridade": "Alta", "versao_esperada": versao + 50})
    if op in ("cancelar", "arquivar", "desarquivar"):
        return cliente.patch(f"{url}/{op}", headers=headers, json={"versao_esperada": versao})
    if op == "avaliar":
        return cliente.patch(f"{url}/avaliar", headers=headers, json={"avaliacao": 5})
    return cliente.patch(f"{url}/atendimento", headers=headers, json={"status": "Em Andamento", "versao_esperada": versao})


@pytest.fixture
def como(autenticar, cenario_de_leitura):
    def _como(quem):
        return autenticar(cenario_de_leitura[quem], quem, ROLE_DE.get(quem, "Usuario"))

    return _como


@pytest.mark.parametrize("quem,alvo,op", CASOS)
def test_matriz_de_escrita(cliente, sessao, como, quem, alvo, op):
    cid = CHAMADOS.get(alvo, INEXISTENTE)
    antes = _foto(sessao, cid)
    resposta = _requisicao(cliente, op, cid, _versao(sessao, cid), como(quem))
    esperado = _esperado(quem, alvo, op)

    assert resposta.status_code == esperado, resposta.text
    corpo = resposta.json()
    if esperado == 200:
        assert corpo["id"] == cid
        return

    # Toda recusa: nada gravado, e a versão só para quem altera o chamado.
    assert _foto(sessao, cid) == antes
    if esperado == 409 and op == "put_versao_velha":
        assert corpo["versao_atual"] == antes[7]
        return
    assert "versao_atual" not in corpo
    if esperado == 404:
        assert corpo == NAO_ENCONTRADO
    if esperado == 403 and op in ("put", "put_versao_velha", "arquivar", "desarquivar") and quem in ROLE_DE:
        assert corpo == FORA_DA_EQUIPE


class TestEstados:
    """
    O alcance não depende do estado: a mesma recusa em aberto, em andamento,
    aguardando, resolvido, cancelado e arquivado — e a mesma permissão.
    """

    ESTADOS = [
        ("Aberto", {}),
        ("Em Andamento", {}),
        ("Aguardando", {}),
        ("Resolvido", {}),
        ("Aberto", {"cancelado": True}),
        ("Aberto", {"arquivado": True}),
    ]
    IDS = ["aberto", "em-andamento", "aguardando", "resolvido", "cancelado", "arquivado"]

    def _por_no_estado(self, sessao, cid, status, marcas):
        chamado = sessao.get(Chamado, cid)
        chamado.status = status
        for marca, valor in marcas.items():
            setattr(chamado, marca, valor)
        sessao.commit()

    @pytest.mark.parametrize("estado", range(6), ids=IDS)
    @pytest.mark.parametrize("quem", ["tecnico_qualidade", "tecnico_outro_setor", "tecnico_sem_setor"])
    @pytest.mark.parametrize("op", ["put", "put_versao_velha", "cancelar", "arquivar", "desarquivar"])
    def test_fora_do_alcance_e_404_em_qualquer_estado(self, cliente, sessao, como, estado, quem, op):
        cid = CHAMADOS["ti_sem_responsavel"]
        self._por_no_estado(sessao, cid, *self.ESTADOS[estado])
        antes = _foto(sessao, cid)
        resposta = _requisicao(cliente, op, cid, _versao(sessao, cid), como(quem))
        assert (resposta.status_code, resposta.json()) == (404, NAO_ENCONTRADO)
        assert _foto(sessao, cid) == antes

    @pytest.mark.parametrize("estado", range(6), ids=IDS)
    @pytest.mark.parametrize("op", ["put", "put_versao_velha", "cancelar", "arquivar", "desarquivar"])
    def test_tecnico_da_ti_fora_da_qualidade_e_404_em_qualquer_estado(self, cliente, sessao, como, estado, op):
        """API-13: até a API-12 o técnico da TI alterava o chamado da Qualidade em qualquer estado."""
        cid = CHAMADOS["q_reatribuido"]
        self._por_no_estado(sessao, cid, *self.ESTADOS[estado])
        antes = _foto(sessao, cid)
        resposta = _requisicao(cliente, op, cid, _versao(sessao, cid), como("tecnico_ti"))
        assert (resposta.status_code, resposta.json()) == (404, NAO_ENCONTRADO)
        assert _foto(sessao, cid) == antes

    @pytest.mark.parametrize("estado", range(6), ids=IDS)
    @pytest.mark.parametrize(
        "quem,alvo",
        [
            ("tecnico_ti", "ti_sem_responsavel"),
            # API-13: na Qualidade, o administrador; até a API-12 também o técnico da TI.
            ("admin", "q_reatribuido"),
            ("tecnico_qualidade", "q_reatribuido"),
            ("admin", "ti_sem_responsavel"),
        ],
    )
    def test_dentro_do_alcance_o_put_vale_em_qualquer_estado(self, cliente, sessao, como, estado, quem, alvo):
        cid = CHAMADOS[alvo]
        self._por_no_estado(sessao, cid, *self.ESTADOS[estado])
        resposta = _requisicao(cliente, "put", cid, _versao(sessao, cid), como(quem))
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["prioridade"] == "Alta"


class TestPrecedencia:
    def test_sem_token_continua_401(self, cliente):
        cid = CHAMADOS["ti_sem_responsavel"]
        assert cliente.put(f"{API}/chamados/{cid}", json={"prioridade": "Alta"}).status_code == 401

    def test_corpo_invalido_continua_422_antes_do_404(self, cliente, como):
        cid = CHAMADOS["ti_sem_responsavel"]
        resposta = cliente.put(f"{API}/chamados/{cid}", headers=como("tecnico_qualidade"), json={"prioridade": "Urgentíssima"})
        assert resposta.status_code == 422

    def test_qualidade_sem_versao_continua_428_para_quem_altera(self, cliente, como):
        cid = CHAMADOS["q_reatribuido"]
        resposta = cliente.put(f"{API}/chamados/{cid}", headers=como("tecnico_qualidade"), json={"prioridade": "Alta"})
        assert resposta.status_code == 428

    def test_qualidade_sem_versao_e_404_para_quem_nao_le(self, cliente, como):
        cid = CHAMADOS["q_reatribuido"]
        resposta = cliente.put(f"{API}/chamados/{cid}", headers=como("tecnico_outro_setor"), json={"prioridade": "Alta"})
        assert (resposta.status_code, resposta.json()) == (404, NAO_ENCONTRADO)

    def test_ti_sem_versao_continua_aceita(self, cliente, como):
        cid = CHAMADOS["ti_sem_responsavel"]
        resposta = cliente.put(f"{API}/chamados/{cid}", headers=como("tecnico_ti"), json={"prioridade": "Alta"})
        assert resposta.status_code == 200

    def test_atendimento_de_quem_nao_le_nao_diz_o_setor(self, cliente, como):
        """Antes: "Esta rota atende só chamados da Qualidade" contra "Você não atende a Qualidade"."""
        corpos = {
            cliente.patch(
                f"{API}/chamados/{cid}/atendimento",
                headers=como("intruso"),
                json={"status": "Em Andamento", "versao_esperada": 1},
            ).text
            for cid in (CHAMADOS["ti_sem_responsavel"], CHAMADOS["q_reatribuido"], INEXISTENTE)
        }
        assert corpos == {'{"detail":"Chamado não encontrado"}'}

    def test_sonda_d6_do_atendimento_continua_405(self, cliente, como):
        assert cliente.get(f"{API}/chamados/0/atendimento", headers=como("solicitante")).status_code == 405


class TestVinculoNaoDaPoderDeEquipe:
    def test_tecnico_da_qualidade_responsavel_de_chamado_da_ti_le_mas_nao_altera(self, cliente, como, sessao):
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        tecnico = como("tecnico_qualidade")
        assert cliente.get(f"{API}/chamados/{cid}", headers=tecnico).status_code == 200
        for op in ("put", "arquivar"):
            resposta = _requisicao(cliente, op, cid, _versao(sessao, cid), tecnico)
            assert (resposta.status_code, resposta.json()) == (403, FORA_DA_EQUIPE)
        resposta = _requisicao(cliente, "cancelar", cid, _versao(sessao, cid), tecnico)
        assert resposta.status_code == 403

    def test_tecnico_da_qualidade_cancela_como_solicitante(self, cliente, como, sessao, cenario_de_leitura):
        """O ramo do solicitante não depende do alcance: quem abriu cancela o que abriu."""
        cid = CHAMADOS["ti_sem_responsavel"]
        chamado = sessao.get(Chamado, cid)
        chamado.solicitante_id = cenario_de_leitura["tecnico_qualidade"]
        sessao.commit()
        tecnico = como("tecnico_qualidade")
        assert _requisicao(cliente, "put", cid, _versao(sessao, cid), tecnico).status_code == 403
        resposta = _requisicao(cliente, "cancelar", cid, _versao(sessao, cid), tecnico)
        assert resposta.status_code == 200
        assert resposta.json()["cancelado"] is True
