"""
Testes da trilha de auditoria do cadastro de usuários (`eventos_de_conta`).

O que a tabela existe para responder é "quem fez o quê com qual conta, e
quando", que é pergunta de ISO 27001. Os testes daqui cobrem as três partes
dessa frase, mais o buraco que a trilha teria se fosse gravada só nas rotas
novas.

A parte mais fácil de errar não é gravar: é gravar só onde se está olhando. O
`PUT /usuarios/{id}` muda `ativo` e `role_id` e é por onde o frontend edita
cadastro hoje; o `DELETE` desativa; o `POST /auth/registro` cria conta e duplica
o `POST /usuarios/`. Cada um desses caminhos tem teste, porque cada um deles,
esquecido, produz mudança invisível — que é pior do que não ter trilha, já que
a trilha passa a ser lida como se fosse completa.
"""

from app.core.security import gerar_hash_senha
from app.models import EventoDeConta, Usuario
from app.services.evento_conta_service import (
    ACAO_ALTERACAO_DE_CONTA_DE_SERVICO,
    ACAO_ALTERACAO_DE_NOME,
    ACAO_ALTERACAO_DE_PERFIL,
    ACAO_ALTERACAO_DE_SENHA,
    ACAO_ALTERACAO_DE_SETOR,
    ACAO_CRIACAO,
    ACAO_DESATIVACAO,
    ACAO_REATIVACAO,
    SEM_VALOR,
)

SENHA_ATUAL = "senha-atual-123"


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


def _eventos(sessao, usuario_id=None):
    """Eventos gravados, na ordem em que foram criados."""
    sessao.expire_all()
    consulta = sessao.query(EventoDeConta)
    if usuario_id is not None:
        consulta = consulta.filter(EventoDeConta.usuario_id == usuario_id)
    return consulta.order_by(EventoDeConta.id).all()


def _unico(sessao, usuario_id):
    eventos = _eventos(sessao, usuario_id)
    assert len(eventos) == 1, f"esperava 1 evento, vieram {len(eventos)}"
    return eventos[0]


class TestAtorEAlvo:
    """
    A separação que dá sentido ao resto: sem o ator, o registro diz que a conta
    foi desativada e não diz por quem — que é a metade da pergunta que a
    auditoria faz.
    """

    def test_desativar_grava_quem_fez_e_em_quem(self, cliente, dados, sessao, autenticar):
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"ativo": False},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_DESATIVACAO
        assert evento.ator_id == dados["admin_id"]
        assert evento.usuario_id == dados["comum_id"]
        assert evento.created_at is not None

    def test_ator_e_alvo_sao_colunas_diferentes(self, cliente, dados, sessao, autenticar):
        """
        Guarda contra a regressão silenciosa: se as duas colunas passarem a
        receber o mesmo id, tudo continua gravando e a trilha vira inútil sem
        que nada falhe.
        """
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"ativo": False},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.ator_id != evento.usuario_id

    def test_reativar_grava_evento_proprio(self, cliente, dados, sessao, autenticar):
        sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().ativo = False
        sessao.commit()

        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"ativo": True},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_REATIVACAO
        assert (evento.valor_anterior, evento.valor_novo) == ("false", "true")


class TestDeParaSobreviveAMudancaSeguinte:
    """
    Guardar só o verbo ("perfil alterado") não permite reconstruir nada depois
    da segunda alteração. Com valor anterior e novo, a corrente se lê de trás
    para frente mesmo que o alvo continue mudando.
    """

    def test_perfil_grava_nomes_e_nao_ids(self, cliente, dados, sessao, autenticar):
        """
        Nome em vez de id: o nome congela o que o valor significava naquele
        momento. Um id exige consulta, e consulta devolve o presente.
        """
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"role_id": 2},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_ALTERACAO_DE_PERFIL
        assert (evento.valor_anterior, evento.valor_novo) == ("Usuario", "Tecnico")

    def test_duas_alteracoes_seguidas_reconstroem_a_corrente(
        self, cliente, dados, sessao, autenticar
    ):
        headers = _como_admin(autenticar, dados)
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}", json={"role_id": 2}, headers=headers
        )
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}", json={"role_id": 1}, headers=headers
        )

        eventos = _eventos(sessao, dados["comum_id"])
        assert [(e.valor_anterior, e.valor_novo) for e in eventos] == [
            ("Usuario", "Tecnico"),
            ("Tecnico", "Administrador"),
        ]

    def test_setor_vazio_vira_texto_e_nao_nulo(self, cliente, dados, sessao, autenticar):
        """
        NULL nos dois valores significa "evento sem valores" (senha). Setor
        vazio precisa de texto próprio, senão os dois casos se confundem.
        """
        sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().setor_id = None
        sessao.commit()

        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"setor_id": 1},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_ALTERACAO_DE_SETOR
        assert (evento.valor_anterior, evento.valor_novo) == (SEM_VALOR, "TI")

    def test_renomear_conta_grava_o_de_para(self, cliente, dados, sessao, autenticar):
        """`nome` é o login: renomear a conta é evento de identidade."""
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"nome": "usuario.renomeado"},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_ALTERACAO_DE_NOME
        assert (evento.valor_anterior, evento.valor_novo) == (
            "usuario.teste",
            "usuario.renomeado",
        )

    def test_conta_de_servico_grava_booleano_legivel(
        self, cliente, dados, sessao, autenticar
    ):
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"conta_de_servico": True},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_ALTERACAO_DE_CONTA_DE_SERVICO
        assert (evento.valor_anterior, evento.valor_novo) == ("false", "true")


class TestTodosOsCaminhosGravam:
    """
    O buraco que a trilha teria se só as rotas novas gravassem: o cadastro é
    editado hoje pelo PUT, e criado por duas rotas diferentes.
    """

    def test_delete_grava_o_mesmo_evento_do_put(self, cliente, dados, sessao, autenticar):
        cliente.delete(
            f"/api/v1/usuarios/{dados['comum_id']}",
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_DESATIVACAO
        assert evento.ator_id == dados["admin_id"]
        assert evento.origem == "DELETE /api/v1/usuarios/{id}"

    def test_put_e_delete_se_distinguem_pela_origem(
        self, cliente, dados, sessao, autenticar
    ):
        """
        Enquanto o DELETE e os PATCH de desativar/reativar conviverem, é a
        `origem` que diz o que o frontend ainda usa.
        """
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"ativo": False},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.origem == "PUT /api/v1/usuarios/{id}"

    def test_criar_usuario_grava_evento_de_criacao(
        self, cliente, dados, sessao, autenticar
    ):
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

        evento = _unico(sessao, resposta.json()["id"])
        assert evento.acao == ACAO_CRIACAO
        assert evento.ator_id == dados["admin_id"]
        # O nome de nascimento da conta é o começo da corrente que as
        # renomeações continuam.
        assert evento.valor_novo == "novo.usuario"
        assert evento.origem == "POST /api/v1/usuarios/"

    def test_registro_pela_rota_de_auth_tambem_grava(
        self, cliente, dados, sessao, autenticar
    ):
        """A rota duplicada, mantida por compatibilidade, não pode ser um vão."""
        resposta = cliente.post(
            "/api/v1/auth/registro",
            json={
                "nome": "criado.pelo.auth",
                "senha": "senha-inicial-123",
                "role_id": 3,
            },
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 201

        evento = _unico(sessao, resposta.json()["user_id"])
        assert evento.acao == ACAO_CRIACAO
        assert evento.origem == "POST /api/v1/auth/registro"

    def test_uma_requisicao_com_dois_campos_gera_dois_eventos(
        self, cliente, dados, sessao, autenticar
    ):
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"ativo": False, "role_id": 2},
            headers=_como_admin(autenticar, dados),
        )

        acoes = {e.acao for e in _eventos(sessao, dados["comum_id"])}
        assert acoes == {ACAO_DESATIVACAO, ACAO_ALTERACAO_DE_PERFIL}


class TestSenhaNaoEntraNaTrilha:
    """
    A trilha registra que a senha mudou, quem mudou e quando. Valor nenhum —
    nem o hash — entra nas colunas de valor.
    """

    def _com_senha(self, sessao, dados):
        usuario = sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one()
        usuario.senha_hash = gerar_hash_senha(SENHA_ATUAL)
        sessao.commit()
        return usuario

    def test_redefinicao_por_admin_grava_evento_sem_valores(
        self, cliente, dados, sessao, autenticar
    ):
        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"senha": "outra-senha-123"},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_ALTERACAO_DE_SENHA
        assert evento.valor_anterior is None
        assert evento.valor_novo is None

    def test_nem_a_senha_nem_o_hash_aparecem(self, cliente, dados, sessao, autenticar):
        usuario = self._com_senha(sessao, dados)
        hash_antigo = usuario.senha_hash

        cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"senha": "outra-senha-123"},
            headers=_como_admin(autenticar, dados),
        )

        sessao.expire_all()
        hash_novo = (
            sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().senha_hash
        )
        valores = [
            v
            for e in _eventos(sessao)
            for v in (e.valor_anterior, e.valor_novo)
            if v is not None
        ]
        for proibido in ("outra-senha-123", SENHA_ATUAL, hash_antigo, hash_novo):
            assert all(proibido not in valor for valor in valores)

    def test_troca_pela_propria_pessoa_tem_ator_igual_ao_alvo(
        self, cliente, dados, sessao, autenticar
    ):
        """
        Ator e alvo iguais, e a `origem` dizendo por qual porta passou. Quem
        classifica o evento é a segunda: ver o teste seguinte.
        """
        self._com_senha(sessao, dados)

        resposta = cliente.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": SENHA_ATUAL, "senha_nova": "outra-senha-123"},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 200

        evento = _unico(sessao, dados["comum_id"])
        assert evento.acao == ACAO_ALTERACAO_DE_SENHA
        assert evento.ator_id == evento.usuario_id == dados["comum_id"]
        assert evento.origem == "POST /api/v1/auth/alterar-senha"

    def test_admin_resetando_a_propria_senha_so_se_separa_pela_origem(
        self, cliente, dados, sessao, autenticar
    ):
        """
        O caso que torna `ator_id == usuario_id` insuficiente para classificar
        o evento: o botão de resetar senha da aba de Usuários aparece também na
        linha do próprio administrador — só o de desativar exclui a si mesmo.
        Esse reset chega por `PUT`, com ator e alvo iguais, idêntico em forma a
        uma troca própria legítima.

        E as duas são coisas diferentes em auditoria: `/auth/alterar-senha`
        exige a senha atual — "trocou sabendo a antiga" — e o `PUT` não —
        "sobrescreveu usando poder de administrador". Quem separa é a `origem`.
        """
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['admin_id']}",
            json={"senha": "outra-senha-123"},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200

        evento = _unico(sessao, dados["admin_id"])
        assert evento.acao == ACAO_ALTERACAO_DE_SENHA
        assert evento.ator_id == evento.usuario_id == dados["admin_id"]
        assert evento.origem == "PUT /api/v1/usuarios/{id}"

    def test_senha_atual_errada_nao_grava_nada(self, cliente, dados, sessao, autenticar):
        self._com_senha(sessao, dados)

        resposta = cliente.post(
            "/api/v1/auth/alterar-senha",
            json={"senha_atual": "chute-errado", "senha_nova": "outra-senha-123"},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 400
        assert _eventos(sessao) == []


class TestTrilhaRegistraMudancaNaoRequisicao:
    """
    Sem isto a trilha enche de linhas dizendo que nada aconteceu — o modal de
    usuário do frontend envia o cadastro inteiro em toda gravação. Trilha que
    não se consegue ler não é evidência de nada.
    """

    def test_reenviar_os_mesmos_valores_nao_gera_evento(
        self, cliente, dados, sessao, autenticar
    ):
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"nome": "usuario.teste", "role_id": 3, "setor_id": 1, "ativo": True},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert _eventos(sessao) == []

    def test_desativar_quem_ja_esta_inativo_nao_gera_evento(
        self, cliente, dados, sessao, autenticar
    ):
        sessao.query(Usuario).filter(Usuario.id == dados["comum_id"]).one().ativo = False
        sessao.commit()

        cliente.delete(
            f"/api/v1/usuarios/{dados['comum_id']}",
            headers=_como_admin(autenticar, dados),
        )

        assert _eventos(sessao) == []

    def test_requisicao_recusada_nao_deixa_rastro_de_mudanca(
        self, cliente, dados, sessao, autenticar
    ):
        """
        O evento e a mudança vivem na mesma transação. Uma edição barrada pelas
        travas de administrador não pode gravar evento de algo que não
        aconteceu.
        """
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['admin_id']}",
            json={"ativo": False},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert _eventos(sessao) == []


class TestTrilhaNaoCascateia:
    """
    A razão de a tabela existir separada de `historico_chamados`: lá a FK é
    `ON DELETE CASCADE`, e uma trilha que morre junto com o alvo some
    exatamente no caso em que é procurada.
    """

    def test_nenhuma_fk_tem_acao_de_exclusao(self):
        colunas = EventoDeConta.__table__.c
        for nome in ("usuario_id", "ator_id"):
            for fk in colunas[nome].foreign_keys:
                assert fk.ondelete is None, (
                    f"eventos_de_conta.{nome} ganhou ON DELETE {fk.ondelete} — "
                    "apagar a conta passaria a apagar a trilha"
                )

    def test_ator_e_alvo_sao_obrigatorios(self):
        """
        Evento sem autor não responde à pergunta da auditoria. Automação futura
        age por uma conta de serviço, que também é uma linha em `usuarios`.
        """
        colunas = EventoDeConta.__table__.c
        assert colunas["usuario_id"].nullable is False
        assert colunas["ator_id"].nullable is False
