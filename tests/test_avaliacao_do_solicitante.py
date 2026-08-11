"""
Testes do PATCH /api/v1/chamados/{id}/avaliar.

Esta rota existe por causa de um bug de produção: o widget de estrelas salvava
via PUT /chamados/{id}, e o PUT virou `require_staff` quando a autorização foi
ligada. O solicitante — a única pessoa que deveria avaliar — passou a levar 403.

A correção não podia ser afrouxar o PUT, porque por ele o solicitante mexeria em
status, prioridade e técnico responsável do próprio chamado. Daí a rota
dedicada, com um campo gravável só.

Por isso a suíte cobre duas coisas distintas, e as duas importam:
o caminho feliz (o solicitante consegue avaliar de novo) e o escopo
(esta rota não virou uma porta lateral para o que o PUT protege).
"""

from app.models import Chamado, HistoricoChamado


def resolver(sessao, chamado_id, status="Resolvido"):
    """Coloca o chamado num estado avaliável, que é o pré-requisito da rota."""
    chamado = sessao.query(Chamado).filter(Chamado.id == chamado_id).one()
    chamado.status = status
    sessao.commit()


class TestSolicitanteAvalia:
    """O caminho que estava quebrado em produção."""

    def test_solicitante_avalia_chamado_resolvido(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 200
        assert resposta.json()["avaliacao"] == 5
        assert sessao.query(Chamado).one().avaliacao == 5

    def test_solicitante_avalia_chamado_fechado(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"], status="Fechado")

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 3},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 200
        assert sessao.query(Chamado).one().avaliacao == 3

    def test_reavaliacao_substitui_a_nota(self, cliente, dados, sessao, autenticar):
        """
        Trocar a nota é permitido: a pessoa clica numa estrela errada e corrige.
        Travar a primeira nota transformaria um clique errado em suporte.
        """
        resolver(sessao, dados["chamado_id"])
        headers = autenticar(dados["comum_id"], "usuario.teste", "Usuario")
        url = f"/api/v1/chamados/{dados['chamado_id']}/avaliar"

        assert cliente.patch(url, json={"avaliacao": 1}, headers=headers).status_code == 200
        assert cliente.patch(url, json={"avaliacao": 4}, headers=headers).status_code == 200

        assert sessao.query(Chamado).one().avaliacao == 4

    def test_avaliacao_deixa_rastro_no_historico(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        historico = sessao.query(HistoricoChamado).one()
        assert historico.usuario_id == dados["comum_id"]
        assert historico.chamado_id == dados["chamado_id"]


class TestSoOSolicitanteAvalia:
    """
    A nota mede o atendimento que a equipe prestou. Se a própria equipe puder
    preenchê-la, o indicador não mede mais nada — por isso nem admin nem
    técnico avaliam no lugar do solicitante.
    """

    def test_outro_usuario_comum_recebe_403(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5},
            headers=autenticar(dados["admin_id"], "admin.teste", "Usuario"),
        )

        assert resposta.status_code == 403
        assert sessao.query(Chamado).one().avaliacao is None

    def test_admin_recebe_403(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5},
            headers=autenticar(dados["admin_id"], "admin.teste", "Administrador"),
        )

        assert resposta.status_code == 403
        assert sessao.query(Chamado).one().avaliacao is None

    def test_tecnico_recebe_403(self, cliente, dados, sessao, autenticar):
        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 403
        assert sessao.query(Chamado).one().avaliacao is None

    def test_sem_token_e_401(self, cliente, dados, sessao):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5},
        )

        assert resposta.status_code == 401
        assert sessao.query(Chamado).one().avaliacao is None


class TestEstadoDoChamado:
    """Avaliar antes do fim do atendimento é 409, não 400: o corpo está certo."""

    def test_chamado_aberto_e_409(self, cliente, dados, sessao, autenticar):
        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 409
        assert sessao.query(Chamado).one().avaliacao is None

    def test_chamado_em_andamento_e_409(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"], status="Em Andamento")

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 409

    def test_chamado_inexistente_e_404(self, cliente, dados, autenticar):
        resposta = cliente.patch(
            "/api/v1/chamados/999999/avaliar",
            json={"avaliacao": 5},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 404


class TestFaixaDaNota:
    """
    A coluna tem CHECK (avaliacao >= 1 AND avaliacao <= 5). Sem validação no
    schema, uma nota fora da faixa só falharia no commit — 500 em vez de 422.
    """

    def test_nota_zero_e_422(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 0},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 422
        assert sessao.query(Chamado).one().avaliacao is None

    def test_nota_seis_e_422(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 6},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 422
        assert sessao.query(Chamado).one().avaliacao is None

    def test_corpo_vazio_e_422(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 422


class TestEscopoDaRota:
    """
    A razão de a rota existir: ela não pode dar ao solicitante o que o
    `require_staff` do PUT protege. Se um dia alguém trocar `ChamadoAvaliacao`
    por `ChamadoUpdate` "para reaproveitar", estes testes caem.
    """

    def test_status_no_corpo_e_ignorado(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={"avaliacao": 5, "status": "Aberto"},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 200
        assert sessao.query(Chamado).one().status == "Resolvido"

    def test_prioridade_e_tecnico_no_corpo_sao_ignorados(self, cliente, dados, sessao, autenticar):
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.patch(
            f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
            json={
                "avaliacao": 5,
                "prioridade": "Crítica",
                "tecnico_responsavel_id": dados["tecnico_id"],
            },
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 200

        chamado = sessao.query(Chamado).one()
        assert chamado.prioridade == "Média"
        assert chamado.tecnico_responsavel_id is None

    def test_put_continua_fechado_para_o_solicitante(self, cliente, dados, sessao, autenticar):
        """
        A trava que motivou a rota nova continua de pé. Se este teste passar a
        falhar, a correção virou o problema que ela deveria evitar.
        """
        resolver(sessao, dados["chamado_id"])

        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"avaliacao": 5},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 403
