"""
Testes do invariante de autoria: quem assina a ação é sempre o dono do token.

Antes da entrega de segurança, o autor vinha do corpo ou da query string — o
histórico registrava quem o chamador dissesse ser. Hoje o valor recebido é
ignorado e vale o id do token, mas até aqui isso só estava coberto no nível do
helper de aviso e dos schemas. Nenhum teste provava o que efetivamente chega ao
banco.

Essa prova importa porque a remoção do parâmetro `usuario_id` (Tarefa 4) mexe
exatamente nestes caminhos. Com estes testes, a remoção é verificável; sem
eles, seria confiada.

Cada teste manda `usuario_id` de OUTRA pessoa de propósito: é a tentativa de
forjar autoria que precisa falhar.
"""

from app.models import ComentarioChamado, HistoricoChamado
from app.models.tarefa_recorrente import TarefaRecorrenteExecucao


class TestComentario:
    """POST /api/v1/comentarios/ — usuario_id é campo do corpo."""

    def test_usuario_id_do_corpo_e_ignorado(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/comentarios/",
            json={
                "chamado_id": dados["chamado_id"],
                "comentario": "tentando assinar como outra pessoa",
                "usuario_id": dados["admin_id"],
            },
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 201
        assert resposta.json()["usuario_id"] == dados["comum_id"]

        gravado = sessao.query(ComentarioChamado).one()
        assert gravado.usuario_id == dados["comum_id"]

    def test_sem_usuario_id_funciona(self, cliente, dados, sessao, autenticar):
        """
        O estado final desejado, depois de o frontend parar de enviar. Já
        funciona hoje — é o que permite remover as seis chamadas do frontend
        numa rodada só, sem esperar mudança no backend.
        """
        resposta = cliente.post(
            "/api/v1/comentarios/",
            json={"chamado_id": dados["chamado_id"], "comentario": "sem autoria no corpo"},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 201
        assert sessao.query(ComentarioChamado).one().usuario_id == dados["comum_id"]

    def test_comentario_interno_exige_perfil(self, cliente, dados, sessao, autenticar):
        """is_interno é a marcação que esconde o comentário do solicitante."""
        resposta = cliente.post(
            "/api/v1/comentarios/",
            json={
                "chamado_id": dados["chamado_id"],
                "comentario": "interno",
                "is_interno": True,
            },
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 403
        assert sessao.query(ComentarioChamado).count() == 0

    def test_tecnico_pode_criar_comentario_interno(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/comentarios/",
            json={
                "chamado_id": dados["chamado_id"],
                "comentario": "interno",
                "is_interno": True,
            },
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 201
        assert sessao.query(ComentarioChamado).one().usuario_id == dados["tecnico_id"]


class TestAtualizarChamado:
    """PUT /api/v1/chamados/{id} — usuario_id vem na query string."""

    def test_historico_registra_o_dono_do_token(self, cliente, dados, sessao, autenticar):
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}?usuario_id={dados['admin_id']}",
            json={"status": "Em Andamento"},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 200

        historicos = sessao.query(HistoricoChamado).all()
        assert historicos, "a atualização precisa deixar rastro no histórico"
        assert all(h.usuario_id == dados["tecnico_id"] for h in historicos)

    def test_usuario_comum_nao_atualiza_chamado(self, cliente, dados, autenticar):
        """O endpoint é restrito a administrador ou técnico (require_staff)."""
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"status": "Em Andamento"},
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 403


class TestRealizarTarefaRecorrente:
    """POST /api/v1/tarefas-recorrentes/{id}/realizar — usuario_id no corpo."""

    def test_execucao_fica_no_nome_do_dono_do_token(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            f"/api/v1/tarefas-recorrentes/{dados['tarefa_id']}/realizar",
            json={"usuario_id": dados["admin_id"], "observacao": "feito"},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 200

        execucao = sessao.query(TarefaRecorrenteExecucao).one()
        assert execucao.usuario_id == dados["tecnico_id"]

    def test_sem_usuario_id_funciona(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            f"/api/v1/tarefas-recorrentes/{dados['tarefa_id']}/realizar",
            json={"observacao": "feito"},
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 200
        assert sessao.query(TarefaRecorrenteExecucao).one().usuario_id == dados["tecnico_id"]


class TestAutenticacaoObrigatoria:
    """Sem token não se escreve nada — a regra que a entrega de segurança pôs."""

    def test_comentario_sem_token_e_401(self, cliente, dados, sessao):
        resposta = cliente.post(
            "/api/v1/comentarios/",
            json={"chamado_id": dados["chamado_id"], "comentario": "anônimo"},
        )

        assert resposta.status_code == 401
        assert sessao.query(ComentarioChamado).count() == 0

    def test_realizar_tarefa_sem_token_e_401(self, cliente, dados, sessao):
        resposta = cliente.post(
            f"/api/v1/tarefas-recorrentes/{dados['tarefa_id']}/realizar",
            json={"observacao": "anônimo"},
        )

        assert resposta.status_code == 401
        assert sessao.query(TarefaRecorrenteExecucao).count() == 0
