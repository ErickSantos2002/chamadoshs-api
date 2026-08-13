"""
Quem pode administrar o quê.

Em 13/08/2026 o técnico passou a administrar **setores, categorias e prazos de
SLA**, e a auditar o cadastro que administra. **Contas de usuário continuam
exclusivas do administrador**, e a razão está em
`TestPorQueUsuarioFicaComAdministrador` — não é hierarquia, é escalonamento de
privilégio.

Este arquivo é a trava dessa fronteira. Ela precisa de teste próprio porque a
mudança que a desfaz não parece perigosa: trocar um `require_admin` por
`require_staff` em `usuarios.py` seria uma linha, pareceria consistente com o
resto da tela de Cadastros, e entregaria o sistema inteiro a qualquer técnico.

Cada permissão tem par: o que o perfil PODE e o que ele NÃO pode. Uma trava
verificada só pelo lado da recusa passaria também com uma API que recusa tudo.
"""

import pytest

from app.models import Categoria, Setor


def _admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


def _tecnico(autenticar, dados):
    return autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico")


def _comum(autenticar, dados):
    return autenticar(dados["comum_id"], "usuario.teste", "Usuario")


class TestTecnicoAdministraOsCadastrosDeApoio:
    """Setores, categorias e SLA — o que o técnico ganhou."""

    def test_cria_setor(self, cliente, dados, autenticar):
        resposta = cliente.post(
            "/api/v1/setores/", json={"nome": "Almoxarifado"},
            headers=_tecnico(autenticar, dados),
        )
        assert resposta.status_code == 201

    def test_edita_setor(self, cliente, dados, autenticar):
        resposta = cliente.put(
            "/api/v1/setores/1", json={"descricao": "Tecnologia da Informação"},
            headers=_tecnico(autenticar, dados),
        )
        assert resposta.status_code == 200

    def test_cria_categoria(self, cliente, dados, autenticar):
        resposta = cliente.post(
            "/api/v1/categorias/", json={"nome": "Rede"},
            headers=_tecnico(autenticar, dados),
        )
        assert resposta.status_code == 201

    def test_edita_categoria(self, cliente, dados, autenticar):
        resposta = cliente.put(
            "/api/v1/categorias/1", json={"nome": "Hardware e Periféricos"},
            headers=_tecnico(autenticar, dados),
        )
        assert resposta.status_code == 200

    def test_exclui_categoria(self, cliente, dados, sessao, autenticar):
        sessao.add(Categoria(id=2, nome="Sem chamados"))
        sessao.commit()

        resposta = cliente.delete(
            "/api/v1/categorias/2", headers=_tecnico(autenticar, dados)
        )
        assert resposta.status_code == 204

    def test_ajusta_prazo_de_sla(self, cliente, dados, autenticar):
        resposta = cliente.put(
            "/api/v1/sla-configs/Média",
            json={"minutos_resposta": 60, "minutos_resolucao": 480},
            headers=_tecnico(autenticar, dados),
        )
        assert resposta.status_code in (200, 404)  # 404 = prioridade sem linha, não é permissão


class TestUsuarioComumNaoAdministraNada:
    """
    O par de cima. Sem estes, a liberação para técnico poderia ter aberto tudo
    para todo mundo e os testes de permissão continuariam verdes.
    """

    @pytest.mark.parametrize(
        "metodo,caminho,corpo",
        [
            ("post", "/api/v1/setores/", {"nome": "X"}),
            ("put", "/api/v1/setores/1", {"nome": "X"}),
            ("patch", "/api/v1/setores/1/desativar", None),
            ("delete", "/api/v1/setores/1", None),
            ("post", "/api/v1/categorias/", {"nome": "X"}),
            ("put", "/api/v1/categorias/1", {"nome": "X"}),
            ("delete", "/api/v1/categorias/1", None),
            ("put", "/api/v1/sla-configs/Média", {"minutos_resposta": 1, "minutos_resolucao": 1}),
        ],
    )
    def test_recusa(self, cliente, dados, autenticar, metodo, caminho, corpo):
        chamada = getattr(cliente, metodo)
        kwargs = {"headers": _comum(autenticar, dados)}
        if corpo is not None:
            kwargs["json"] = corpo

        assert chamada(caminho, **kwargs).status_code == 403


class TestPorQueUsuarioFicaComAdministrador:
    """
    **A trava mais importante do arquivo.**

    Editar usuário inclui editar `role_id`. Um técnico com acesso a
    `PUT /usuarios/{id}` se promove a administrador em uma requisição — e daí em
    diante pode tudo, inclusive rebaixar quem o promoveu.

    É o mesmo escalonamento que o passo 0 fechou por outro caminho: lá, um
    `PUT {"ativo": false}` derrubava o último administrador pela porta ao lado
    da que o `DELETE` trancava. A forma do defeito é a mesma — uma rota que
    parece de edição comum carregando poder de mudar quem manda.
    """

    @pytest.mark.parametrize(
        "metodo,caminho,corpo",
        [
            ("post", "/api/v1/usuarios/", {"nome": "novo", "senha": "senha-123456", "role_id": 3}),
            ("put", "/api/v1/usuarios/30", {"nome": "renomeado"}),
            ("patch", "/api/v1/usuarios/30/desativar", None),
            ("patch", "/api/v1/usuarios/30/reativar", None),
            ("delete", "/api/v1/usuarios/30", None),
        ],
    )
    def test_tecnico_nao_mexe_em_conta(self, cliente, dados, autenticar, metodo, caminho, corpo):
        chamada = getattr(cliente, metodo)
        kwargs = {"headers": _tecnico(autenticar, dados)}
        if corpo is not None:
            kwargs["json"] = corpo

        assert chamada(caminho, **kwargs).status_code == 403

    def test_o_escalonamento_concreto(self, cliente, dados, sessao, autenticar):
        """
        A requisição exata que a trava impede: o técnico promovendo a si mesmo
        a administrador. Se este teste um dia passar a devolver 200, o sistema
        não tem mais níveis de acesso.
        """
        from app.models import Usuario

        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['tecnico_id']}",
            json={"role_id": 1},
            headers=_tecnico(autenticar, dados),
        )

        assert resposta.status_code == 403
        sessao.expire_all()
        assert sessao.query(Usuario).filter(Usuario.id == dados["tecnico_id"]).one().role_id == 2

    def test_administrador_continua_podendo(self, cliente, dados, autenticar):
        """O par: a trava é sobre o perfil do autor, não sobre a rota."""
        resposta = cliente.put(
            f"/api/v1/usuarios/{dados['comum_id']}",
            json={"nome": "renomeado.pelo.admin"},
            headers=_admin(autenticar, dados),
        )

        assert resposta.status_code == 200


class TestAuditoriaSegueOQueSeAdministra:
    """
    Técnico audita setor porque administra setor. Evento de conta fica com o
    administrador nos dois endpoints que o servem — ver
    `TestTecnicoSoVeTrilhaDeSetor` em test_consulta_da_trilha.py, que cobre a
    porta lateral em detalhe.
    """

    def test_tecnico_le_trilha_de_setor(self, cliente, dados, autenticar):
        resposta = cliente.get(
            "/api/v1/eventos/?alvo=setor", headers=_tecnico(autenticar, dados)
        )
        assert resposta.status_code == 200

    def test_tecnico_nao_le_trilha_de_conta(self, cliente, dados, autenticar):
        assert cliente.get(
            "/api/v1/eventos/?alvo=usuario", headers=_tecnico(autenticar, dados)
        ).status_code == 403
        assert cliente.get(
            f"/api/v1/usuarios/{dados['comum_id']}/eventos", headers=_tecnico(autenticar, dados)
        ).status_code == 403

    def test_marcar_rotina_como_realizada_exige_staff(self, cliente, dados, autenticar):
        """
        `POST /tarefas-recorrentes/{id}/realizar` exigia apenas autenticação, e
        era a única porta aberta daquele módulo — criar, editar e excluir rotina
        já pediam staff.

        A rota não só registra quem fez: ela **avança `proxima_data`**. Um
        usuário comum marcava "Backup semanal" como realizado e o cronograma da
        equipe pulava uma semana, sem backup nenhum ter acontecido e sem nada
        parecer errado na tela. A interface escondia a rota; esconder não é
        proteger.
        """
        corpo = {"observacao": "feito"}

        assert cliente.post(
            f"/api/v1/tarefas-recorrentes/{dados['tarefa_id']}/realizar",
            json=corpo, headers=_comum(autenticar, dados),
        ).status_code == 403

        assert cliente.post(
            f"/api/v1/tarefas-recorrentes/{dados['tarefa_id']}/realizar",
            json=corpo, headers=_tecnico(autenticar, dados),
        ).status_code == 200

    def test_rotinas_da_equipe_nao_sao_visiveis_a_usuario_comum(
        self, cliente, dados, autenticar
    ):
        """
        Leitura acompanha escrita no módulo de rotinas: é trabalho interno da
        equipe de TI, e o histórico de execuções diz quem fez o quê e quando.
        Confirmado com ele que nenhuma tela lista rotinas para usuário comum.
        """
        comum = _comum(autenticar, dados)
        tarefa = dados["tarefa_id"]

        assert cliente.get("/api/v1/tarefas-recorrentes/", headers=comum).status_code == 403
        assert cliente.get(f"/api/v1/tarefas-recorrentes/{tarefa}", headers=comum).status_code == 403
        assert cliente.get(
            f"/api/v1/tarefas-recorrentes/{tarefa}/execucoes", headers=comum
        ).status_code == 403

    def test_tecnico_continua_lendo_as_rotinas(self, cliente, dados, autenticar):
        """O par: a restrição não pode ter alcançado quem faz o trabalho."""
        tecnico = _tecnico(autenticar, dados)
        tarefa = dados["tarefa_id"]

        assert cliente.get("/api/v1/tarefas-recorrentes/", headers=tecnico).status_code == 200
        assert cliente.get(f"/api/v1/tarefas-recorrentes/{tarefa}", headers=tecnico).status_code == 200
        assert cliente.get(
            f"/api/v1/tarefas-recorrentes/{tarefa}/execucoes", headers=tecnico
        ).status_code == 200

    def test_diagnostico_continua_so_do_administrador(self, cliente, dados, autenticar):
        """
        Enumera contas e diz quais estão sem senha. Não entrou na liberação, e
        não deve entrar: é mapa de onde entrar, não ferramenta de cadastro.
        """
        assert cliente.get(
            "/api/v1/diagnostico/", headers=_tecnico(autenticar, dados)
        ).status_code == 403
