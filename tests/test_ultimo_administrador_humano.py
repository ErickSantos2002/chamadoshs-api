"""
O último administrador humano ativo não sai (API-11, decisão S4).

Até a API-10, a trava do "último administrador ativo" contava a conta de
serviço: com a conta compartilhada de administração ativa, o último
administrador de verdade podia se rebaixar, ou ser rebaixado e desativado, e o
sistema ficava administrado só por uma conta que não é ninguém. Agora só conta
quem é ativo, administrador e pessoa — e a trava olha o estado final da conta
com tudo o que o PUT muda junto.

A concorrência (dois administradores removendo um ao outro ao mesmo tempo)
está em `test_ultimo_administrador_humano_postgres.py`: o SQLite não tem
`FOR UPDATE`.
"""

import pytest
from sqlalchemy import text

from app.api.endpoints.usuarios import (
    ULTIMO_ADMIN_CONVERTER,
    ULTIMO_ADMIN_DESATIVAR,
    ULTIMO_ADMIN_REBAIXAR,
    _outros_admins_humanos_ativos,
)
from app.models import Usuario
from app.models.evento_conta import EventoDeConta

API = "/api/v1"
ADMIN = 10  # conftest: administrador humano, setor 1
OUTRO_ADMIN = 11
ADMIN_DE_SERVICO = 12
ADMIN_INATIVO = 13
PROPRIO = "Não é possível desativar o próprio usuário"


@pytest.fixture
def com_admin_de_servico(dados, sessao):
    """O caso real que a trava deixava passar: um humano e a conta compartilhada."""
    sessao.add_all([
        Usuario(id=ADMIN_DE_SERVICO, nome="admin.compartilhado", role_id=1, setor_id=1, ativo=True,
                conta_de_servico=True),
        Usuario(id=ADMIN_INATIVO, nome="admin.antigo", role_id=1, setor_id=1, ativo=False),
    ])
    sessao.commit()
    return dados


@pytest.fixture
def dois_humanos(com_admin_de_servico, sessao):
    sessao.add(Usuario(id=OUTRO_ADMIN, nome="admin.dois", role_id=1, setor_id=1, ativo=True))
    sessao.commit()
    return com_admin_de_servico


def _foto(sessao):
    sessao.expire_all()
    return {
        "usuarios": sorted((u.id, u.role_id, u.ativo, u.conta_de_servico) for u in sessao.query(Usuario)),
        "eventos": sessao.query(EventoDeConta).count(),
    }


def _como(autenticar, uid):
    return autenticar(uid, f"admin{uid}", "Administrador")


class TestContaDeServicoNaoConta:
    @pytest.mark.parametrize("corpo,motivo", [
        ({"role_id": 3}, ULTIMO_ADMIN_REBAIXAR),
        ({"role_id": 2}, ULTIMO_ADMIN_REBAIXAR),
        ({"conta_de_servico": True}, ULTIMO_ADMIN_CONVERTER),
        ({"role_id": 3, "conta_de_servico": True}, ULTIMO_ADMIN_REBAIXAR),
        ({"ativo": False}, PROPRIO),
        ({"ativo": None}, ULTIMO_ADMIN_DESATIVAR),
        ({"ativo": None, "role_id": 3, "conta_de_servico": True}, ULTIMO_ADMIN_DESATIVAR),
    ])
    def test_ultimo_humano_nao_sai_com_a_conta_compartilhada_ativa(
        self, cliente, com_admin_de_servico, sessao, autenticar, corpo, motivo
    ):
        antes = _foto(sessao)
        resposta = cliente.put(f"{API}/usuarios/{ADMIN}", headers=_como(autenticar, ADMIN), json=corpo)
        assert (resposta.status_code, resposta.json()) == (400, {"detail": motivo})
        assert _foto(sessao) == antes

    def test_a_contagem_ignora_servico_inativo_e_o_proprio(self, com_admin_de_servico, sessao):
        assert _outros_admins_humanos_ativos(sessao, ADMIN) == 0
        # NULL de verdade: o ORM troca `ativo=None` pelo default.
        sessao.add(Usuario(id=14, nome="admin.sem.estado", role_id=1, setor_id=1))
        sessao.commit()
        sessao.execute(text("UPDATE usuarios SET ativo = NULL WHERE id = 14"))
        sessao.commit()
        assert _outros_admins_humanos_ativos(sessao, ADMIN) == 0
        assert _outros_admins_humanos_ativos(sessao, ADMIN_DE_SERVICO) == 1

    def test_reenviar_o_mesmo_perfil_passa(self, cliente, com_admin_de_servico, autenticar):
        """O modal manda tudo em toda gravação: só trocar o nome do último humano não trava."""
        resposta = cliente.put(f"{API}/usuarios/{ADMIN}", headers=_como(autenticar, ADMIN), json={
            "nome": "admin.renomeado", "role_id": 1, "setor_id": 1, "conta_de_servico": False, "ativo": True,
        })
        assert resposta.status_code == 200

    def test_rebaixar_a_conta_de_servico_e_livre(self, cliente, com_admin_de_servico, autenticar):
        resposta = cliente.put(f"{API}/usuarios/{ADMIN_DE_SERVICO}", headers=_como(autenticar, ADMIN),
                               json={"role_id": 3})
        assert resposta.status_code == 200


class TestComOutroHumano:
    @pytest.mark.parametrize("corpo", [
        {"role_id": 3}, {"conta_de_servico": True}, {"ativo": False},
        {"role_id": 2, "conta_de_servico": True, "ativo": False},
    ])
    def test_o_outro_pode_sair(self, cliente, dois_humanos, autenticar, corpo):
        resposta = cliente.put(f"{API}/usuarios/{OUTRO_ADMIN}", headers=_como(autenticar, ADMIN), json=corpo)
        assert resposta.status_code == 200

    def test_desativar_pelo_patch_e_pelo_delete(self, cliente, dois_humanos, autenticar):
        assert cliente.patch(f"{API}/usuarios/{OUTRO_ADMIN}/desativar",
                             headers=_como(autenticar, ADMIN)).status_code == 200
        assert cliente.patch(f"{API}/usuarios/{OUTRO_ADMIN}/reativar",
                             headers=_como(autenticar, ADMIN)).status_code == 200
        assert cliente.delete(f"{API}/usuarios/{OUTRO_ADMIN}", headers=_como(autenticar, ADMIN)).status_code == 204

    def test_depois_de_converter_o_outro_o_ultimo_e_ele(self, cliente, dois_humanos, sessao, autenticar):
        h = _como(autenticar, ADMIN)
        assert cliente.put(f"{API}/usuarios/{OUTRO_ADMIN}", headers=h,
                           json={"conta_de_servico": True}).status_code == 200
        antes = _foto(sessao)
        resposta = cliente.put(f"{API}/usuarios/{ADMIN}", headers=h, json={"role_id": 3})
        assert (resposta.status_code, resposta.json()) == (400, {"detail": ULTIMO_ADMIN_REBAIXAR})
        assert _foto(sessao) == antes

    def test_o_outro_humano_rebaixa_o_primeiro_e_vira_o_ultimo(self, cliente, dois_humanos, autenticar):
        assert cliente.put(f"{API}/usuarios/{ADMIN}", headers=_como(autenticar, OUTRO_ADMIN),
                           json={"role_id": 3}).status_code == 200
        resposta = cliente.patch(f"{API}/usuarios/{OUTRO_ADMIN}/desativar", headers=_como(autenticar, OUTRO_ADMIN))
        assert (resposta.status_code, resposta.json()) == (400, {"detail": PROPRIO})
        resposta = cliente.put(f"{API}/usuarios/{OUTRO_ADMIN}", headers=_como(autenticar, OUTRO_ADMIN),
                               json={"conta_de_servico": True})
        assert (resposta.status_code, resposta.json()) == (400, {"detail": ULTIMO_ADMIN_CONVERTER})


class TestBancoSemAdministradorHumano:
    """Estado legado possível: só a conta compartilhada administra. Nada aqui vira atalho."""

    @pytest.fixture
    def so_servico(self, com_admin_de_servico, sessao):
        sessao.get(Usuario, ADMIN).conta_de_servico = True
        sessao.commit()

    @pytest.mark.parametrize("metodo,rota,corpo", [
        ("PUT", f"/usuarios/{ADMIN}", {"conta_de_servico": False}),
        ("PUT", f"/usuarios/{ADMIN_DE_SERVICO}", {"conta_de_servico": False}),
        ("PATCH", f"/usuarios/{ADMIN_INATIVO}/reativar", None),
        ("POST", "/usuarios/", {"nome": "admin.novo", "senha": "x" * 12, "role_id": 1}),
    ])
    def test_conta_de_servico_nao_se_promove(self, cliente, so_servico, sessao, autenticar, metodo, rota, corpo):
        antes = _foto(sessao)
        for uid in (ADMIN, ADMIN_DE_SERVICO):
            resposta = cliente.request(metodo, f"{API}{rota}", headers=_como(autenticar, uid), json=corpo)
            assert resposta.status_code == 403
        assert _foto(sessao) == antes
        assert _outros_admins_humanos_ativos(sessao, 0) == 0
