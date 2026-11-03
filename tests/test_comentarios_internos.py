"""
Comentário interno só para administrador e técnico da TI (API-8).

Até a API-7 bastava o perfil de equipe: o técnico da Qualidade, o de outro
setor e o sem setor viam e criavam comentário interno em todo chamado que
liam pelo vínculo — que abriram ou atendem. Agora são duas perguntas, as duas
exigidas: ler o chamado (API-5/API-6) e poder o interno
(`pode_acessar_comentario_interno`).

A matriz é configuração × perfil × chamado. A leitura do chamado vem da
própria API (`GET /chamados/{id}`): o que se prova aqui não é quem lê — isso
é da API-5 —, é que o interno só aparece quando as duas respostas são sim, e
que para o resto o chamado continua com os comentários públicos, sem erro e
sem sinal do interno. `VINCULOS`, escrito à mão, garante que cada perfil lê
de fato os chamados que o vínculo lhe dá: sem isso a matriz passaria vazia.

A criação segue a mesma regra: 404 de chamado inexistente para quem não lê o
chamado, antes de olhar o tipo; 403 para o interno de quem lê mas não pode;
e a recusa não grava nada nem chama ninguém.
"""

import pytest
from sqlalchemy import func

from app.api.endpoints.comentarios import CRIAR_INTERNO_NEGADO
from app.models import Chamado, Role, Usuario
from app.models.comentario import ComentarioChamado
from app.models.evento_setor import EventoDeSetor
from app.models.historico import HistoricoChamado
from leitura_cenario import (  # noqa: F401
    CHAMADOS,
    ROLE_DE,
    cenario_de_leitura,
    comentario_interno,
    comentario_publico,
)
from test_administracao_equipe_ti import CONFIGURACOES, configurar, saidas  # noqa: F401

API = "/api/v1"
INEXISTENTE = 777_777
COMENTARIO_NAO_ENCONTRADO = {"detail": "Comentário não encontrado"}
CHAMADO_NAO_ENCONTRADO = {"detail": "Chamado não encontrado"}
# O texto de todo comentário interno do cenário: o que não pode vazar.
MARCA_DO_INTERNO = "Comentário interno"

PERFIL_DESCONHECIDO = 60
CONTA_DE_SERVICO_TI = 61

# Chamados novos, onde o vínculo dá leitura a quem o perfil não dá.
VINCULADOS = {
    # (setor de destino, solicitante, responsável)
    "q_do_tecnico_q": ("QUALIDADE", "tecnico_qualidade", "atendente"),
    "q_do_tecnico_ti": ("QUALIDADE", "tecnico_ti", "atendente"),
    "ti_do_tecnico_outro": ("TI", "tecnico_outro_setor", None),
    "q_com_tecnico_outro": ("QUALIDADE", "outro_solicitante", "tecnico_outro_setor"),
    "ti_do_tecnico_sem_setor": ("TI", "tecnico_sem_setor", None),
    "ti_com_tecnico_sem_setor": ("TI", "outro_solicitante", "tecnico_sem_setor"),
    "ti_do_perfil_desconhecido": ("TI", "perfil_desconhecido", None),
    "ti_da_conta_de_servico_ti": ("TI", "conta_de_servico_ti", None),
}
TODOS_OS_CHAMADOS = {**CHAMADOS, **{nome: 110 + n for n, nome in enumerate(VINCULADOS)}}

PERFIS = [
    "admin",
    "admin_da_qualidade",
    "tecnico_ti",
    "conta_de_servico_ti",
    "tecnico_qualidade",
    "tecnico_outro_setor",
    "tecnico_sem_setor",
    "solicitante",
    "atendente",
    "ex_responsavel",
    "outro_solicitante",
    "intruso",
    "perfil_desconhecido",
    "conta_de_servico",
    "usuario_sem_setor",
]
ADMINISTRADORES = {"admin", "admin_da_qualidade"}
# API-10 (C1): a conta de serviço técnica da TI saiu daqui — não integra a equipe.
TECNICOS_DA_TI = {"tecnico_ti"}

# Os chamados que cada perfil lê só pelo vínculo — em qualquer configuração.
VINCULOS = {
    "tecnico_ti": {"q_do_tecnico_ti"},
    "conta_de_servico_ti": {"ti_da_conta_de_servico_ti"},
    "tecnico_qualidade": {"ti_com_tecnico_da_q", "q_do_tecnico_q"},
    "tecnico_outro_setor": {"ti_do_tecnico_outro", "q_com_tecnico_outro"},
    "tecnico_sem_setor": {"ti_do_tecnico_sem_setor", "ti_com_tecnico_sem_setor"},
    "solicitante": {"ti_do_solicitante", "q_atribuido"},
    "atendente": {"q_atribuido", "q_reatribuido", "q_do_tecnico_q", "q_do_tecnico_ti"},
    "outro_solicitante": {
        "ti_arquivado", "q_reatribuido", "ti_cancelado", "ti_com_tecnico_da_q", "ti_sem_responsavel",
        "q_com_tecnico_outro", "ti_com_tecnico_sem_setor",
    },
    "perfil_desconhecido": {"ti_do_perfil_desconhecido"},
}
SEM_LEITURA = {"ex_responsavel", "intruso", "conta_de_servico", "usuario_sem_setor"}


def pode_o_interno(quem, configuracao):
    """A regra aprovada, escrita à mão."""
    if quem in ADMINISTRADORES:
        return True
    return quem in TECNICOS_DA_TI and CONFIGURACOES[configuracao][1]


@pytest.fixture
def internos(cenario_de_leitura, sessao):
    """O cenário de leitura, mais as contas e os chamados de vínculo."""
    d = cenario_de_leitura
    sessao.add(Role(id=4, nome="Auditor"))
    sessao.flush()
    sessao.add_all([
        Usuario(id=PERFIL_DESCONHECIDO, nome="auditor.ti", role_id=4, setor_id=1, ativo=True),
        Usuario(
            id=CONTA_DE_SERVICO_TI, nome="painel.ti", role_id=2, setor_id=1, ativo=True, conta_de_servico=True,
        ),
    ])
    sessao.flush()
    contas = {**d, "perfil_desconhecido": PERFIL_DESCONHECIDO, "conta_de_servico_ti": CONTA_DE_SERVICO_TI}

    for nome, (setor, solicitante, responsavel) in VINCULADOS.items():
        cid = TODOS_OS_CHAMADOS[nome]
        sessao.add(Chamado(
            id=cid,
            protocolo=f"CH-TESTE-{cid}",
            solicitante_id=contas[solicitante],
            categoria_id=1 if setor == "TI" else None,
            titulo=f"Chamado {nome}",
            descricao=f"Descrição do chamado {nome}",
            status="Aberto",
            prioridade="Média",
            setor_destino=setor,
            tecnico_responsavel_id=contas[responsavel] if responsavel else None,
        ))
    sessao.flush()
    for nome in VINCULADOS:
        cid = TODOS_OS_CHAMADOS[nome]
        sessao.add_all([
            ComentarioChamado(
                id=comentario_publico(cid), chamado_id=cid, usuario_id=d["admin_id"],
                comentario=f"Comentário público do {cid}", is_interno=False,
            ),
            ComentarioChamado(
                id=comentario_interno(cid), chamado_id=cid, usuario_id=d["tecnico_id"],
                comentario=f"{MARCA_DO_INTERNO} do {cid}", is_interno=True,
            ),
        ])
    sessao.commit()
    return contas


@pytest.fixture
def como(autenticar, internos):
    papeis = {**ROLE_DE, "perfil_desconhecido": "Auditor", "conta_de_servico_ti": "Tecnico"}

    def _como(quem):
        return autenticar(internos[quem], quem, papeis.get(quem, "Usuario"))

    return _como


def _foto(sessao):
    """Tudo que um comentário recusado não pode ter mudado."""
    sessao.expire_all()
    return {
        "comentarios": sorted(
            (c.id, c.chamado_id, c.usuario_id, c.comentario, c.is_interno) for c in sessao.query(ComentarioChamado)
        ),
        "historico": sessao.query(func.count(HistoricoChamado.id)).scalar(),
        "eventos": sessao.query(func.count(EventoDeSetor.id)).scalar(),
        "chamados": sorted((c.id, c.versao, c.updated_at, c.status) for c in sessao.query(Chamado)),
    }


@pytest.mark.parametrize("quem", PERFIS)
@pytest.mark.parametrize("configuracao", CONFIGURACOES)
def test_leitura_por_configuracao_e_perfil(cliente, como, configurar, configuracao, quem):
    configurar(configuracao)
    h = como(quem)
    pode = pode_o_interno(quem, configuracao)
    lista_inexistente = cliente.get(f"{API}/comentarios/chamado/{INEXISTENTE}", headers=h)
    id_inexistente = cliente.get(f"{API}/comentarios/{INEXISTENTE}", headers=h)
    assert id_inexistente.json() == COMENTARIO_NAO_ENCONTRADO

    lidos = set()
    for nome, cid in TODOS_OS_CHAMADOS.items():
        leitura = cliente.get(f"{API}/chamados/{cid}", headers=h)
        lista = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=h)
        publico = cliente.get(f"{API}/comentarios/{comentario_publico(cid)}", headers=h)
        interno = cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h)

        if leitura.status_code == 200:
            lidos.add(nome)
            esperados = {comentario_publico(cid)} | ({comentario_interno(cid)} if pode else set())
            assert lista.status_code == 200, nome
            assert {c["id"] for c in lista.json()} == esperados, nome
            assert publico.status_code == 200, nome
            if pode:
                assert interno.status_code == 200, nome
                assert interno.json()["is_interno"] is True
            else:
                # Igual a um id que não existe: nem o status, nem o corpo dizem que há interno.
                assert (interno.status_code, interno.json()) == (404, id_inexistente.json()), nome
                assert MARCA_DO_INTERNO not in lista.text, nome
        else:
            assert leitura.status_code == 404, nome
            for resposta, modelo in ((lista, lista_inexistente), (publico, id_inexistente), (interno, id_inexistente)):
                assert (resposta.status_code, resposta.json()) == (404, modelo.json()), nome

    # Sem isto a matriz passaria sem ler nada.
    assert VINCULOS.get(quem, set()) <= lidos
    if quem in ADMINISTRADORES:
        assert lidos == set(TODOS_OS_CHAMADOS)
    if quem in SEM_LEITURA:
        assert lidos == set()


# O chamado em que cada perfil comenta: um que ele lê pelo vínculo, em
# qualquer configuração; e, para quem não lê nenhum, um que ele não lê.
ALVO = {
    "admin": "q_atribuido",
    "admin_da_qualidade": "ti_do_solicitante",
    "tecnico_ti": "q_do_tecnico_ti",
    "conta_de_servico_ti": "ti_da_conta_de_servico_ti",
    "tecnico_qualidade": "q_do_tecnico_q",
    "tecnico_outro_setor": "q_com_tecnico_outro",
    "tecnico_sem_setor": "ti_com_tecnico_sem_setor",
    "solicitante": "ti_do_solicitante",
    "atendente": "q_atribuido",
    "ex_responsavel": "q_reatribuido",
    "outro_solicitante": "ti_cancelado",
    "intruso": "ti_do_solicitante",
    "perfil_desconhecido": "ti_do_perfil_desconhecido",
    "conta_de_servico": "q_atribuido",
    "usuario_sem_setor": "ti_do_solicitante",
}


@pytest.mark.parametrize("interno", [False, True], ids=["publico", "interno"])
@pytest.mark.parametrize("quem", PERFIS)
@pytest.mark.parametrize("configuracao", ["valida", "ausente", "invalida"])
def test_criacao(cliente, sessao, como, configurar, saidas, configuracao, quem, interno):
    configurar(configuracao)
    cid = TODOS_OS_CHAMADOS[ALVO[quem]]
    antes = _foto(sessao)
    resposta = cliente.post(
        f"{API}/comentarios/", headers=como(quem),
        json={"chamado_id": cid, "comentario": "Escrito na matriz", "is_interno": interno},
    )

    if quem in SEM_LEITURA:
        # O chamado vem antes do tipo: quem não o lê recebe o 404 de um que não existe.
        inexistente = cliente.post(
            f"{API}/comentarios/", headers=como(quem),
            json={"chamado_id": INEXISTENTE, "comentario": "Escrito na matriz", "is_interno": interno},
        )
        assert (resposta.status_code, resposta.json()) == (404, CHAMADO_NAO_ENCONTRADO)
        assert inexistente.json() == CHAMADO_NAO_ENCONTRADO
    elif interno and not pode_o_interno(quem, configuracao):
        assert (resposta.status_code, resposta.json()) == (403, {"detail": CRIAR_INTERNO_NEGADO})
    else:
        assert resposta.status_code == 201, resposta.text
        corpo = resposta.json()
        assert (corpo["chamado_id"], corpo["is_interno"], corpo["usuario_id"]) == (cid, interno, como_id(sessao, quem))
        assert saidas == []
        return

    assert _foto(sessao) == antes
    assert saidas == []


def como_id(sessao, quem):
    """O id da conta pelo nome, para conferir o autor gravado."""
    nomes = {
        "admin": "admin.teste", "admin_da_qualidade": "aaron.qualidade", "tecnico_ti": "tecnico.teste",
        "conta_de_servico_ti": "painel.ti", "tecnico_qualidade": "bruno.qualidade",
        "tecnico_outro_setor": "tecnico.comercial", "tecnico_sem_setor": "tecnico.sem.setor",
        "solicitante": "usuario.teste", "atendente": "ana.qualidade", "outro_solicitante": "outro.solicitante",
        "perfil_desconhecido": "auditor.ti",
    }
    return sessao.query(Usuario.id).filter(Usuario.nome == nomes[quem]).scalar()


class TestCasosNomeados:
    """Os casos da especificação que a matriz cobre, ditos por extenso."""

    def test_tecnico_da_qualidade_responsavel_nao_ve_o_interno(self, cliente, como):
        cid = CHAMADOS["ti_com_tecnico_da_q"]
        h = como("tecnico_qualidade")
        assert cliente.get(f"{API}/chamados/{cid}", headers=h).status_code == 200
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).json() == COMENTARIO_NAO_ENCONTRADO
        assert [c["id"] for c in cliente.get(f"{API}/comentarios/chamado/{cid}", headers=h).json()] == [
            comentario_publico(cid)
        ]

    def test_tecnico_da_qualidade_nao_ve_o_interno_nem_nos_chamados_da_qualidade(self, cliente, como):
        """Lê pelo perfil todos os da Qualidade, e nenhum interno deles."""
        h = como("tecnico_qualidade")
        for nome in ("q_atribuido", "q_reatribuido", "q_com_tecnico_outro"):
            cid = TODOS_OS_CHAMADOS[nome]
            lista = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=h)
            assert lista.status_code == 200
            assert [c["id"] for c in lista.json()] == [comentario_publico(cid)]

    def test_responsavel_da_qualidade_de_perfil_usuario_nao_ve_o_interno(self, cliente, como):
        cid = CHAMADOS["q_atribuido"]
        h = como("atendente")
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 404
        r = cliente.post(
            f"{API}/comentarios/", headers=h, json={"chamado_id": cid, "comentario": "Interno", "is_interno": True},
        )
        assert r.status_code == 403

    def test_solicitante_segue_com_os_publicos(self, cliente, como):
        cid = CHAMADOS["ti_do_solicitante"]
        lista = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=como("solicitante"))
        assert [c["id"] for c in lista.json()] == [comentario_publico(cid)]

    def test_tecnico_sem_permissao_segue_comentando_publico(self, cliente, sessao, como):
        for quem in ("tecnico_qualidade", "tecnico_outro_setor", "tecnico_sem_setor"):
            cid = TODOS_OS_CHAMADOS[ALVO[quem]]
            r = cliente.post(
                f"{API}/comentarios/", headers=como(quem), json={"chamado_id": cid, "comentario": "Público"},
            )
            assert r.status_code == 201, quem
            assert r.json()["is_interno"] is False

    def test_lista_com_so_internos_vira_lista_vazia_e_nao_erro(self, cliente, sessao, como):
        cid = TODOS_OS_CHAMADOS["q_do_tecnico_q"]
        sessao.delete(sessao.get(ComentarioChamado, comentario_publico(cid)))
        sessao.commit()
        r = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=como("tecnico_qualidade"))
        assert (r.status_code, r.json()) == (200, [])

    def test_ordem_e_formato_da_lista_nao_mudam(self, cliente, sessao, como):
        """A lista do técnico da TI é a de antes; a do resto, a mesma sem os internos."""
        cid = CHAMADOS["q_atribuido"]
        sessao.add(ComentarioChamado(
            id=9000, chamado_id=cid, usuario_id=como_id(sessao, "solicitante"), comentario="Outro público",
        ))
        sessao.commit()
        completa = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=como("tecnico_ti")).json()
        restrita = cliente.get(f"{API}/comentarios/chamado/{cid}", headers=como("tecnico_qualidade")).json()
        assert restrita == [c for c in completa if not c["is_interno"]]
        assert set(restrita[0]) == {"id", "chamado_id", "usuario_id", "comentario", "is_interno", "created_at", "updated_at"}

    def test_conta_de_servico_comum_nao_ganha_interno(self, cliente, como):
        """A conta de serviço da Qualidade (perfil Usuário) não vira equipe por classificação errada."""
        h = como("conta_de_servico")
        cid = CHAMADOS["q_atribuido"]
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 404

    def test_conta_de_servico_tecnico_da_ti_nao_ve_o_interno(self, cliente, como):
        """API-10 (C1): fecha o risco residual da API-8. Lê o chamado, não o interno."""
        cid = CHAMADOS["q_atribuido"]
        h = como("conta_de_servico_ti")
        assert cliente.get(f"{API}/chamados/{cid}", headers=h).status_code == 200
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 404

    def test_perfil_desconhecido_num_setor_da_ti_nao_ve_o_interno(self, cliente, como):
        cid = TODOS_OS_CHAMADOS["ti_do_perfil_desconhecido"]
        h = como("perfil_desconhecido")
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 404

    def test_administrador_fora_da_ti_ve_e_cria_interno(self, cliente, como):
        cid = CHAMADOS["ti_do_solicitante"]
        h = como("admin_da_qualidade")
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 200
        r = cliente.post(
            f"{API}/comentarios/", headers=h, json={"chamado_id": cid, "comentario": "Interno", "is_interno": True},
        )
        assert r.status_code == 201

    def test_mudanca_de_setor_vale_no_proximo_pedido(self, cliente, sessao, como, internos):
        cid = CHAMADOS["q_atribuido"]
        h = como("tecnico_ti")
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 200
        sessao.get(Usuario, internos["tecnico_ti"]).setor_id = 4
        sessao.commit()
        assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}", headers=h).status_code == 404


@pytest.mark.parametrize("quem", sorted(set(PERFIS) - ADMINISTRADORES - TECNICOS_DA_TI))
def test_o_interno_nao_vaza_por_outra_resposta(cliente, como, quem):
    """Nenhuma rota de chamado ou de histórico carrega o texto de comentário."""
    h = como(quem)
    respostas = [cliente.get(f"{API}/chamados/", headers=h)]
    for cid in TODOS_OS_CHAMADOS.values():
        respostas += [
            cliente.get(f"{API}/chamados/{cid}", headers=h),
            cliente.get(f"{API}/historico/chamado/{cid}", headers=h),
            cliente.get(f"{API}/comentarios/chamado/{cid}", headers=h),
        ]
    for resposta in respostas:
        assert MARCA_DO_INTERNO not in resposta.text, resposta.url


def test_sem_token_continua_401(cliente, internos):
    cid = CHAMADOS["q_atribuido"]
    assert cliente.get(f"{API}/comentarios/chamado/{cid}").status_code == 401
    assert cliente.get(f"{API}/comentarios/{comentario_interno(cid)}").status_code == 401
    assert cliente.post(
        f"{API}/comentarios/", json={"chamado_id": cid, "comentario": "x", "is_interno": True},
    ).status_code == 401
