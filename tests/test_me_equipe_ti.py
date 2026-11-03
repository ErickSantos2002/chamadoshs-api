"""
`integra_equipe_ti` no `GET /auth/me` (API-7, A7-5).

O campo orienta a tela; quem protege é a API. Por isso o que se prova aqui
é que os dois dizem a mesma coisa: para quem não é administrador, o campo é
True exatamente quando a administração da TI responde 200. O administrador
administra pelo perfil, e o campo dele diz só se ele está num setor da TI.

E o resto do contrato: os campos de antes continuam iguais, o valor é
recalculado a cada pedido, e o cliente não tem como mandá-lo — nem no
cadastro, nem no token.
"""

import pytest

from app.core.security import decodificar_token
from app.models import Usuario
from app.schemas.auth import TokenResponse
from leitura_cenario import cenario_de_leitura  # noqa: F401
from test_administracao_equipe_ti import (  # noqa: F401
    CONFIGURACOES,
    PERFIS,
    administracao,
    como,
    configurar,
)

API = "/api/v1"
CAMPOS = {"id", "nome", "setor_id", "role_id", "ativo", "integra_equipe_ti"}

# Com a lista válida, quem é da TI: os que estão no setor 1 com perfil de
# equipe. O administrador da Qualidade não é, e administra do mesmo jeito.
# API-10 (C1): a conta de serviço técnica da TI saiu daqui — não integra a equipe.
DA_TI = {"admin", "tecnico_ti"}


def _me(cliente, headers):
    resposta = cliente.get(f"{API}/auth/me", headers=headers)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("quem", PERFIS)
def test_valor_por_perfil_e_configuracao(cliente, como, configurar, administracao, sessao, quem, configuracao):
    configurar(configuracao)
    corpo = _me(cliente, como(quem))
    assert set(corpo) == CAMPOS
    assert corpo["integra_equipe_ti"] is (quem in DA_TI and CONFIGURACOES[configuracao][1])

    # Os campos de antes, iguais ao cadastro.
    conta = sessao.get(Usuario, administracao[quem])
    assert {k: corpo[k] for k in CAMPOS - {"integra_equipe_ti"}} == {
        "id": conta.id, "nome": conta.nome, "setor_id": conta.setor_id, "role_id": conta.role_id, "ativo": conta.ativo,
    }


@pytest.mark.parametrize("configuracao", CONFIGURACOES)
@pytest.mark.parametrize("quem", [p for p in PERFIS if p not in {"admin", "admin_da_qualidade"}])
def test_campo_e_trava_dizem_o_mesmo(cliente, como, configurar, quem, configuracao):
    """Fora do administrador, o campo é a autorização: a tela não mostra o que a API recusa."""
    configurar(configuracao)
    headers = como(quem)
    acesso = cliente.get(f"{API}/tarefas-recorrentes/", headers=headers).status_code
    assert acesso in (200, 403)
    assert _me(cliente, headers)["integra_equipe_ti"] is (acesso == 200)


@pytest.mark.parametrize("configuracao", ["ausente", "vazia", "invalida"])
def test_administrador_fora_da_lista_administra_com_o_campo_false(cliente, como, configurar, configuracao):
    configurar(configuracao)
    for quem in ("admin", "admin_da_qualidade"):
        assert _me(cliente, como(quem))["integra_equipe_ti"] is False
        assert cliente.get(f"{API}/tarefas-recorrentes/", headers=como(quem)).status_code == 200


def test_mudanca_de_setor_vale_no_proximo_pedido(cliente, como, configurar, administracao):
    configurar("valida")
    headers = como("tecnico_ti")
    assert _me(cliente, headers)["integra_equipe_ti"] is True
    movido = cliente.put(
        f"{API}/usuarios/{administracao['tecnico_ti']}", headers=como("admin"),
        json={"setor_id": administracao["setor_qualidade_id"]},
    )
    assert movido.status_code == 200, movido.text
    # O mesmo token: o campo não está nele.
    assert _me(cliente, headers)["integra_equipe_ti"] is False
    assert cliente.get(f"{API}/tarefas-recorrentes/", headers=headers).status_code == 403


def test_mudanca_de_configuracao_vale_no_proximo_pedido(cliente, como, configurar):
    headers = como("tecnico_ti")
    configurar("valida")
    assert _me(cliente, headers)["integra_equipe_ti"] is True
    configurar("ausente")
    assert _me(cliente, headers)["integra_equipe_ti"] is False


class TestClienteNaoManda:
    def test_cadastro_ignora_o_campo(self, cliente, sessao, como, configurar, administracao):
        configurar("valida")
        quem = administracao["tecnico_qualidade"]
        resposta = cliente.put(
            f"{API}/usuarios/{quem}", headers=como("admin"), json={"nome": "bruno.q", "integra_equipe_ti": True},
        )
        assert resposta.status_code == 200, resposta.text
        assert "integra_equipe_ti" not in resposta.json()
        assert _me(cliente, como("tecnico_qualidade"))["integra_equipe_ti"] is False

    def test_nao_e_coluna(self):
        assert "integra_equipe_ti" not in Usuario.__table__.columns

    def test_nem_no_token_nem_na_resposta_de_login(self, cliente, como, configurar):
        configurar("valida")
        assert "integra_equipe_ti" not in TokenResponse.model_fields
        renovado = cliente.post(f"{API}/auth/refresh", headers=como("tecnico_ti"))
        assert renovado.status_code == 200, renovado.text
        assert set(renovado.json()) == {"access_token", "token_type", "user_id", "nome", "role"}
        assert set(decodificar_token(renovado.json()["access_token"])) == {"sub", "nome", "role", "exp"}

    def test_me_sem_token_continua_401(self, cliente, administracao):
        assert cliente.get(f"{API}/auth/me").status_code == 401
