"""
Testes do 400 para `role_id` e `setor_id` que não existem.

Antes disto o valor inválido seguia até o banco e voltava como IntegrityError
da FK, que o FastAPI entrega como 500. Errado por dois motivos: 500 afirma
defeito do servidor sobre o que é dado inválido do cliente, e a tela mostra
erro genérico em vez de dizer o que houve. O mesmo formulário já respondia 400
na porta ao lado — as travas de administrador — então as duas recusas saíam em
códigos diferentes.

O par de testes que importa em cada caso é recusa + passagem: uma validação que
recusa tudo também faria os testes de recusa passarem, e quebraria o cadastro
inteiro.
"""

from app.models import Setor, Usuario


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


class TestCriacao:
    def test_perfil_inexistente_devolve_400(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/usuarios/",
            json={"nome": "novo.usuario", "senha": "senha-inicial-123", "role_id": 99},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert "Perfil 99" in resposta.json()["detail"]

        # E não gravou nada pelo caminho.
        sessao.expire_all()
        assert sessao.query(Usuario).filter(Usuario.nome == "novo.usuario").count() == 0

    def test_setor_inexistente_devolve_400(self, cliente, dados, autenticar):
        resposta = cliente.post(
            "/api/v1/usuarios/",
            json={
                "nome": "novo.usuario",
                "senha": "senha-inicial-123",
                "role_id": 3,
                "setor_id": 99,
            },
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert "Setor 99" in resposta.json()["detail"]

    def test_vinculos_validos_continuam_passando(self, cliente, dados, autenticar):
        resposta = cliente.post(
            "/api/v1/usuarios/",
            json={
                "nome": "novo.usuario",
                "senha": "senha-inicial-123",
                "role_id": 3,
                "setor_id": 1,
            },
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 201

    def test_sem_setor_continua_passando(self, cliente, dados, autenticar):
        """`setor_id` é opcional: omiti-lo não é dado inválido."""
        resposta = cliente.post(
            "/api/v1/usuarios/",
            json={"nome": "sem.setor", "senha": "senha-inicial-123", "role_id": 3},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 201


class TestEdicao:
    def test_perfil_inexistente_devolve_400(self, cliente, dados, sessao, autenticar):
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"role_id": 99},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert "Perfil 99" in resposta.json()["detail"]

        sessao.expire_all()
        assert sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().role_id == 3

    def test_setor_inexistente_devolve_400(self, cliente, dados, autenticar):
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"setor_id": 99},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert "Setor 99" in resposta.json()["detail"]

    def test_tirar_a_pessoa_do_setor_continua_passando(self, cliente, dados, sessao, autenticar):
        """
        `setor_id: null` é o jeito de esvaziar o campo, não um vínculo inválido.
        Recusá-lo tornaria impossível tirar alguém de um setor.
        """
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"setor_id": None},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        sessao.expire_all()
        assert sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().setor_id is None

    def test_edicao_sem_tocar_nos_vinculos_continua_passando(self, cliente, dados, autenticar):
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"nome": "usuario.renomeado"},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200

    def test_setor_inativo_ainda_e_um_setor(self, cliente, dados, sessao, autenticar):
        """
        A validação é sobre existir, não sobre estar ativo. Barrar setor inativo
        aqui quebraria a edição de quem já está vinculado a um: o modal envia o
        cadastro inteiro em toda gravação, então salvar qualquer campo
        reenviaria o `setor_id` atual da pessoa.
        """
        sessao.add(Setor(id=2, nome="Extinto", ativo=False))
        sessao.commit()

        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"setor_id": 2},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200


class TestOrdemDasRecusas:
    def test_perfil_invalido_ganha_da_trava_de_rebaixamento(self, cliente, dados, autenticar):
        """
        Um `role_id` que não existe também não é administrador, então a trava do
        último administrador barraria a requisição sozinha — com uma mensagem
        sobre rebaixamento, para um id que não resolve para perfil nenhum.

        A validação roda antes justamente para a mensagem descrever o que houve.
        As duas recusas são 400; o que muda é o texto que chega na tela.
        """
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['admin_id']}",
            json={"role_id": 99},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert "Perfil 99" in resposta.json()["detail"]
        assert "administrador" not in resposta.json()["detail"]
