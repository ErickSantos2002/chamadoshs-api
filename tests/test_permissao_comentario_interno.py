"""
`pode_acessar_comentario_interno`, a regra do comentário interno (API-8).

Sem banco e sem rota: a função chamada direto, com as contas e as
configurações de `test_permissao_equipe_ti.py`. As rotas que a usam são
cobertas em `test_comentarios_internos.py`.

A regra que se prova: administrador pode sempre; técnico, só se
`integra_equipe_ti` disser que ele é da TI; o resto, nunca — nem o técnico
da Qualidade, de outro setor ou sem setor, que até a API-7 passavam pelo
perfil (`is_staff`). Aqui só o perfil: ler o chamado é exigido à parte.
"""

import pytest
from fastapi import HTTPException

from app.api.deps import is_staff, require_equipe_ti
from app.services.leitura_service import integra_equipe_ti, pode_acessar_comentario_interno
from test_permissao_equipe_ti import (  # noqa: F401
    ADMINISTRADORES,
    CONFIGURACOES,
    CONTAS,
    _autorizado,
    _conta,
    configurar,
)


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_matriz(configurar, nome, configuracao):
    configurar(configuracao)
    assert pode_acessar_comentario_interno(_conta(nome)) is _autorizado(nome, configuracao)


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", sorted(set(CONTAS) - ADMINISTRADORES))
def test_fora_do_administrador_a_regra_e_a_de_integra_equipe_ti(configurar, nome, configuracao):
    """Sem classificação paralela da TI: a mesma da API-6."""
    configurar(configuracao)
    conta = _conta(nome)
    assert pode_acessar_comentario_interno(conta) is integra_equipe_ti(conta)


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("nome", CONTAS)
def test_e_a_mesma_regra_da_administracao(configurar, nome, configuracao):
    """Quem administra como TI (API-7) é quem vê o interno: a tela usa um critério só."""
    configurar(configuracao)
    conta = _conta(nome)
    try:
        require_equipe_ti(current_user=conta)
        administra = True
    except HTTPException:
        administra = False
    assert pode_acessar_comentario_interno(conta) is administra


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize(
    "nome", ["tecnico_qualidade", "tecnico_outro_setor", "tecnico_sem_setor"],
)
def test_perfil_tecnico_nao_basta(configurar, nome, configuracao):
    """O perfil que até a API-7 bastava não decide mais."""
    configurar(configuracao)
    conta = _conta(nome)
    assert is_staff(conta)
    esperado = configuracao == "outro_setor" and nome == "tecnico_outro_setor"
    assert pode_acessar_comentario_interno(conta) is esperado


@pytest.mark.parametrize("configuracao", ["ausente", "vazia", "invalida", "so_qualidade"])
def test_sem_ti_valida_so_o_administrador(configurar, configuracao):
    """Sem fallback para qualquer técnico."""
    configurar(configuracao)
    for nome in CONTAS:
        assert pode_acessar_comentario_interno(_conta(nome)) is (nome in ADMINISTRADORES)


def test_a_lista_e_lida_a_cada_pedido(configurar):
    conta = _conta("tecnico_ti")
    configurar("valida")
    assert pode_acessar_comentario_interno(conta) is True
    configurar("ausente")
    assert pode_acessar_comentario_interno(conta) is False


def test_mudar_de_setor_muda_a_resposta(configurar):
    configurar("valida")
    conta = _conta("tecnico_ti")
    conta.setor_id = 2
    assert pode_acessar_comentario_interno(conta) is False
