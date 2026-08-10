"""
Testes do campo `conta_de_servico`.

Contas que não são pessoas — painel de parede, integração, login compartilhado
— precisam autenticar, então não podem ser desativadas. O campo diz o que a
conta é, e o frontend usa isso para tirá-las do seletor de técnico.

O padrão `false` é a parte crítica do contrato e está testado dos dois lados
(schema e resposta da API): se ele virasse `true`, toda conta existente sumiria
do seletor no instante do deploy.
"""

from app.models import Chamado, Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioUpdate


class TestContrato:
    """O frontend depende do nome e do tipo — os dois estão fixados aqui."""

    def test_padrao_e_falso_na_criacao(self):
        """Conta criada sem informar o campo é pessoa."""
        usuario = UsuarioCreate(nome="joao", role_id=3, senha="x")
        assert usuario.conta_de_servico is False

    def test_pode_ser_informado_na_criacao(self):
        usuario = UsuarioCreate(nome="televisao", role_id=3, senha="x", conta_de_servico=True)
        assert usuario.conta_de_servico is True

    def test_ausente_no_update_significa_nao_mexer(self):
        """
        None, e não False: o handler usa exclude_unset, então omitir o campo
        precisa preservar o valor gravado em vez de desmarcar a conta.
        """
        dados = UsuarioUpdate(nome="outro")
        assert dados.conta_de_servico is None
        assert "conta_de_servico" not in dados.model_dump(exclude_unset=True)


class TestApi:
    def test_resposta_expoe_o_campo(self, cliente, dados, autenticar):
        resposta = cliente.get(
            f"/api/v1/usuarios/{dados['comum_id']}",
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 200
        assert resposta.json()["conta_de_servico"] is False

    def test_admin_cria_conta_de_servico(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/usuarios/",
            json={
                "nome": "televisao",
                "role_id": 3,
                "senha": "qualquer",
                "conta_de_servico": True,
            },
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 201
        assert resposta.json()["conta_de_servico"] is True

        gravado = sessao.query(Usuario).filter(Usuario.nome == "televisao").one()
        assert gravado.conta_de_servico is True

    def test_admin_marca_conta_existente(self, cliente, dados, sessao, autenticar):
        """O caminho que substitui o UPDATE manual no banco."""
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"conta_de_servico": True},
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 200
        assert resposta.json()["conta_de_servico"] is True

        sessao.expire_all()
        assert sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().conta_de_servico is True

    def test_update_sem_o_campo_nao_desmarca(self, cliente, dados, sessao, autenticar):
        """
        A armadilha do exclude_unset: editar o setor de uma conta de serviço
        não pode transformá-la em pessoa de volta.
        """
        sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().conta_de_servico = True
        sessao.commit()

        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"setor_id": 1},
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 200
        assert resposta.json()["conta_de_servico"] is True

    def test_conta_de_servico_continua_autenticando(self, cliente, dados, sessao, autenticar):
        """
        A razão de o campo existir em vez de simplesmente desativar a conta:
        as três precisam fazer login.
        """
        conta = sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one()
        conta.conta_de_servico = True
        sessao.commit()

        resposta = cliente.get(
            "/api/v1/chamados/",
            headers=autenticar(dados["comum_id"], "televisao", "Usuario"),
        )

        assert resposta.status_code == 200


class TestAtribuicaoDeTecnico:
    """PUT /chamados/{id} recusa atribuir a uma conta de serviço."""

    def _marcar_como_servico(self, sessao, usuario_id):
        sessao.query(Usuario).filter(Usuario.id == usuario_id).one().conta_de_servico = True
        sessao.commit()

    def test_atribuir_a_conta_de_servico_e_recusado(self, cliente, dados, sessao, autenticar):
        self._marcar_como_servico(sessao, dados["tecnico_id"])

        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"tecnico_responsavel_id": dados["tecnico_id"]},
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 400
        assert "conta de serviço" in resposta.json()["detail"]

    def test_atribuir_a_pessoa_continua_funcionando(self, cliente, dados, autenticar):
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"tecnico_responsavel_id": dados["tecnico_id"]},
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] == dados["tecnico_id"]

    def test_editar_chamado_ja_atribuido_a_conta_de_servico_nao_trava(
        self, cliente, dados, sessao, autenticar
    ):
        """
        O motivo de a validação olhar model_fields_set e não o estado do
        chamado. Se alguém virar conta de serviço depois de já estar atribuído,
        o chamado tem de continuar editável — senão fecham-se os chamados
        justamente daquela conta.
        """
        chamado = sessao.query(Chamado).filter(Chamado.id == dados["chamado_id"]).one()
        chamado.tecnico_responsavel_id = dados["tecnico_id"]
        sessao.commit()
        self._marcar_como_servico(sessao, dados["tecnico_id"])

        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"status": "Em Andamento"},
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 200

    def test_desatribuir_continua_permitido(self, cliente, dados, sessao, autenticar):
        """None explícito é desatribuição, não tentativa de atribuir."""
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"tecnico_responsavel_id": None},
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 200
        assert resposta.json()["tecnico_responsavel_id"] is None

    def test_tecnico_inexistente_e_400_e_nao_500(self, cliente, dados, autenticar):
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"tecnico_responsavel_id": 999999},
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 400
        assert "não encontrado" in resposta.json()["detail"]
