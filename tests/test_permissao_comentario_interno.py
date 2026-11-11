"""
`pode_acessar_comentario_interno`, a regra do comentário interno (API-8,
refeita na API-13).

Sem banco e sem rota: a função chamada direto, com as contas e as
configurações de `test_permissao_equipe_ti.py`, num chamado da TI e num da
Qualidade. As rotas que a usam são cobertas em `test_comentarios_internos.py`.

A regra que se prova (API-13): administrador humano pode sempre; técnico, só
no setor de destino da equipe dele — o da TI, se `integra_equipe_ti` disser
que ele é da TI, nos chamados da TI; o da Qualidade nos da Qualidade; o
resto, nunca — nem o técnico de outro setor ou sem setor, que até a API-7
passavam pelo perfil (`is_staff`). É a regra de `pode_alterar_como_equipe`.
Até a API-12 a pergunta era só do perfil: o técnico da TI via o interno da
Qualidade, e o da Qualidade não via nenhum. Ler o chamado é exigido à parte.
"""

import pytest
from fastapi import HTTPException

from app.api.deps import is_staff, require_equipe_ti
from app.models import Chamado
from app.services.leitura_service import (
    integra_equipe_ti,
    pode_acessar_comentario_interno,
    pode_alterar_como_equipe,
)
from test_permissao_equipe_ti import (  # noqa: F401
    ADMINISTRADORES,
    CONFIGURACOES,
    CONTAS,
    _autorizado,
    _conta,
    configurar,
)

SETORES_DESTINO = ["TI", "QUALIDADE"]


def _chamado(setor_destino):
    # Sem vínculo com a conta (id 1): o vínculo não daria o interno, mas aqui
    # nem a leitura fica em jogo.
    return Chamado(id=1, setor_destino=setor_destino, solicitante_id=99, tecnico_responsavel_id=None)


def _interno_esperado(nome, configuracao, setor_destino):
    if nome in ADMINISTRADORES:
        return True
    if setor_destino == "TI":
        return _autorizado(nome, configuracao)
    # O setor da Qualidade é sempre o 2 aqui, qualquer que seja a lista da TI.
    return nome == "tecnico_qualidade"


@pytest.mark.parametrize("setor_destino", SETORES_DESTINO)
@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_matriz(configurar, nome, configuracao, setor_destino):
    configurar(configuracao)
    esperado = _interno_esperado(nome, configuracao, setor_destino)
    assert pode_acessar_comentario_interno(_conta(nome), _chamado(setor_destino)) is esperado


@pytest.mark.parametrize("setor_destino", SETORES_DESTINO)
@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_e_a_mesma_regra_de_alterar_como_equipe(configurar, nome, configuracao, setor_destino):
    """API-13: quem altera o chamado como equipe é quem vê o interno dele — um critério só."""
    configurar(configuracao)
    conta, chamado = _conta(nome), _chamado(setor_destino)
    assert pode_acessar_comentario_interno(conta, chamado) is pode_alterar_como_equipe(conta, chamado)


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", sorted(set(CONTAS) - ADMINISTRADORES))
def test_no_chamado_da_ti_fora_do_administrador_a_regra_e_a_de_integra_equipe_ti(configurar, nome, configuracao):
    """Sem classificação paralela da TI: nos chamados da TI, a mesma da API-6."""
    configurar(configuracao)
    conta = _conta(nome)
    assert pode_acessar_comentario_interno(conta, _chamado("TI")) is integra_equipe_ti(conta)


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_no_chamado_da_ti_e_a_mesma_regra_da_administracao(configurar, nome, configuracao):
    """Quem administra como TI (API-7) é quem vê o interno dos chamados da TI."""
    configurar(configuracao)
    conta = _conta(nome)
    try:
        require_equipe_ti(current_user=conta)
        administra = True
    except HTTPException:
        administra = False
    assert pode_acessar_comentario_interno(conta, _chamado("TI")) is administra


def test_no_chamado_da_qualidade_nao_e_a_regra_da_administracao(configurar):
    """API-13: a administração segue da TI, o interno da Qualidade é da equipe da Qualidade."""
    configurar("valida")
    qualidade, ti = _conta("tecnico_qualidade"), _conta("tecnico_ti")
    chamado = _chamado("QUALIDADE")
    with pytest.raises(HTTPException):
        require_equipe_ti(current_user=qualidade)
    assert pode_acessar_comentario_interno(qualidade, chamado) is True
    assert require_equipe_ti(current_user=ti) is ti
    assert pode_acessar_comentario_interno(ti, chamado) is False


@pytest.mark.parametrize("setor_destino", SETORES_DESTINO)
@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize(
    "nome", ["tecnico_qualidade", "tecnico_outro_setor", "tecnico_sem_setor"],
)
def test_perfil_tecnico_nao_basta(configurar, nome, configuracao, setor_destino):
    """O perfil que até a API-7 bastava não decide mais: decide o setor da equipe."""
    configurar(configuracao)
    conta = _conta(nome)
    assert is_staff(conta)
    if setor_destino == "TI":
        esperado = configuracao == "outro_setor" and nome == "tecnico_outro_setor"
    else:
        esperado = nome == "tecnico_qualidade"
    assert pode_acessar_comentario_interno(conta, _chamado(setor_destino)) is esperado


@pytest.mark.parametrize("configuracao", ["ausente", "vazia", "invalida", "so_qualidade"])
def test_sem_ti_valida_so_o_administrador(configurar, configuracao):
    """Sem fallback para qualquer técnico: na TI, só o administrador; na Qualidade, segue a equipe dela."""
    configurar(configuracao)
    for nome in CONTAS:
        assert pode_acessar_comentario_interno(_conta(nome), _chamado("TI")) is (nome in ADMINISTRADORES)
        assert pode_acessar_comentario_interno(_conta(nome), _chamado("QUALIDADE")) is (
            nome in ADMINISTRADORES or nome == "tecnico_qualidade"
        )


def test_a_lista_e_lida_a_cada_pedido(configurar):
    conta = _conta("tecnico_ti")
    configurar("valida")
    assert pode_acessar_comentario_interno(conta, _chamado("TI")) is True
    configurar("ausente")
    assert pode_acessar_comentario_interno(conta, _chamado("TI")) is False


def test_mudar_de_setor_muda_a_resposta(configurar):
    """Do setor da TI para o da Qualidade: troca de equipe, e com ela o interno que vê."""
    configurar("valida")
    conta = _conta("tecnico_ti")
    conta.setor_id = 2
    assert pode_acessar_comentario_interno(conta, _chamado("TI")) is False
    assert pode_acessar_comentario_interno(conta, _chamado("QUALIDADE")) is True


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
def test_tecnico_da_ti_nao_ve_o_interno_da_qualidade(configurar, configuracao):
    """API-13: até a API-12 via, porque a regra era só do perfil."""
    configurar(configuracao)
    for nome in ("tecnico_ti", "tecnico_ti_com_acento"):
        assert pode_acessar_comentario_interno(_conta(nome), _chamado("QUALIDADE")) is False
