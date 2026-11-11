"""
O último administrador humano em PostgreSQL real (API-11, S4).

Dois administradores humanos, e a conta compartilhada ativa: cada um tenta
tirar o outro ao mesmo tempo. Contando sem trava, os dois veriam "um outro" e
os dois passariam — o sistema ficaria só com a conta de serviço. Com o
`FOR UPDATE` de `_outros_admins_humanos_ativos`, o segundo espera o primeiro e
reavalia a conta sobre a linha já gravada.

A sincronização é a da matriz da API-4c, nunca por sleep: a requisição A para
logo depois de contar, com as linhas travadas; B é disparada e o teste espera
o PostgreSQL mostrar B bloqueada pelo backend de A; A segue e faz commit.

Os testes de `test_ultimo_administrador_humano.py` rodam aqui também.
"""

import pytest

from app.api.endpoints import usuarios as usuarios_endpoint
from app.api.endpoints.usuarios import ULTIMO_ADMIN_CONVERTER, ULTIMO_ADMIN_REBAIXAR
from app.models import Usuario
from concorrencia import Pausa, em_paralelo, esperar_bloqueio

# As sessões por requisição e o banco da matriz de concorrência.
from test_concorrencia_versao_postgres import banco_modelo, cliente, engine, sessao, url_do_banco  # noqa: F401

# Importados para serem coletados aqui também, com o `sessao` deste módulo.
from test_ultimo_administrador_humano import (  # noqa: F401
    TestBancoSemAdministradorHumano,
    TestComOutroHumano,
    TestContaDeServicoNaoConta,
    com_admin_de_servico,
    dois_humanos,
)

pytestmark = pytest.mark.postgres

API = "/api/v1"
A, B, SERVICO = 10, 11, 12


@pytest.fixture
def admins(dados, sessao):
    sessao.add_all([
        Usuario(id=B, nome="admin.dois", role_id=1, setor_id=1, ativo=True),
        Usuario(id=SERVICO, nome="admin.compartilhado", role_id=1, setor_id=1, ativo=True, conta_de_servico=True),
    ])
    sessao.commit()


@pytest.fixture
def pausa(monkeypatch):
    """A primeira contagem para depois de travar as linhas; as seguintes passam direto."""
    p = Pausa(usuarios_endpoint._outros_admins_humanos_ativos)
    monkeypatch.setattr(usuarios_endpoint, "_outros_admins_humanos_ativos", p)
    yield p
    p.liberar()


def _humanos_ativos(sessao):
    sessao.expire_all()
    return sorted(
        u.id for u in sessao.query(Usuario)
        if u.ativo is True and u.role_id == 1 and u.conta_de_servico is False
    )


def _pedido(cliente, autenticar, ator, metodo, rota, corpo):
    h = autenticar(ator, f"admin{ator}", "Administrador")
    return lambda: cliente.request(metodo, f"{API}{rota}", headers=h, json=corpo)


# (o que A faz com B, o que B faz com A, o motivo da recusa de B)
CRUZADOS = {
    "rebaixar_x_rebaixar": (
        ("PUT", f"/usuarios/{B}", {"role_id": 3}), ("PUT", f"/usuarios/{A}", {"role_id": 3}), ULTIMO_ADMIN_REBAIXAR,
    ),
    "desativar_x_converter": (
        ("PATCH", f"/usuarios/{B}/desativar", None), ("PUT", f"/usuarios/{A}", {"conta_de_servico": True}),
        ULTIMO_ADMIN_CONVERTER,
    ),
    "converter_x_rebaixar_e_converter": (
        ("PUT", f"/usuarios/{B}", {"conta_de_servico": True}),
        ("PUT", f"/usuarios/{A}", {"role_id": 2, "conta_de_servico": True}),
        ULTIMO_ADMIN_REBAIXAR,
    ),
}


@pytest.mark.parametrize("cena", sorted(CRUZADOS))
def test_dois_removendo_um_ao_outro_deixam_um_humano(cliente, admins, sessao, autenticar, url_do_banco, pausa, cena):
    de_a, de_b, motivo = CRUZADOS[cena]
    esperar_a = em_paralelo(_pedido(cliente, autenticar, A, *de_a))
    pausa.esperar_parar()
    esperar_b = em_paralelo(_pedido(cliente, autenticar, B, *de_b))
    esperar_bloqueio(url_do_banco, pausa.pid)
    pausa.liberar()
    resposta_a, resposta_b = esperar_a(), esperar_b()

    assert resposta_a.status_code in (200, 204), resposta_a.text
    assert (resposta_b.status_code, resposta_b.json()) == (400, {"detail": motivo})
    assert _humanos_ativos(sessao) == [A]
