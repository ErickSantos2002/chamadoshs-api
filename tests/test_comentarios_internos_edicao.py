"""
Editar e excluir comentário interno (API-8, refeita na API-13).

A edição e a exclusão já exigiam ver o comentário hoje (API-6, D11). Ver o
interno é ser administrador humano ou da equipe do setor de destino do
chamado (API-13): quem não é — o técnico de outro setor, o sem setor, o
usuário, o técnico da TI sem `SETORES_TI_IDS` válida, ou o técnico de uma
equipe num chamado do outro setor que ele lê pelo vínculo — não edita nem
exclui o interno que ele mesmo escreveu, e recebe o 404 de um id que não
existe. O comentário público de quem lê o chamado segue como antes. Até a
API-12 a regra era só do perfil, e o técnico da Qualidade estava entre os que
não podiam.

A edição também não muda a visibilidade por fora da regra: só quem pode o
interno torna interno um comentário público, e quem não pode nem chega ao
interno para torná-lo público. Autoria e poderes do administrador: os de
sempre.
"""

import pytest

from app.api.endpoints.comentarios import MARCAR_INTERNO_NEGADO
from app.models import Chamado
from app.models.comentario import ComentarioChamado
from leitura_cenario import CHAMADOS, comentario_interno  # noqa: F401
from test_comentarios_internos import (  # noqa: F401
    ALVO,
    API,
    COMENTARIO_NAO_ENCONTRADO,
    INEXISTENTE,
    PERFIS,
    SEM_LEITURA,
    TODOS_OS_CHAMADOS,
    _foto,
    cenario_de_leitura,
    como,
    configurar,
    internos,
    pode_o_interno,
    saidas,
)

COM_LEITURA = [quem for quem in PERFIS if quem not in SEM_LEITURA]
TIPOS = {"publico": False, "interno": True}

# O `ALVO` do técnico da TI é um chamado da Qualidade que ele lê pelo vínculo,
# e desde a API-13 o interno dele ali nunca é dele. Para que a matriz continue
# provando o interno do técnico da TI — e a perda dele sem lista válida —, o
# comentário dele vai num chamado da TI que ele mesmo abriu: lê pelo vínculo
# em qualquer configuração, e o interno depende só da lista.
TI_DO_TECNICO_TI = 130
ALVO_DA_EDICAO = {**ALVO, "tecnico_ti": "ti_do_tecnico_ti"}
CHAMADOS_DA_EDICAO = {**TODOS_OS_CHAMADOS, "ti_do_tecnico_ti": TI_DO_TECNICO_TI}


@pytest.fixture
def proprios(internos, sessao):
    """Um comentário público e um interno de cada perfil, no chamado do `ALVO_DA_EDICAO` dele."""
    sessao.add(Chamado(
        id=TI_DO_TECNICO_TI, protocolo=f"CH-TESTE-{TI_DO_TECNICO_TI}", solicitante_id=internos["tecnico_ti"],
        categoria_id=1, titulo="Chamado ti_do_tecnico_ti", descricao="Descrição do chamado ti_do_tecnico_ti",
        status="Aberto", prioridade="Média", setor_destino="TI",
    ))
    sessao.flush()
    ids = {}
    for n, quem in enumerate(PERFIS):
        for m, (tipo, interno) in enumerate(TIPOS.items()):
            cid = 8000 + 2 * n + m
            sessao.add(ComentarioChamado(
                id=cid, chamado_id=CHAMADOS_DA_EDICAO[ALVO_DA_EDICAO[quem]], usuario_id=internos[quem],
                comentario=f"Escrito por {quem}", is_interno=interno,
            ))
            ids[(quem, tipo)] = cid
    sessao.commit()
    return ids


def _estado(sessao, comentario_id):
    sessao.expire_all()
    comentario = sessao.get(ComentarioChamado, comentario_id)
    return None if comentario is None else (comentario.comentario, comentario.is_interno)


def _agir(cliente, como, quem, acao, comentario_id, corpo=None):
    url = f"{API}/comentarios/{comentario_id}"
    if acao == "PUT":
        return cliente.put(url, headers=como(quem), json=corpo or {"comentario": "Revisado na matriz"})
    return cliente.delete(url, headers=como(quem))


@pytest.mark.parametrize("acao", ["PUT", "DELETE"])
@pytest.mark.parametrize("tipo", TIPOS)
@pytest.mark.parametrize("quem", COM_LEITURA)
@pytest.mark.parametrize("configuracao", ["valida", "ausente", "invalida"])
def test_o_proprio_comentario(cliente, sessao, como, configurar, saidas, proprios, configuracao, quem, tipo, acao):
    """O autor que lê o chamado: o público segue dele; o interno, só se pode o interno."""
    configurar(configuracao)
    cid = proprios[(quem, tipo)]
    antes = _foto(sessao)
    resposta = _agir(cliente, como, quem, acao, cid)

    if tipo == "publico" or pode_o_interno(quem, configuracao, ALVO_DA_EDICAO[quem]):
        assert resposta.status_code == (200 if acao == "PUT" else 204), resposta.text
        assert _estado(sessao, cid) == (None if acao == "DELETE" else ("Revisado na matriz", TIPOS[tipo]))
    else:
        inexistente = _agir(cliente, como, quem, acao, INEXISTENTE)
        assert (resposta.status_code, resposta.json()) == (404, COMENTARIO_NAO_ENCONTRADO)
        assert (resposta.status_code, resposta.json()) == (inexistente.status_code, inexistente.json())
        assert _foto(sessao) == antes
    assert saidas == []


@pytest.mark.parametrize("acao", ["PUT", "DELETE"])
@pytest.mark.parametrize("tipo", TIPOS)
@pytest.mark.parametrize("quem", sorted(SEM_LEITURA))
def test_autor_sem_acesso_ao_chamado(cliente, sessao, como, proprios, quem, tipo, acao):
    """Comentário de antes, num chamado que o autor não lê: 404 nos dois tipos."""
    cid = proprios[(quem, tipo)]
    antes = _foto(sessao)
    resposta = _agir(cliente, como, quem, acao, cid)
    assert (resposta.status_code, resposta.json()) == (404, COMENTARIO_NAO_ENCONTRADO)
    assert _foto(sessao) == antes


# Desde a API-13 o técnico da Qualidade sai daqui: o comentário dele é num
# chamado da Qualidade, e ali o interno é dele.
SEM_O_INTERNO = ["tecnico_outro_setor", "tecnico_sem_setor", "solicitante", "atendente", "perfil_desconhecido"]


class TestVisibilidade:
    @pytest.mark.parametrize("quem", SEM_O_INTERNO)
    def test_quem_nao_pode_nao_torna_interno_o_proprio_publico(self, cliente, sessao, como, proprios, quem):
        cid = proprios[(quem, "publico")]
        antes = _foto(sessao)
        r = _agir(cliente, como, quem, "PUT", cid, {"comentario": "Agora interno", "is_interno": True})
        assert (r.status_code, r.json()) == (403, {"detail": MARCAR_INTERNO_NEGADO})
        assert _foto(sessao) == antes

    @pytest.mark.parametrize("quem", SEM_O_INTERNO)
    def test_quem_nao_pode_nao_torna_publico_o_proprio_interno(self, cliente, sessao, como, proprios, quem):
        cid = proprios[(quem, "interno")]
        antes = _foto(sessao)
        r = _agir(cliente, como, quem, "PUT", cid, {"is_interno": False})
        assert (r.status_code, r.json()) == (404, COMENTARIO_NAO_ENCONTRADO)
        assert _foto(sessao) == antes

    @pytest.mark.parametrize("quem", SEM_O_INTERNO)
    def test_publico_continua_publico_para_quem_nao_pode(self, cliente, sessao, como, proprios, quem):
        cid = proprios[(quem, "publico")]
        r = _agir(cliente, como, quem, "PUT", cid, {"comentario": "Revisado", "is_interno": False})
        assert r.status_code == 200
        assert _estado(sessao, cid) == ("Revisado", False)

    def test_tecnico_da_ti_sem_lista_valida_perde_o_poder_de_marcar(self, cliente, sessao, como, configurar, proprios):
        configurar("ausente")
        cid = proprios[("tecnico_ti", "publico")]
        r = _agir(cliente, como, "tecnico_ti", "PUT", cid, {"is_interno": True})
        assert (r.status_code, r.json()) == (403, {"detail": MARCAR_INTERNO_NEGADO})
        assert _estado(sessao, cid) == ("Escrito por tecnico_ti", False)

    @pytest.mark.parametrize("de,para", [(False, True), (True, False)], ids=["publico_para_interno", "interno_para_publico"])
    @pytest.mark.parametrize("quem", ["tecnico_ti", "tecnico_qualidade", "admin", "admin_da_qualidade"])
    def test_quem_pode_muda_a_visibilidade_do_proprio(self, cliente, sessao, como, proprios, quem, de, para):
        cid = proprios[(quem, "interno" if de else "publico")]
        r = _agir(cliente, como, quem, "PUT", cid, {"is_interno": para})
        assert r.status_code == 200
        assert r.json()["is_interno"] is para
        assert _estado(sessao, cid) == (f"Escrito por {quem}", para)

    @pytest.mark.parametrize("tipo", TIPOS)
    def test_is_interno_nulo_nao_muda_a_visibilidade(self, cliente, sessao, como, proprios, tipo):
        """O NULL não chega ao banco: antes gravava e a resposta quebrava com 500."""
        cid = proprios[("tecnico_ti", tipo)]
        r = _agir(cliente, como, "tecnico_ti", "PUT", cid, {"comentario": "Revisado", "is_interno": None})
        assert r.status_code == 200, r.text
        assert r.json()["is_interno"] is TIPOS[tipo]
        assert _estado(sessao, cid) == ("Revisado", TIPOS[tipo])

    def test_interno_nulo_no_banco_conta_como_interno(self, cliente, sessao, como, proprios):
        """Um NULL de antes não vira público na busca por id: fecha, como a listagem."""
        cid = proprios[("tecnico_ti", "interno")]
        sessao.get(ComentarioChamado, cid).is_interno = None
        sessao.commit()
        r = cliente.get(f"{API}/comentarios/{cid}", headers=como("atendente"))
        assert (r.status_code, r.json()) == (404, COMENTARIO_NAO_ENCONTRADO)


class TestPoderesDeSempre:
    @pytest.mark.parametrize("acao", ["PUT", "DELETE"])
    @pytest.mark.parametrize("configuracao", ["valida", "ausente"])
    @pytest.mark.parametrize("quem", ["admin", "admin_da_qualidade"])
    def test_administrador_edita_e_exclui_o_interno_alheio(self, cliente, sessao, como, configurar, quem, configuracao, acao):
        configurar(configuracao)
        cid = comentario_interno(CHAMADOS["q_atribuido"])  # do técnico da TI
        r = _agir(cliente, como, quem, acao, cid)
        assert r.status_code == (200 if acao == "PUT" else 204), r.text

    @pytest.mark.parametrize("acao", ["PUT", "DELETE"])
    @pytest.mark.parametrize(
        "quem,autor",
        # O interno de cada administrador está num chamado de um setor: o do
        # `admin_da_qualidade`, na TI; o do `admin`, na Qualidade (API-13).
        [("tecnico_ti", "admin_da_qualidade"), ("tecnico_qualidade", "admin")],
    )
    def test_tecnico_da_equipe_nao_mexe_no_interno_alheio(self, cliente, sessao, como, proprios, quem, autor, acao):
        """Ver o interno não dá autoria: o 403 de sempre."""
        cid = proprios[(autor, "interno")]
        assert cliente.get(f"{API}/comentarios/{cid}", headers=como(quem)).status_code == 200
        antes = _foto(sessao)
        r = _agir(cliente, como, quem, acao, cid)
        assert r.status_code == 403
        assert r.json()["detail"].startswith("Só é possível")
        assert _foto(sessao) == antes

    def test_autor_que_perde_a_permissao_por_troca_de_setor(self, cliente, sessao, como, internos, proprios):
        """Vai para a Qualidade: continua lendo o chamado da TI que abriu, e o interno dele ali é da TI."""
        from app.models import Usuario

        cid = proprios[("tecnico_ti", "interno")]
        sessao.get(Usuario, internos["tecnico_ti"]).setor_id = 2
        sessao.commit()
        for acao in ("PUT", "DELETE"):
            r = _agir(cliente, como, "tecnico_ti", acao, cid)
            assert (r.status_code, r.json()) == (404, COMENTARIO_NAO_ENCONTRADO)
        assert _estado(sessao, cid) == ("Escrito por tecnico_ti", True)


def test_sem_token_continua_401(cliente, proprios):
    cid = proprios[("tecnico_ti", "interno")]
    assert cliente.put(f"{API}/comentarios/{cid}", json={"comentario": "x"}).status_code == 401
    assert cliente.delete(f"{API}/comentarios/{cid}").status_code == 401
