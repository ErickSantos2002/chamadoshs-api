"""
Editar e excluir comentário exige ver o comentário hoje (API-6, D11).

Até a API-5 bastava ser o autor: o ex-responsável editava e apagava o que
escreveu num chamado que já não lia (e a resposta da edição devolvia o
texto), o autor de comentário de antes da API-5 seguia mexendo nele, e o 403
de autoria dizia a qualquer conta que um id de comentário existia.

Agora a regra é a do `GET /comentarios/{id}`: o chamado legível e, se
interno, ser administrador ou técnico da TI (API-8; até a API-7, ser da
equipe). Fora disso, o 404 de um id que não existe, antes da autoria.
Dentro, as regras de sempre. A matriz do interno por perfil e configuração
está em `test_comentarios_internos_edicao.py`.
"""

import pytest

from app.models.comentario import ComentarioChamado
from leitura_cenario import (  # noqa: F401
    CHAMADOS,
    EX_RESPONSAVEL,
    INTRUSO,
    ROLE_DE,
    cenario_de_leitura,
    comentario_interno,
    comentario_publico,
)

API = "/api/v1"
NAO_ENCONTRADO = {"detail": "Comentário não encontrado"}
INEXISTENTE = 777_777


@pytest.fixture
def como(autenticar, cenario_de_leitura):
    def _como(quem):
        return autenticar(cenario_de_leitura[quem], quem, ROLE_DE.get(quem, "Usuario"))

    return _como


@pytest.fixture
def comentarios(cenario_de_leitura, sessao):
    """Comentários próprios de quem perdeu ou nunca teve a leitura, e de quem a tem."""
    d = cenario_de_leitura
    novos = {
        # eva escreveu quando atendia o 103; o chamado foi para a ana.
        "do_ex_responsavel": (CHAMADOS["q_reatribuido"], EX_RESPONSAVEL, False),
        # gravado antes da API-5, quando qualquer conta comentava em qualquer chamado.
        "antigo_do_intruso": (CHAMADOS["q_atribuido"], INTRUSO, False),
        "do_tecnico_q_na_ti": (CHAMADOS["ti_do_solicitante"], d["tecnico_qualidade"], False),
        "interno_do_tecnico_q_na_ti": (CHAMADOS["ti_do_solicitante"], d["tecnico_qualidade"], True),
        # o técnico da Qualidade lê o 105 pelo vínculo: o comentário dele lá segue dele.
        "do_tecnico_q_onde_atende": (CHAMADOS["ti_com_tecnico_da_q"], d["tecnico_qualidade"], False),
        "do_solicitante": (CHAMADOS["ti_do_solicitante"], d["solicitante"], False),
        "do_outro_no_cancelado": (CHAMADOS["ti_cancelado"], d["outro_solicitante"], False),
        "do_outro_no_arquivado": (CHAMADOS["ti_arquivado"], d["outro_solicitante"], False),
        "interno_do_tecnico_no_cancelado": (CHAMADOS["ti_cancelado"], d["tecnico_ti"], True),
    }
    ids = {}
    for n, (nome, (chamado_id, autor, interno)) in enumerate(novos.items()):
        ids[nome] = 6000 + n
        sessao.add(ComentarioChamado(
            id=ids[nome], chamado_id=chamado_id, usuario_id=autor, comentario=f"Texto de {nome}", is_interno=interno,
        ))
    sessao.commit()
    ids["publico_do_admin_no_100"] = comentario_publico(CHAMADOS["ti_do_solicitante"])
    ids["interno_do_tecnico_no_100"] = comentario_interno(CHAMADOS["ti_do_solicitante"])
    ids["publico_do_admin_no_101"] = comentario_publico(CHAMADOS["q_atribuido"])
    ids["inexistente"] = INEXISTENTE
    return ids


# (quem, comentário, status do PUT, status do DELETE)
CASOS = [
    # Autor que vê o comentário: as regras de sempre.
    ("admin", "publico_do_admin_no_100", 200, 204),
    ("solicitante", "do_solicitante", 200, 204),
    ("tecnico_ti", "interno_do_tecnico_no_100", 200, 204),
    ("tecnico_qualidade", "do_tecnico_q_onde_atende", 200, 204),
    # Sem status: cancelado e arquivado seguem editáveis por quem os lê.
    ("outro_solicitante", "do_outro_no_cancelado", 200, 204),
    ("outro_solicitante", "do_outro_no_arquivado", 200, 204),
    ("tecnico_ti", "interno_do_tecnico_no_cancelado", 200, 204),
    # Administrador lê tudo: edita e exclui o alheio, como sempre.
    ("admin", "do_ex_responsavel", 200, 204),
    ("admin", "antigo_do_intruso", 200, 204),
    # Autor que perdeu a leitura (ou nunca a teve): 404.
    ("ex_responsavel", "do_ex_responsavel", 404, 404),
    ("intruso", "antigo_do_intruso", 404, 404),
    ("tecnico_qualidade", "do_tecnico_q_na_ti", 404, 404),
    ("tecnico_qualidade", "interno_do_tecnico_q_na_ti", 404, 404),
    # Alheio, num chamado que a pessoa lê: o 403 de autoria de sempre.
    ("solicitante", "publico_do_admin_no_100", 403, 403),
    ("tecnico_ti", "publico_do_admin_no_100", 403, 403),
    ("atendente", "publico_do_admin_no_101", 403, 403),
    # Alheio, num chamado que a pessoa não lê: 404, e não mais o 403 que dizia que ele existe.
    ("intruso", "publico_do_admin_no_100", 404, 404),
    ("tecnico_outro_setor", "publico_do_admin_no_100", 404, 404),
    ("tecnico_sem_setor", "publico_do_admin_no_100", 404, 404),
    # Interno, para quem não é da equipe: 404 mesmo lendo o chamado (como o GET).
    ("solicitante", "interno_do_tecnico_no_100", 404, 404),
    # Inexistente.
    ("solicitante", "inexistente", 404, 404),
    ("admin", "inexistente", 404, 404),
]


def _texto(sessao, comentario_id):
    sessao.expire_all()
    comentario = sessao.get(ComentarioChamado, comentario_id)
    return None if comentario is None else (comentario.comentario, comentario.is_interno)


@pytest.mark.parametrize("acao", ["PUT", "DELETE"])
@pytest.mark.parametrize("quem,nome,put,delete", CASOS)
def test_edicao_e_exclusao(cliente, sessao, como, comentarios, acao, quem, nome, put, delete):
    cid = comentarios[nome]
    antes = _texto(sessao, cid)
    url = f"{API}/comentarios/{cid}"
    if acao == "PUT":
        resposta = cliente.put(url, headers=como(quem), json={"comentario": "Texto revisado pela edição"})
        esperado = put
    else:
        resposta = cliente.delete(url, headers=como(quem))
        esperado = delete

    assert resposta.status_code == esperado, resposta.text
    if esperado == 200:
        assert _texto(sessao, cid) == ("Texto revisado pela edição", antes[1])
    elif esperado == 204:
        assert _texto(sessao, cid) is None
    else:
        assert _texto(sessao, cid) == antes
        corpo = resposta.json()
        assert set(corpo) == {"detail"}
        if esperado == 404:
            assert corpo == NAO_ENCONTRADO


def test_recusa_de_quem_nao_ve_e_igual_a_de_inexistente(cliente, como, comentarios):
    respostas = {
        (r.status_code, r.text)
        for cid in (comentarios["publico_do_admin_no_100"], comentarios["antigo_do_intruso"], INEXISTENTE)
        for r in (
            cliente.put(f"{API}/comentarios/{cid}", headers=como("intruso"), json={"comentario": "Texto qualquer aqui"}),
            cliente.delete(f"{API}/comentarios/{cid}", headers=como("intruso")),
        )
    }
    assert respostas == {(404, '{"detail":"Comentário não encontrado"}')}


def test_ex_responsavel_perde_a_edicao_quando_e_reatribuido(cliente, sessao, como, cenario_de_leitura):
    """
    O caminho real: a atendente comenta, o chamado é reatribuído, e o
    comentário dela fica onde está, sem que ela possa mais mexer nele.

    A atendente tem perfil comum e é a responsável do q_atribuido no cenário
    por gravação direta (estado legado: desde a API-13 a API não a atribui).
    O novo responsável é o Técnico da Qualidade; até a API-12 era a eva, de
    perfil comum, que hoje a reatribuição recusa.
    """
    cid = CHAMADOS["q_atribuido"]
    atendente = como("atendente")
    criado = cliente.post(f"{API}/comentarios/", headers=atendente, json={"chamado_id": cid, "comentario": "Laudo conferido"})
    assert criado.status_code == 201
    comentario_id = criado.json()["id"]
    assert cliente.put(f"{API}/comentarios/{comentario_id}", headers=atendente, json={"comentario": "Laudo conferido ok"}).status_code == 200

    versao = cliente.get(f"{API}/chamados/{cid}", headers=como("admin")).json()["versao"]
    reatribuido = cliente.put(
        f"{API}/chamados/{cid}", headers=como("admin"),
        json={"tecnico_responsavel_id": cenario_de_leitura["tecnico_qualidade"], "versao_esperada": versao},
    )
    assert reatribuido.status_code == 200

    assert cliente.put(f"{API}/comentarios/{comentario_id}", headers=atendente, json={"comentario": "Outro texto"}).json() == NAO_ENCONTRADO
    assert cliente.delete(f"{API}/comentarios/{comentario_id}", headers=atendente).status_code == 404
    assert _texto(sessao, comentario_id) == ("Laudo conferido ok", False)
    # Quem atende agora lê o comentário; não o edita, porque não é dele.
    nova = como("tecnico_qualidade")
    assert cliente.get(f"{API}/comentarios/{comentario_id}", headers=nova).status_code == 200
    assert cliente.put(f"{API}/comentarios/{comentario_id}", headers=nova, json={"comentario": "Outro texto"}).status_code == 403


class TestRegrasDeSempre:
    def test_usuario_nao_marca_o_proprio_como_interno(self, cliente, como, comentarios):
        resposta = cliente.put(
            f"{API}/comentarios/{comentarios['do_solicitante']}", headers=como("solicitante"),
            json={"comentario": "Agora seria interno", "is_interno": True},
        )
        assert resposta.status_code == 403
        assert resposta.json() == {"detail": "Apenas administrador ou a equipe do setor do chamado pode marcar comentário como interno"}

    def test_tecnico_marca_o_proprio_como_interno(self, cliente, como, comentarios):
        resposta = cliente.put(
            f"{API}/comentarios/{comentarios['interno_do_tecnico_no_cancelado']}", headers=como("tecnico_ti"),
            json={"comentario": "Segue interno", "is_interno": True},
        )
        assert resposta.status_code == 200
        assert resposta.json()["is_interno"] is True

    def test_busca_por_id_inalterada(self, cliente, como, comentarios):
        assert cliente.get(f"{API}/comentarios/{comentarios['publico_do_admin_no_100']}", headers=como("solicitante")).status_code == 200
        assert cliente.get(f"{API}/comentarios/{comentarios['interno_do_tecnico_no_100']}", headers=como("solicitante")).json() == NAO_ENCONTRADO
        assert cliente.get(f"{API}/comentarios/{comentarios['publico_do_admin_no_100']}", headers=como("intruso")).json() == NAO_ENCONTRADO
