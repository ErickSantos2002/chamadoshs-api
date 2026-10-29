"""
`require_equipe_ti`, a dependência da administração global (API-7, D13).

Sem banco e sem rota: a dependência chamada direto, com contas montadas em
memória, perfil por perfil e configuração por configuração. As rotas que a
usam são cobertas em `test_administracao_equipe_ti.py`.

A regra que se prova: administrador passa sempre; técnico passa só se
`integra_equipe_ti` disser que ele é da TI; o resto recebe 403 — o mesmo
403, com o mesmo corpo, para todo mundo.
"""

import pytest
from fastapi import HTTPException

import main
from app.api.deps import EQUIPE_TI_NEGADA, require_equipe_ti
from app.models import Role, Usuario
from app.services.leitura_service import integra_equipe_ti

SETOR_TI = 1
SETOR_QUALIDADE = 2
SETOR_OUTRO = 4

# (nome, perfil, setor, conta de serviço)
CONTAS = {
    "admin_da_ti": ("Administrador", SETOR_TI, False),
    "admin_da_qualidade": ("Administrador", SETOR_QUALIDADE, False),
    "admin_sem_setor": ("Administrador", None, False),
    "tecnico_ti": ("Tecnico", SETOR_TI, False),
    "tecnico_ti_com_acento": ("Técnico", SETOR_TI, False),
    "tecnico_qualidade": ("Tecnico", SETOR_QUALIDADE, False),
    "tecnico_outro_setor": ("Tecnico", SETOR_OUTRO, False),
    "tecnico_sem_setor": ("Tecnico", None, False),
    "usuario_da_ti": ("Usuario", SETOR_TI, False),
    "perfil_desconhecido_na_ti": ("Auditor", SETOR_TI, False),
    "sem_perfil_na_ti": (None, SETOR_TI, False),
    # Conta de serviço segue a regra do perfil e do setor, como em toda rota
    # de equipe: a recusa dela é só como responsável de chamado (`chamados.py`).
    "conta_de_servico_tecnico_ti": ("Tecnico", SETOR_TI, True),
    "conta_de_servico_usuario_ti": ("Usuario", SETOR_TI, True),
}

ADMINISTRADORES = {"admin_da_ti", "admin_da_qualidade", "admin_sem_setor"}
TECNICOS_DA_TI = {"tecnico_ti", "tecnico_ti_com_acento", "conta_de_servico_tecnico_ti"}

# SETORES_TI_IDS → se o técnico do setor 1 é da TI. O setor da Qualidade
# (2) nunca vale como TI, nem quando está na lista.
CONFIGURACOES = {
    "valida": ("1", True),
    "ausente": (None, False),
    "vazia": ("", False),
    "invalida": ("1,x", False),
    "com_duplicidade": ("1,1", True),
    "conflitante_com_qualidade": ("1,2", True),
    "so_qualidade": ("2", False),
    "outro_setor": ("4", False),
}


def _conta(nome):
    perfil, setor, servico = CONTAS[nome]
    return Usuario(
        id=1, nome=nome, setor_id=setor, conta_de_servico=servico, ativo=True,
        role=Role(id=9, nome=perfil) if perfil is not None else None,
    )


def _autorizado(nome, configuracao):
    if nome in ADMINISTRADORES:
        return True
    _, ti_valida = CONFIGURACOES[configuracao]
    if configuracao == "outro_setor":
        return nome == "tecnico_outro_setor"
    return nome in TECNICOS_DA_TI and ti_valida


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
    conta = _conta(nome)
    if _autorizado(nome, configuracao):
        assert require_equipe_ti(current_user=conta) is conta
    else:
        with pytest.raises(HTTPException) as recusa:
            require_equipe_ti(current_user=conta)
        assert recusa.value.status_code == 403
        assert recusa.value.detail == EQUIPE_TI_NEGADA


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", sorted(set(CONTAS) - ADMINISTRADORES))
def test_fora_do_administrador_a_regra_e_a_de_integra_equipe_ti(configurar, nome, configuracao):
    """Uma regra só: para quem não é administrador, passar é ser da TI pela API-6."""
    configurar(configuracao)
    conta = _conta(nome)
    try:
        require_equipe_ti(current_user=conta)
        passou = True
    except HTTPException:
        passou = False
    assert passou is integra_equipe_ti(conta)


@pytest.mark.parametrize("configuracao", ["ausente", "vazia", "invalida"])
def test_sem_lista_valida_o_administrador_continua(configurar, configuracao):
    configurar(configuracao)
    for nome in ADMINISTRADORES:
        conta = _conta(nome)
        assert require_equipe_ti(current_user=conta) is conta


def test_a_lista_e_lida_a_cada_pedido(configurar):
    """Mudar a configuração muda a resposta sem recriar nada: não há cache."""
    conta = _conta("tecnico_ti")
    configurar("valida")
    assert require_equipe_ti(current_user=conta) is conta
    configurar("ausente")
    with pytest.raises(HTTPException):
        require_equipe_ti(current_user=conta)


def test_mudar_de_setor_muda_a_resposta(configurar):
    configurar("valida")
    conta = _conta("tecnico_ti")
    conta.setor_id = SETOR_QUALIDADE
    with pytest.raises(HTTPException):
        require_equipe_ti(current_user=conta)


@pytest.mark.parametrize("valor", [None, "", "1,x"])
def test_o_log_da_subida_diz_que_a_administracao_fica_com_o_administrador(monkeypatch, caplog, valor):
    """O diagnóstico operacional da A7-6: quem olha o log sabe o que a TI perdeu."""
    import logging

    from app.core.config import Settings

    if valor is None:
        monkeypatch.delenv("SETORES_TI_IDS", raising=False)
    else:
        monkeypatch.setenv("SETORES_TI_IDS", valor)
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        Settings(_env_file=None)
    assert any("administração global só pelo administrador" in r.getMessage() for r in caplog.records)
