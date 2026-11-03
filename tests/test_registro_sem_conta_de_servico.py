"""
`POST /auth/registro` recusa `conta_de_servico` (API-11, decisão S5).

O schema da rota não tem o campo, e o Pydantic descartava a chave calado:
`{"conta_de_servico": true}` voltava 201 com uma conta humana, e quem criou
saía achando que tinha criado uma conta de serviço. Agora qualquer presença da
chave é 422, e a conta não é criada. O `POST /usuarios/`, que tem o campo,
não muda.
"""

import pytest

from app.core.security import gerar_hash_senha
from app.models import Usuario
from app.models.evento_conta import EventoDeConta

API = "/api/v1"
SENHA = "senha-atual-123"
CORPO = {"nome": "nova.pessoa", "senha": "senha-inicial-123", "role_id": 3}


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


def _foto(sessao):
    sessao.expire_all()
    return sessao.query(Usuario).count(), sessao.query(EventoDeConta).count()


@pytest.mark.parametrize("valor", [True, False, None, "sim", 1, [], {}])
def test_qualquer_presenca_da_chave_e_422_sem_criar(cliente, dados, sessao, autenticar, valor):
    antes = _foto(sessao)
    resposta = cliente.post(f"{API}/auth/registro", headers=_como_admin(autenticar, dados),
                            json={**CORPO, "conta_de_servico": valor})
    assert resposta.status_code == 422
    assert "conta_de_servico" in resposta.text
    assert _foto(sessao) == antes
    assert sessao.query(Usuario).filter(Usuario.nome == CORPO["nome"]).first() is None


def test_o_registro_legitimo_continua(cliente, dados, sessao, autenticar):
    resposta = cliente.post(f"{API}/auth/registro", headers=_como_admin(autenticar, dados), json=CORPO)
    assert resposta.status_code == 201
    sessao.expire_all()
    criado = sessao.get(Usuario, resposta.json()["user_id"])
    assert (criado.nome, criado.role_id, criado.conta_de_servico) == (CORPO["nome"], 3, False)


def test_sem_token_continua_401(cliente, dados, sessao, autenticar):
    """A validação do corpo não passa na frente da autenticação."""
    resposta = cliente.post(f"{API}/auth/registro", json={**CORPO, "conta_de_servico": False})
    assert resposta.status_code == 401
    assert sessao.query(Usuario).filter(Usuario.nome == CORPO["nome"]).first() is None


def test_post_usuarios_ainda_cria_conta_de_servico(cliente, dados, sessao, autenticar):
    resposta = cliente.post(f"{API}/usuarios/", headers=_como_admin(autenticar, dados),
                            json={**CORPO, "conta_de_servico": True})
    assert resposta.status_code == 201
    assert resposta.json()["conta_de_servico"] is True


def test_alterar_senha_continua(cliente, dados, sessao, autenticar):
    admin = sessao.get(Usuario, dados["admin_id"])
    admin.senha_hash = gerar_hash_senha(SENHA)
    sessao.commit()
    resposta = cliente.post(f"{API}/auth/alterar-senha", headers=_como_admin(autenticar, dados),
                            json={"senha_atual": SENHA, "senha_nova": "senha-nova-456"})
    assert resposta.status_code == 200
