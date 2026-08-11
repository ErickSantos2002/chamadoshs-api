"""
Testes das travas de desativação de usuário.

O DELETE sempre recusou desativar a si mesmo e desativar o último
administrador ativo — sem isso o sistema fica sem quem administrar, e como
criar e editar usuário também exigem administrador, a recuperação só sairia
por SQL direto no banco.

O PUT aceita `ativo` e não tinha nenhuma das duas travas: `PUT {"ativo":
false}` derrubava o último administrador pela porta ao lado da que o DELETE
trancava. As travas agora são compartilhadas.

A outra metade importa tanto quanto: elas valem só na desativação. Reativar é
`PUT {"ativo": true}`, e é o único caminho de volta pela interface — travar
qualquer mudança de `ativo` bloquearia a recuperação em vez do dano.
"""

from app.models import Usuario


def _segundo_admin(sessao, ativo=True):
    outro = Usuario(id=11, nome="admin.outro", role_id=1, setor_id=1, ativo=ativo)
    sessao.add(outro)
    sessao.commit()
    return outro.id


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


class TestPutNaoDesativaQuemNaoPode:
    """O furo que existia: as travas do DELETE não valiam para o PUT."""

    def test_put_recusa_desativar_a_si_mesmo(self, cliente, dados, sessao, autenticar):
        """
        Esta é a trava que de fato fecha o buraco. Quando só resta um
        administrador ativo, ele é necessariamente quem está autenticado —
        e é aqui que a requisição para.
        """
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['admin_id']}",
            json={"ativo": False},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert "próprio usuário" in resposta.json()["detail"]

        sessao.expire_all()
        assert sessao.query(Usuario).filter(Usuario.id == dados["admin_id"]).one().ativo is True

    def test_put_desativa_outro_admin_quando_sobra_um(self, cliente, dados, sessao, autenticar):
        """Com dois administradores ativos, desativar um é legítimo."""
        outro_id = _segundo_admin(sessao)

        resposta = cliente.put(
            f"/api/v1/usuarios/{outro_id}",
            json={"ativo": False},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is False

    def test_put_desativa_usuario_comum_normalmente(self, cliente, dados, autenticar):
        """As travas são sobre administrador; o resto segue igual."""
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"ativo": False},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is False

    def test_admin_desativado_perde_o_acesso(self, cliente, dados, sessao, autenticar):
        """
        Por que a trava do último administrador não é alcançável: para desativar
        alguém é preciso estar ativo. Um admin desativado não passa nem do
        get_current_user, então nunca chega a ser o segundo a desativar.
        """
        outro_id = _segundo_admin(sessao, ativo=False)

        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"ativo": False},
            headers=autenticar(outro_id, "admin.outro", "Administrador"),
        )

        assert resposta.status_code == 403


class TestReativarNaoEAfetado:
    """
    A parte que não pode regredir: o botão de reativar do frontend manda
    PUT {"ativo": true}, e é o único caminho de volta que existe hoje.
    """

    def test_reativar_usuario_comum(self, cliente, dados, sessao, autenticar):
        sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().ativo = False
        sessao.commit()

        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"ativo": True},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is True

    def test_reativar_administrador(self, cliente, dados, sessao, autenticar):
        """
        O caso que uma trava mal colocada quebraria: reativar um admin
        enquanto existe um único admin ativo é exatamente a recuperação.
        """
        outro_id = _segundo_admin(sessao, ativo=False)

        resposta = cliente.put(
            f"/api/v1/usuarios/{outro_id}",
            json={"ativo": True},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is True

    def test_reativar_a_si_mesmo_nao_e_bloqueado(self, cliente, dados, autenticar):
        """
        `ativo: true` no próprio usuário não pode cair na trava de
        auto-desativação. É no-op — e no-op responde 200, não 400.
        """
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['admin_id']}",
            json={"ativo": True},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200

    def test_editar_outro_campo_do_proprio_admin_continua_liberado(
        self, cliente, dados, autenticar
    ):
        """
        A trava olha o valor de `ativo`, não a presença do campo: trocar o
        setor não tem nada a ver com desativar.
        """
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['admin_id']}",
            json={"setor_id": 1},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200


class TestDeleteContinuaIgual:
    """O DELETE passou a chamar a trava compartilhada; o contrato é o mesmo."""

    def test_delete_recusa_o_proprio_usuario(self, cliente, dados, autenticar):
        resposta = cliente.delete(
            f"/api/v1/usuarios/{dados['admin_id']}",
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert "próprio usuário" in resposta.json()["detail"]

    def test_delete_desativa_usuario_comum(self, cliente, dados, sessao, autenticar):
        resposta = cliente.delete(
            f"/api/v1/usuarios/{dados['comum_id']}",
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 204

        sessao.expire_all()
        assert sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().ativo is False
