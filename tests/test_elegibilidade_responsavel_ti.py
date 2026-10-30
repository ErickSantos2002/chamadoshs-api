"""
`responsavel_ti_service`, a regra de quem pode ser novo responsável de
chamado da TI.

Sem banco e sem rota: a função chamada direto, com contas montadas em memória,
conta por conta e configuração por configuração. O PUT que a usa é coberto em
`test_responsavel_ti.py`.

A regra que se prova: elegível é quem `integra_equipe_ti` diz ser da TI, sem
ser conta de serviço — e cada recusa tem a mensagem que a API-6 já dava.
"""

import pytest

import main
from app.models import Role, Usuario
from app.services.leitura_service import integra_equipe_ti
from app.services.responsavel_ti_service import (
    CONTA_DE_SERVICO,
    FORA_DA_EQUIPE,
    motivo_de_recusa,
    pode_ser_novo_responsavel,
)

SETOR_TI = 1
SETOR_QUALIDADE = 2
SETOR_OUTRO = 4
SETOR_INEXISTENTE = 999

# nome → (perfil, setor, conta de serviço)
CONTAS = {
    "tecnico_ti": ("Tecnico", SETOR_TI, False),
    "tecnico_ti_com_acento": ("Técnico", SETOR_TI, False),
    "admin_da_ti": ("Administrador", SETOR_TI, False),
    "admin_da_qualidade": ("Administrador", SETOR_QUALIDADE, False),
    "admin_sem_setor": ("Administrador", None, False),
    "tecnico_qualidade": ("Tecnico", SETOR_QUALIDADE, False),
    "tecnico_outro_setor": ("Tecnico", SETOR_OUTRO, False),
    "tecnico_sem_setor": ("Tecnico", None, False),
    "tecnico_setor_inexistente": ("Tecnico", SETOR_INEXISTENTE, False),
    "usuario_da_ti": ("Usuario", SETOR_TI, False),
    "perfil_desconhecido_na_ti": ("Auditor", SETOR_TI, False),
    "sem_perfil_na_ti": (None, SETOR_TI, False),
    "conta_de_servico_tecnico_ti": ("Tecnico", SETOR_TI, True),
    "conta_de_servico_usuario_ti": ("Usuario", SETOR_TI, True),
}

# Elegíveis com a configuração válida ("1"): perfil de equipe no setor 1.
ELEGIVEIS_NA_TI = {"tecnico_ti", "tecnico_ti_com_acento", "admin_da_ti"}

# SETORES_TI_IDS → quem é elegível. O setor da Qualidade (2) nunca vale como
# TI, nem quando está na lista; o inexistente (999) vale só se for listado.
CONFIGURACOES = {
    "valida": ("1", ELEGIVEIS_NA_TI),
    "ausente": (None, set()),
    "vazia": ("", set()),
    "invalida": ("1,x", set()),
    "com_duplicidade": ("1,1", ELEGIVEIS_NA_TI),
    "conflitante_com_qualidade": ("1,2", ELEGIVEIS_NA_TI),
    "so_qualidade": ("2", set()),
    "outro_setor": ("4", {"tecnico_outro_setor"}),
    "setor_inexistente": ("999", {"tecnico_setor_inexistente"}),
}


def conta(nome, **mudancas):
    perfil, setor, servico = CONTAS[nome]
    campos = dict(
        id=1, nome=nome, setor_id=setor, conta_de_servico=servico, ativo=True,
        role=Role(id=9, nome=perfil) if perfil is not None else None,
    )
    campos.update(mudancas)
    return Usuario(**campos)


@pytest.fixture
def configurar(monkeypatch):
    def _configurar(configuracao):
        valor, _ = CONFIGURACOES[configuracao]
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", valor)
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", SETOR_QUALIDADE)

    return _configurar


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_matriz(configurar, nome, configuracao):
    configurar(configuracao)
    _, elegiveis = CONFIGURACOES[configuracao]
    assert pode_ser_novo_responsavel(conta(nome)) is (nome in elegiveis)


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_e_a_regra_da_api_6(configurar, nome, configuracao):
    """Nada além do que já valia: ser da TI pela API-6 e não ser conta de serviço."""
    configurar(configuracao)
    c = conta(nome)
    assert pode_ser_novo_responsavel(c) is (integra_equipe_ti(c) and not c.conta_de_servico)


@pytest.mark.parametrize("nome", sorted(set(CONTAS) - ELEGIVEIS_NA_TI))
def test_motivo_de_cada_recusa(configurar, nome):
    configurar("valida")
    esperado = CONTA_DE_SERVICO if CONTAS[nome][2] else FORA_DA_EQUIPE
    assert motivo_de_recusa(conta(nome)) == esperado


def test_as_mensagens_sao_as_da_api_6():
    assert CONTA_DE_SERVICO == "Não é possível atribuir um chamado a uma conta de serviço"
    assert FORA_DA_EQUIPE == "Técnico responsável não é da equipe da TI"


@pytest.mark.parametrize("configuracao", ["ausente", "vazia", "invalida", "so_qualidade"])
def test_sem_lista_valida_nem_o_administrador_e_elegivel(configurar, configuracao):
    """Sem fallback: a falta de configuração não abre a atribuição a ninguém."""
    configurar(configuracao)
    for nome in CONTAS:
        assert not pode_ser_novo_responsavel(conta(nome)), nome


def test_a_lista_e_lida_a_cada_chamada(configurar):
    c = conta("tecnico_ti")
    configurar("valida")
    assert pode_ser_novo_responsavel(c)
    configurar("ausente")
    assert not pode_ser_novo_responsavel(c)


def test_mudar_de_setor_muda_a_resposta(configurar):
    configurar("valida")
    assert not pode_ser_novo_responsavel(conta("tecnico_ti", setor_id=SETOR_QUALIDADE))
