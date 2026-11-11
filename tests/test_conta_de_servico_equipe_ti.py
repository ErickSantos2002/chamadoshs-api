"""
Conta de serviço fora da equipe da TI (API-10, decisão C1).

Até a API-9, `integra_equipe_ti` olhava só o perfil e o setor: uma conta de
serviço com perfil Técnico num setor de `SETORES_TI_IDS` integrava a equipe, e
com isso passava em `require_equipe_ti`, via e criava comentário interno e
recebia `integra_equipe_ti: true` no `/auth/me`. A homologação FE-5 × API-9
reproduziu: comentário interno criado com 201.

Aqui, a regra escrita à mão — e não derivada do código — conferida contra as
quatro funções que dependem dela, conta × configuração. O perfil de
administrador não é assunto da C1: o administrador passa pelo perfil — e,
desde a API-11 (S3), só o humano; a conta de serviço administradora não.
O comentário interno, desde a API-13, também depende do setor de destino do
chamado: é conferido num chamado da TI e num da Qualidade.
"""

import pytest
from fastapi import HTTPException

import main
from app.api.deps import EQUIPE_TI_NEGADA, require_equipe_ti
from app.models import Chamado, Role, Usuario
from app.services.leitura_service import integra_equipe_ti, pode_acessar_comentario_interno
from app.services.responsavel_ti_service import CONTA_DE_SERVICO, motivo_de_recusa, pode_ser_novo_responsavel

SETOR_TI = 1
SETOR_QUALIDADE = 2
SETOR_OUTRO = 4

# nome: (perfil, setor, conta_de_servico, ativo)
CONTAS = {
    "admin_humano": ("Administrador", SETOR_TI, False, True),
    "tecnico_ti_humano": ("Tecnico", SETOR_TI, False, True),
    "tecnico_qualidade_humano": ("Tecnico", SETOR_QUALIDADE, False, True),
    "tecnico_outro_setor_humano": ("Tecnico", SETOR_OUTRO, False, True),
    "tecnico_sem_setor_humano": ("Tecnico", None, False, True),
    "usuario_humano": ("Usuario", SETOR_TI, False, True),
    "servico_tecnico_ti": ("Tecnico", SETOR_TI, True, True),
    "servico_tecnico_qualidade": ("Tecnico", SETOR_QUALIDADE, True, True),
    "servico_tecnico_outro_setor": ("Tecnico", SETOR_OUTRO, True, True),
    "servico_tecnico_sem_setor": ("Tecnico", None, True, True),
    "servico_usuario_ti": ("Usuario", SETOR_TI, True, True),
    "servico_admin_ti": ("Administrador", SETOR_TI, True, True),
    "tecnico_ti_desativado": ("Tecnico", SETOR_TI, False, False),
    "perfil_desconhecido_ti": ("Auditor", SETOR_TI, False, True),
}

# SETORES_TI_IDS → os setores que valem como TI (a Qualidade nunca vale).
CONFIGURACOES = {
    "valida": ("1", {SETOR_TI}),
    "ausente": (None, set()),
    "vazia": ("", set()),
    "invalida": ("1,x", set()),
    "duplicada": ("1,1", {SETOR_TI}),
    "com_qualidade": ("1,2", {SETOR_TI}),
    "com_setor_inexistente": ("1,999", {SETOR_TI, 999}),
}

EQUIPE = {"Administrador", "Tecnico"}
SETORES_DESTINO = ["TI", "QUALIDADE"]
_PADRAO = object()


def _chamado(setor_destino):
    return Chamado(id=1, setor_destino=setor_destino, solicitante_id=99, tecnico_responsavel_id=None)


def _conta(nome, conta_de_servico=_PADRAO):
    perfil, setor, servico, ativo = CONTAS[nome]
    return Usuario(
        id=1, nome=nome, setor_id=setor, ativo=ativo,
        conta_de_servico=servico if conta_de_servico is _PADRAO else conta_de_servico,
        role=Role(id=9, nome=perfil),
    )


def _admin_humano(nome):
    """Perfil Administrador e pessoa (API-11, S3)."""
    return CONTAS[nome][0] == "Administrador" and not CONTAS[nome][2]


def _integra_esperado(nome, configuracao):
    """A regra C1, à mão: pessoa, perfil de equipe, setor da TI."""
    perfil, setor, servico, _ = CONTAS[nome]
    return (not servico) and perfil in EQUIPE and setor in CONFIGURACOES[configuracao][1]


def _interno_esperado(nome, configuracao, setor_destino):
    """
    A regra do interno (API-13), à mão: administrador humano; na TI, quem
    integra; na Qualidade, o técnico humano do setor da Qualidade.
    """
    perfil, setor, servico, _ = CONTAS[nome]
    if _admin_humano(nome):
        return True
    if setor_destino == "TI":
        return _integra_esperado(nome, configuracao)
    return (not servico) and perfil == "Tecnico" and setor == SETOR_QUALIDADE


@pytest.fixture
def configurar(monkeypatch):
    def _configurar(configuracao):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", CONFIGURACOES[configuracao][0])
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", SETOR_QUALIDADE)

    return _configurar


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_integra_equipe_ti(configurar, nome, configuracao):
    configurar(configuracao)
    assert integra_equipe_ti(_conta(nome)) is _integra_esperado(nome, configuracao)


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", [n for n in CONTAS if CONTAS[n][2]])
def test_nenhuma_conta_de_servico_integra_a_equipe(configurar, nome, configuracao):
    configurar(configuracao)
    assert integra_equipe_ti(_conta(nome)) is False


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_require_equipe_ti(configurar, nome, configuracao):
    """Administrador humano; os demais, só quem integra. API-11 (S3): o de serviço não passa mais."""
    configurar(configuracao)
    conta = _conta(nome)
    if _admin_humano(nome) or _integra_esperado(nome, configuracao):
        assert require_equipe_ti(current_user=conta) is conta
    else:
        with pytest.raises(HTTPException) as recusa:
            require_equipe_ti(current_user=conta)
        assert (recusa.value.status_code, recusa.value.detail) == (403, EQUIPE_TI_NEGADA)


@pytest.mark.parametrize("setor_destino", SETORES_DESTINO)
@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_comentario_interno(configurar, nome, configuracao, setor_destino):
    """Conta de serviço não vê interno em nenhum dos dois setores (API-10, API-11, API-13)."""
    configurar(configuracao)
    esperado = _interno_esperado(nome, configuracao, setor_destino)
    assert pode_acessar_comentario_interno(_conta(nome), _chamado(setor_destino)) is esperado


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_novo_responsavel_da_ti(configurar, nome, configuracao):
    configurar(configuracao)
    conta = _conta(nome)
    esperado = _integra_esperado(nome, configuracao) and CONTAS[nome][3] is True
    assert pode_ser_novo_responsavel(conta) is esperado
    if CONTAS[nome][2]:
        # A mensagem da recusa da conta de serviço não mudou (API-6).
        assert motivo_de_recusa(conta) == CONTA_DE_SERVICO


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", [n for n in CONTAS if not CONTAS[n][2]])
def test_marcar_como_servico_nunca_concede(configurar, nome, configuracao):
    """A mesma conta, marcada como de serviço, não ganha nada — só pode perder."""
    configurar(configuracao)
    pessoa, servico = _conta(nome), _conta(nome, conta_de_servico=True)
    for regra in (integra_equipe_ti, pode_ser_novo_responsavel):
        assert not (regra(servico) and not regra(pessoa)), regra.__name__
    for setor_destino in SETORES_DESTINO:
        chamado = _chamado(setor_destino)
        assert not (
            pode_acessar_comentario_interno(servico, chamado) and not pode_acessar_comentario_interno(pessoa, chamado)
        ), setor_destino


@pytest.mark.parametrize("valor", [None, 1, "false", "true", 0])
def test_valor_ambiguo_nao_e_pessoa(configurar, valor):
    """Só `False` prova pessoa: `None` (antes do flush) e o que não é booleano não integram."""
    configurar("valida")
    conta = _conta("tecnico_ti_humano", conta_de_servico=valor)
    assert integra_equipe_ti(conta) is False
    assert pode_ser_novo_responsavel(conta) is False


def test_tecnico_humano_da_ti_continua_integrando(configurar):
    configurar("valida")
    assert integra_equipe_ti(_conta("tecnico_ti_humano")) is True
