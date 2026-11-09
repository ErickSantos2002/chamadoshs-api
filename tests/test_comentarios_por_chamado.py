"""
Comentários por chamado (API-5, correção do O-1).

Ler os comentários de um chamado — pela lista ou pelo id de um deles — exige
poder ler o chamado, e a recusa é o mesmo 404 de quando ele não existe (D6).
Por cima disso, comentário interno só para o administrador humano e para a
equipe do setor de destino do chamado (API-13; na API-8, administrador e
técnico da TI em tudo o que liam), e a responsável de perfil Usuário não o
vê (D3).

Comentar também exige poder ler o chamado, e o chamado tem de existir. Isso
só fecha: antes qualquer conta comentava em qualquer chamado, e nenhum perfil
ganha aqui um comentário que não tinha.
"""

import pytest

from app.models.comentario import ComentarioChamado
from leitura_cenario import (  # noqa: F401
    CHAMADOS,
    EX_RESPONSAVEL,
    LEITURA_ESPERADA,
    VEEM_INTERNO,
    cenario_de_leitura,
    comentario_interno,
    comentario_publico,
)
from test_leitura_por_chamado import API, INEXISTENTE, PARES, como  # noqa: F401


@pytest.mark.parametrize("quem,nome", PARES)
def test_leitura_dos_comentarios(cliente, como, quem, nome):
    h = como(quem)
    cid = CHAMADOS[nome]
    lista = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=h)
    publico = cliente.get(f"{API}/comentarios/{comentario_publico(cid)}", headers=h)
    interno = cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h)

    if nome in LEITURA_ESPERADA[quem]:
        esperados = {comentario_publico(cid)}
        if nome in VEEM_INTERNO.get(quem, set()):
            esperados.add(comentario_interno(cid))
            assert interno.status_code == 200
        else:
            assert interno.status_code == 404
        assert lista.status_code == 200
        assert {c["id"] for c in lista.json()} == esperados
        assert publico.status_code == 200
    else:
        lista_inexistente = cliente.get(f"{API}/comentarios/chamado/{INEXISTENTE}", headers=h)
        id_inexistente = cliente.get(f"{API}/comentarios/{INEXISTENTE}", headers=h)
        for resposta, modelo in ((lista, lista_inexistente), (publico, id_inexistente), (interno, id_inexistente)):
            assert resposta.status_code == 404, resposta.text
            assert resposta.json() == modelo.json()


def test_tecnico_da_qualidade_nao_le_interno_da_ti(cliente, como):
    """D2: o perfil de equipe não leva aos internos de um chamado da TI que ele não lê."""
    h = como("tecnico_qualidade")
    cid = CHAMADOS["ti_do_solicitante"]
    assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 404
    assert cliente.get(f"{API}/comentarios/chamado/{cid}", headers=h).status_code == 404


def test_tecnico_ti_nao_le_chamado_da_qualidade(cliente, como):
    """API-13: o técnico da TI não lê a Qualidade — nem os comentários, nem o interno."""
    cid = CHAMADOS["q_atribuido"]
    h = como("tecnico_ti")
    assert cliente.get(f"{API}/comentarios/chamado/{cid}", headers=h).status_code == 404
    assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 404


def test_tecnico_qualidade_le_interno_da_qualidade(cliente, como):
    """API-13: a equipe da Qualidade vê o interno dos chamados da Qualidade."""
    cid = CHAMADOS["q_atribuido"]
    r = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=como("tecnico_qualidade"))
    assert {c["id"] for c in r.json()} == {comentario_publico(cid), comentario_interno(cid)}


def test_vinculo_nao_da_o_interno_do_outro_setor(cliente, como):
    """API-13: o técnico da Qualidade responsável por um chamado da TI lê o chamado, não o interno."""
    cid = CHAMADOS["ti_com_tecnico_da_q"]
    r = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=como("tecnico_qualidade"))
    assert r.status_code == 200
    assert {c["id"] for c in r.json()} == {comentario_publico(cid)}


def test_ex_responsavel_perde_os_comentarios(cliente, como, autenticar, sessao, cenario_de_leitura):
    """D4: depois da reatribuição, nem ler nem comentar."""
    from app.models import Chamado

    cid = CHAMADOS["q_reatribuido"]
    sessao.get(Chamado, cid).tecnico_responsavel_id = EX_RESPONSAVEL
    sessao.commit()
    eva = autenticar(EX_RESPONSAVEL, "eva.qualidade", "Usuario")
    assert cliente.get(f"{API}/comentarios/chamado/{cid}", headers=eva).status_code == 200
    versao = cliente.get(f"{API}/chamados/{cid}", headers=eva).json()["versao"]

    r = cliente.put(
        f"{API}/chamados/{cid}",
        headers=como("admin"),
        json={"tecnico_responsavel_id": cenario_de_leitura["atendente"], "versao_esperada": versao},
    )
    assert r.status_code == 200, r.text

    assert cliente.get(f"{API}/comentarios/chamado/{cid}", headers=eva).status_code == 404
    assert cliente.get(f"{API}/comentarios/{comentario_publico(cid)}", headers=eva).status_code == 404
    post = cliente.post(f"{API}/comentarios/", headers=eva, json={"chamado_id": cid, "comentario": "Ainda é meu?"})
    assert post.status_code == 404


class TestComentar:
    @pytest.mark.parametrize("quem,nome", PARES)
    def test_comenta_so_onde_le(self, cliente, como, sessao, quem, nome):
        cid = CHAMADOS[nome]
        antes = sessao.query(ComentarioChamado).filter(ComentarioChamado.chamado_id == cid).count()
        r = cliente.post(
            f"{API}/comentarios/", headers=como(quem), json={"chamado_id": cid, "comentario": "Tem novidade?"}
        )
        sessao.expire_all()
        depois = sessao.query(ComentarioChamado).filter(ComentarioChamado.chamado_id == cid).count()
        if nome in LEITURA_ESPERADA[quem]:
            assert r.status_code == 201, r.text
            assert depois == antes + 1
        else:
            assert r.status_code == 404
            assert r.json() == {"detail": "Chamado não encontrado"}
            assert depois == antes

    @pytest.mark.parametrize("quem", ["admin", "intruso"])
    def test_chamado_inexistente_nao_recebe_comentario(self, cliente, como, sessao, quem):
        r = cliente.post(
            f"{API}/comentarios/", headers=como(quem), json={"chamado_id": INEXISTENTE, "comentario": "Alô"}
        )
        assert r.status_code == 404
        assert r.json() == {"detail": "Chamado não encontrado"}
        assert sessao.query(ComentarioChamado).filter(ComentarioChamado.chamado_id == INEXISTENTE).count() == 0

    def test_interno_continua_so_da_equipe(self, cliente, como):
        """D3: a responsável de perfil Usuário lê o chamado, mas não comenta interno."""
        r = cliente.post(
            f"{API}/comentarios/",
            headers=como("atendente"),
            json={"chamado_id": CHAMADOS["q_atribuido"], "comentario": "Só para a equipe", "is_interno": True},
        )
        assert r.status_code == 403

    def test_interno_em_chamado_que_nao_le_e_404(self, cliente, como):
        """A leitura vem antes: o técnico da Qualidade nem descobre o chamado da TI."""
        r = cliente.post(
            f"{API}/comentarios/",
            headers=como("tecnico_qualidade"),
            json={"chamado_id": CHAMADOS["ti_do_solicitante"], "comentario": "Interno", "is_interno": True},
        )
        assert r.status_code == 404

    def test_equipe_continua_comentando_interno_onde_le(self, cliente, como):
        """API-13: a equipe do setor de destino; até a API-12 este era o técnico da TI na Qualidade."""
        r = cliente.post(
            f"{API}/comentarios/",
            headers=como("tecnico_qualidade"),
            json={"chamado_id": CHAMADOS["q_atribuido"], "comentario": "Visto pela Qualidade", "is_interno": True},
        )
        assert r.status_code == 201
        r = cliente.post(
            f"{API}/comentarios/",
            headers=como("tecnico_ti"),
            json={"chamado_id": CHAMADOS["ti_sem_responsavel"], "comentario": "Visto pela TI", "is_interno": True},
        )
        assert r.status_code == 201


