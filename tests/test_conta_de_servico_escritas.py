"""
Conta de serviço não altera chamado como equipe (API-11, decisão S2).

Até a API-10, a conta de serviço técnica da TI lia os chamados da TI e da
Qualidade pelo alcance do perfil — e, pelo mesmo alcance, os alterava: PUT,
arquivar, desarquivar, cancelar o alheio. A leitura é a do painel de parede;
a escrita não tinha uso documentado. Agora `pode_alterar_como_equipe` recusa
toda conta de serviço, qualquer perfil, e cada recusa sai sem escrita, sem
versão nova, sem histórico e sem webhook.

O que não passa pela equipe fica como era, e está aqui para não sumir por
acidente: ler, abrir chamado, comentar em público, cancelar o que ela mesma
abriu e avaliar o que ela abriu.
"""

import pytest

from app.api.endpoints import chamados as rotas_de_chamados
from app.models import Chamado
from app.models.comentario import ComentarioChamado
from app.models.historico import HistoricoChamado
from app.services.leitura_service import CONTA_DE_SERVICO_NAO_ALTERA, FORA_DA_EQUIPE
from leitura_cenario import CHAMADOS, cenario_de_leitura  # noqa: F401
from test_conta_de_servico_rotas import SERVICOS, como, configurar, saidas, servicos  # noqa: F401

API = "/api/v1"
CHAMADO_TI = CHAMADOS["ti_sem_responsavel"]  # 106, TI, de outro solicitante
ARQUIVADO = CHAMADOS["ti_arquivado"]  # 102, TI, arquivado
CHAMADO_Q = CHAMADOS["q_atribuido"]  # 101, Qualidade
TECNICO_TI_DOIS = 56  # pessoa elegível da TI, do cenário de `servicos`
NAO_E_SOLICITANTE = "Só é possível cancelar chamados abertos por você"

# As escritas de equipe, cada uma como (método, rota, corpo).
ESCRITAS_DE_EQUIPE = {
    "put_prioridade": ("PUT", f"/chamados/{CHAMADO_TI}", {"prioridade": "Alta"}),
    "put_status": ("PUT", f"/chamados/{CHAMADO_TI}", {"status": "Em Andamento"}),
    "put_solucao": ("PUT", f"/chamados/{CHAMADO_TI}", {"solucao": "Resolvido pela conta de serviço"}),
    "put_responsavel": ("PUT", f"/chamados/{CHAMADO_TI}", {"tecnico_responsavel_id": TECNICO_TI_DOIS}),
    "put_desatribuir": ("PUT", f"/chamados/{CHAMADOS['ti_com_tecnico_da_q']}", {"tecnico_responsavel_id": None}),
    "put_qualidade": ("PUT", f"/chamados/{CHAMADO_Q}", {"prioridade": "Alta", "versao_esperada": 1}),
    "arquivar": ("PATCH", f"/chamados/{CHAMADO_TI}/arquivar", None),
    "desarquivar": ("PATCH", f"/chamados/{ARQUIVADO}/desarquivar", None),
    "cancelar_alheio": ("PATCH", f"/chamados/{CHAMADO_TI}/cancelar", None),
}

# Quem lê o quê, entre as contas de serviço (perfil e vínculo do cenário).
LEITURA_DO_SERVICO = {
    "servico_tecnico_ti": set(CHAMADOS.values()),  # TI e Qualidade, pelo perfil
    "servico_admin_ti": set(CHAMADOS.values()),  # todos, pelo perfil
    "servico_tecnico_qualidade": {101, 103},  # a Qualidade, pelo perfil
    "servico_tecnico_outro": {ARQUIVADO},  # responsável atual do 102
    "servico_tecnico_sem_setor": set(),
    "servico_usuario_ti": {CHAMADOS["ti_cancelado"]},  # solicitante do 104
}


def _alvo(rota):
    return int(rota.split("/")[2])


def _esperado(quem, chave):
    """A recusa de cada conta de serviço, pela ordem real das checagens."""
    metodo, rota, _ = ESCRITAS_DE_EQUIPE[chave]
    perfil_usuario = SERVICOS[quem][1] == 3
    if perfil_usuario and chave != "cancelar_alheio":
        # `require_staff`, antes de buscar o chamado.
        return 403, "Requer perfil: Administrador, Tecnico"
    if _alvo(rota) not in LEITURA_DO_SERVICO[quem]:
        return 404, "Chamado não encontrado"
    if chave == "cancelar_alheio":
        return 403, NAO_E_SOLICITANTE
    return 403, CONTA_DE_SERVICO_NAO_ALTERA


@pytest.fixture
def webhooks(monkeypatch):
    """Toda chamada ao webhook da TI. `saidas` não basta: o serviço engole a exceção."""
    chamadas = []
    monkeypatch.setattr(rotas_de_chamados, "enviar_webhook_tecnico", lambda **kw: chamadas.append(kw))
    return chamadas


def _foto(sessao):
    sessao.expire_all()
    return {
        "chamados": sorted(
            (c.id, c.tecnico_responsavel_id, c.prioridade, c.status, c.solucao, c.arquivado, c.cancelado,
             c.avaliacao, c.versao)
            for c in sessao.query(Chamado)
        ),
        "historico": sorted((h.id, h.chamado_id, h.acao) for h in sessao.query(HistoricoChamado)),
        "comentarios": sessao.query(ComentarioChamado).count(),
    }


def _pedir(cliente, metodo, rota, corpo, headers):
    return cliente.request(metodo, f"{API}{rota}", headers=headers, json=corpo)


@pytest.mark.usefixtures("configurar", "saidas")
class TestRecusaSemEfeito:
    @pytest.mark.parametrize("chave", sorted(ESCRITAS_DE_EQUIPE))
    @pytest.mark.parametrize("quem", sorted(SERVICOS))
    def test_conta_de_servico_nao_escreve_como_equipe(self, cliente, como, sessao, webhooks, quem, chave):
        metodo, rota, corpo = ESCRITAS_DE_EQUIPE[chave]
        antes = _foto(sessao)
        resposta = _pedir(cliente, metodo, rota, corpo, como(quem))
        assert (resposta.status_code, resposta.json()) == (
            _esperado(quem, chave)[0], {"detail": _esperado(quem, chave)[1]}
        )
        assert _foto(sessao) == antes
        assert webhooks == []

    def test_a_recusa_vem_antes_da_versao(self, cliente, como, sessao):
        """Versão velha num chamado da Qualidade: 403 da equipe, não 409 nem 428."""
        h = como("servico_tecnico_qualidade")
        for corpo in ({"prioridade": "Alta", "versao_esperada": 999}, {"prioridade": "Alta"}):
            resposta = cliente.put(f"{API}/chamados/{CHAMADO_Q}", headers=h, json=corpo)
            assert (resposta.status_code, resposta.json()) == (403, {"detail": CONTA_DE_SERVICO_NAO_ALTERA})

    def test_sem_token_continua_401(self, cliente):
        assert cliente.put(f"{API}/chamados/{CHAMADO_TI}", json={"prioridade": "Alta"}).status_code == 401


@pytest.mark.usefixtures("configurar", "saidas")
class TestOQueContinua:
    """A técnica de serviço da TI: o que não vem da equipe."""

    def test_le_o_kanban_o_detalhe_e_o_historico(self, cliente, como):
        h = como("servico_tecnico_ti")
        ids = {c["id"] for c in cliente.get(f"{API}/chamados/?incluir_arquivados=true&incluir_cancelados=true",
                                           headers=h).json()}
        assert set(CHAMADOS.values()) <= ids
        assert cliente.get(f"{API}/chamados/{CHAMADO_TI}", headers=h).status_code == 200
        assert cliente.get(f"{API}/historico/chamado/{CHAMADO_TI}", headers=h).status_code == 200

    def test_abre_cancela_e_avalia_o_proprio(self, cliente, como, sessao, webhooks):
        h = como("servico_tecnico_ti")
        aberto = cliente.post(f"{API}/chamados/", headers=h, json={
            "titulo": "Painel sem imagem", "descricao": "A TV da sala apagou durante a manhã",
            "solicitante_id": 70,
        })
        assert aberto.status_code == 201, aberto.text
        cid = aberto.json()["id"]
        assert aberto.json()["solicitante_id"] == 70
        # A pessoa da TI resolve; a conta de serviço, solicitante, avalia.
        resolvido = cliente.put(f"{API}/chamados/{cid}", headers=como("tecnico_ti"), json={"status": "Resolvido"})
        assert resolvido.status_code == 200
        avaliado = cliente.patch(f"{API}/chamados/{cid}/avaliar", headers=h, json={"avaliacao": 5})
        assert avaliado.status_code == 200 and avaliado.json()["avaliacao"] == 5

        outro = cliente.post(f"{API}/chamados/", headers=h, json={
            "titulo": "Painel lento", "descricao": "O quadro demora a atualizar na TV", "solicitante_id": 70,
        }).json()["id"]
        cancelado = cliente.patch(f"{API}/chamados/{outro}/cancelar", headers=h)
        assert cancelado.status_code == 200 and cancelado.json()["cancelado"] is True

    def test_comenta_em_publico(self, cliente, como):
        resposta = cliente.post(f"{API}/comentarios/", headers=como("servico_tecnico_ti"), json={
            "chamado_id": CHAMADO_TI, "comentario": "Visto no painel",
        })
        assert resposta.status_code == 201 and resposta.json()["is_interno"] is False

    def test_mesmo_como_solicitante_nao_edita_pelo_put(self, cliente, como):
        """Ser o solicitante dá o cancelamento, não a edição de equipe."""
        h = como("servico_tecnico_ti")
        cid = cliente.post(f"{API}/chamados/", headers=h, json={
            "titulo": "Painel piscando", "descricao": "A imagem pisca a cada minuto", "solicitante_id": 70,
        }).json()["id"]
        for metodo, rota, corpo in (("PUT", f"/chamados/{cid}", {"prioridade": "Alta"}),
                                    ("PATCH", f"/chamados/{cid}/arquivar", None)):
            resposta = _pedir(cliente, metodo, rota, corpo, h)
            assert (resposta.status_code, resposta.json()) == (403, {"detail": CONTA_DE_SERVICO_NAO_ALTERA})


@pytest.mark.usefixtures("configurar", "saidas")
class TestPessoasNaoMudam:
    @pytest.mark.parametrize("chave", sorted(ESCRITAS_DE_EQUIPE))
    @pytest.mark.parametrize("quem", ["admin", "tecnico_ti"])
    def test_equipe_humana_continua_escrevendo(self, cliente, como, quem, chave):
        metodo, rota, corpo = ESCRITAS_DE_EQUIPE[chave]
        resposta = _pedir(cliente, metodo, rota, corpo, como(quem))
        assert resposta.status_code == 200, (resposta.status_code, resposta.text)

    def test_reatribuir_dispara_o_webhook(self, cliente, como, webhooks):
        resposta = cliente.put(f"{API}/chamados/{CHAMADO_TI}", headers=como("tecnico_ti"),
                               json={"tecnico_responsavel_id": TECNICO_TI_DOIS})
        assert resposta.status_code == 200
        assert [w["tecnico_id"] for w in webhooks] == [TECNICO_TI_DOIS]

    def test_qualidade_segue_segregada(self, cliente, como):
        h = como("tecnico_qualidade")
        # Lê pelo vínculo, mas não é da equipe do chamado da TI.
        vinculo = cliente.put(f"{API}/chamados/{CHAMADOS['ti_com_tecnico_da_q']}", headers=h,
                              json={"prioridade": "Alta"})
        assert (vinculo.status_code, vinculo.json()) == (403, {"detail": FORA_DA_EQUIPE})
        proprio = cliente.put(f"{API}/chamados/{CHAMADOS['q_reatribuido']}", headers=h,
                              json={"prioridade": "Alta", "versao_esperada": 1})
        assert proprio.status_code == 200
