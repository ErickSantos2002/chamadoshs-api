"""
Testes dos PATCH de desativar/reativar em usuários e setores, e da convivência
deles com o DELETE.

O que esta entrega resolve é uma mentira de nomenclatura: `DELETE /usuarios/1`
nunca apagou nada — desativava. Enquanto o verbo diz uma coisa e o corpo faz
outra, não dá para tornar exclusão de verdade possível em cadastro nenhum sem
ambiguidade.

A entrega é aditiva de propósito: o PATCH entra dizendo no verbo o que faz, o
DELETE continua valendo e delega para o mesmo corpo. Por isso o teste central
aqui não é "o PATCH funciona", e sim **as duas rotas não divergem** — foi a
duplicação entre DELETE e PUT que, no passo 0, deixou um `PUT {"ativo": false}`
derrubar o último administrador pela porta que o DELETE trancava.

A `origem` gravada é o que separa as duas na trilha, e é ela que vai dizer
quando o frontend terminou de migrar — a pergunta que decide se o passo 4 pode
acontecer.
"""

from app.models import EventoDeConta, EventoDeSetor, Setor, Usuario


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


def _usuario(sessao, usuario_id):
    sessao.expire_all()
    return sessao.query(Usuario).filter(Usuario.id == usuario_id).one()


def _setor(sessao, setor_id):
    sessao.expire_all()
    return sessao.query(Setor).filter(Setor.id == setor_id).one()


def _setor_vazio(sessao, setor_id=2, nome="Financeiro", ativo=True):
    """Setor sem ninguém dentro: a trava de vínculo não se aplica a ele."""
    sessao.add(Setor(id=setor_id, nome=nome, ativo=ativo))
    sessao.commit()
    return setor_id


class TestUsuarioPatchEDeleteNaoDivergem:
    """
    As duas rotas fazem a mesma coisa porque compartilham o corpo. Se alguém
    reimplementar uma delas, é aqui que aparece.
    """

    def test_patch_desativa(self, cliente, dados, sessao, autenticar):
        resposta = cliente.patch(
            f"/api/v1/usuarios/{dados['comum_id']}/desativar",
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is False
        assert _usuario(sessao, dados["comum_id"]).ativo is False

    def test_patch_reativa(self, cliente, dados, sessao, autenticar):
        _usuario(sessao, dados["comum_id"]).ativo = False
        sessao.commit()

        resposta = cliente.patch(
            f"/api/v1/usuarios/{dados['comum_id']}/reativar",
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is True
        assert _usuario(sessao, dados["comum_id"]).ativo is True

    def test_patch_herda_a_trava_de_auto_desativacao(self, cliente, dados, autenticar):
        """
        A trava que impede o sistema de ficar sem administrador precisa valer na
        rota nova. Ela vale por compartilhamento de corpo, não por repetição —
        é o que impede as duas de divergirem com o tempo.
        """
        resposta = cliente.patch(
            f"/api/v1/usuarios/{dados['admin_id']}/desativar",
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert "próprio usuário" in resposta.json()["detail"]

    def test_patch_herda_a_trava_do_ultimo_administrador(
        self, cliente, dados, sessao, autenticar
    ):
        """
        O outro lado da mesma trava: um segundo admin ativo torna a desativação
        legítima. Sem este par, um teste que só verifica a recusa passaria
        também com uma rota que recusa tudo.
        """
        sessao.add(Usuario(id=11, nome="admin.outro", role_id=1, setor_id=1, ativo=True))
        sessao.commit()

        resposta = cliente.patch(
            "/api/v1/usuarios/11/desativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 200

    def test_reativar_nao_herda_as_travas(self, cliente, dados, sessao, autenticar):
        """
        Reativar é o caminho de volta do estado que as travas evitam. Aplicá-las
        aqui bloquearia a recuperação em vez do dano — inclusive a de um
        administrador, que é o caso em que a recuperação mais importa.
        """
        sessao.add(Usuario(id=11, nome="admin.outro", role_id=1, setor_id=1, ativo=False))
        sessao.commit()

        resposta = cliente.patch(
            "/api/v1/usuarios/11/reativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is True

    def test_delete_continua_com_o_contrato_antigo(self, cliente, dados, sessao, autenticar):
        """
        O frontend chama esta rota hoje. Enquanto o passo 4 não acontece, ela
        responde exatamente como antes: 204 sem corpo.
        """
        resposta = cliente.delete(
            f"/api/v1/usuarios/{dados['comum_id']}",
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 204
        assert resposta.content == b""
        assert _usuario(sessao, dados["comum_id"]).ativo is False

    def test_patch_e_delete_gravam_o_mesmo_evento(self, cliente, dados, sessao, autenticar):
        """
        Mesma ação, mesmo ator, mesmo alvo — só a `origem` difere. É essa
        diferença que mede a migração do frontend, e é o resto ser igual que
        garante que a medição não está comparando comportamentos diferentes.
        """
        headers = _como_admin(autenticar, dados)
        cliente.patch(f"/api/v1/usuarios/{dados['comum_id']}/desativar", headers=headers)
        cliente.patch(f"/api/v1/usuarios/{dados['comum_id']}/reativar", headers=headers)
        cliente.delete(f"/api/v1/usuarios/{dados['comum_id']}", headers=headers)

        sessao.expire_all()
        eventos = (
            sessao.query(EventoDeConta)
            .filter(EventoDeConta.usuario_id == dados["comum_id"])
            .order_by(EventoDeConta.id)
            .all()
        )

        por_patch, _, por_delete = eventos
        assert por_patch.acao == por_delete.acao == "desativacao"
        assert por_patch.ator_id == por_delete.ator_id == dados["admin_id"]
        assert (por_patch.valor_anterior, por_patch.valor_novo) == ("true", "false")
        assert (por_delete.valor_anterior, por_delete.valor_novo) == ("true", "false")

    def test_a_origem_separa_as_duas_rotas(self, cliente, dados, sessao, autenticar):
        """
        A consulta que decide se o passo 4 pode acontecer:

            SELECT origem, count(*) FROM eventos_de_conta
            WHERE acao = 'desativacao' GROUP BY origem;
        """
        headers = _como_admin(autenticar, dados)
        cliente.patch(f"/api/v1/usuarios/{dados['comum_id']}/desativar", headers=headers)
        cliente.patch(f"/api/v1/usuarios/{dados['comum_id']}/reativar", headers=headers)
        cliente.delete(f"/api/v1/usuarios/{dados['comum_id']}", headers=headers)

        sessao.expire_all()
        origens = [e.origem for e in sessao.query(EventoDeConta).order_by(EventoDeConta.id)]
        assert origens == [
            "PATCH /api/v1/usuarios/{id}/desativar",
            "PATCH /api/v1/usuarios/{id}/reativar",
            "DELETE /api/v1/usuarios/{id}",
        ]

    def test_desativar_quem_ja_esta_inativo_responde_sucesso_sem_evento(
        self, cliente, dados, sessao, autenticar
    ):
        """
        O estado pedido é o estado final, então a requisição deu certo. Mas
        nada mudou, e a trilha registra mudança, não requisição.
        """
        _usuario(sessao, dados["comum_id"]).ativo = False
        sessao.commit()

        resposta = cliente.patch(
            f"/api/v1/usuarios/{dados['comum_id']}/desativar",
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        sessao.expire_all()
        assert sessao.query(EventoDeConta).count() == 0

    def test_conta_inexistente_devolve_404(self, cliente, dados, autenticar):
        resposta = cliente.patch(
            "/api/v1/usuarios/9999/desativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 404

    def test_patch_e_restrito_a_administrador(self, cliente, dados, autenticar):
        resposta = cliente.patch(
            f"/api/v1/usuarios/{dados['comum_id']}/desativar",
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 403


class TestSetorPatchEDeleteNaoDivergem:
    """
    Mesmo desenho do lado de usuários. A diferença é o que espera o `DELETE` de
    setor no passo 3: lá ele passa a apagar de verdade, e o PATCH fica sendo o
    caminho para o que ele faz hoje.
    """

    def test_patch_desativa_setor_sem_usuarios(self, cliente, dados, sessao, autenticar):
        setor_id = _setor_vazio(sessao)

        resposta = cliente.patch(
            f"/api/v1/setores/{setor_id}/desativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is False
        assert _setor(sessao, setor_id).ativo is False

    def test_patch_reativa_setor(self, cliente, dados, sessao, autenticar):
        setor_id = _setor_vazio(sessao, ativo=False)

        resposta = cliente.patch(
            f"/api/v1/setores/{setor_id}/reativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is True

    def test_delete_de_setor_continua_desativando(self, cliente, dados, sessao, autenticar):
        """
        O contrato de hoje, que o passo 3 vai mudar — e é por isso que ele só
        acontece depois de o frontend migrar para o PATCH.
        """
        setor_id = _setor_vazio(sessao)

        resposta = cliente.delete(
            f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 204
        assert _setor(sessao, setor_id).ativo is False
        # Desativado, não apagado.
        assert sessao.query(Setor).filter(Setor.id == setor_id).count() == 1

    def test_a_origem_separa_as_duas_rotas(self, cliente, dados, sessao, autenticar):
        setor_id = _setor_vazio(sessao)
        headers = _como_admin(autenticar, dados)

        cliente.patch(f"/api/v1/setores/{setor_id}/desativar", headers=headers)
        cliente.patch(f"/api/v1/setores/{setor_id}/reativar", headers=headers)
        cliente.delete(f"/api/v1/setores/{setor_id}", headers=headers)

        sessao.expire_all()
        origens = [
            e.origem for e in sessao.query(EventoDeSetor).order_by(EventoDeSetor.id)
        ]
        assert origens == [
            "PATCH /api/v1/setores/{id}/desativar",
            "PATCH /api/v1/setores/{id}/reativar",
            "DELETE /api/v1/setores/{id}",
        ]

    def test_setor_inexistente_devolve_404(self, cliente, dados, autenticar):
        resposta = cliente.patch(
            "/api/v1/setores/9999/desativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 404

    def test_patch_de_setor_e_restrito_a_administrador(
        self, cliente, dados, sessao, autenticar
    ):
        setor_id = _setor_vazio(sessao)

        resposta = cliente.patch(
            f"/api/v1/setores/{setor_id}/desativar",
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 403


class TestSetorComGenteDentro:
    """
    A trava nova desta entrega.

    Setor inativo some do seletor do formulário, mas não solta quem aponta para
    ele: as contas ficam vinculadas a um setor que a tela não oferece mais, e o
    estrago aparece longe da causa — na hora de editar uma dessas pessoas.
    """

    def test_recusa_desativar_setor_com_usuarios_ativos(self, cliente, dados, sessao, autenticar):
        # O setor 1 do fixture tem os três usuários dentro.
        resposta = cliente.patch(
            "/api/v1/setores/1/desativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 400
        assert "3 usuário(s) ativo(s)" in resposta.json()["detail"]
        assert _setor(sessao, 1).ativo is True

    def test_a_trava_vale_tambem_no_put(self, cliente, dados, sessao, autenticar):
        """
        A lição do passo 0, aplicada antes de custar caro: em usuários a trava
        nasceu só no DELETE, e o `PUT {"ativo": false}` passava por cima dela.
        Aqui as duas portas compartilham a checagem desde o começo.
        """
        resposta = cliente.put(
            "/api/v1/setores/1",
            json={"ativo": False},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 400
        assert _setor(sessao, 1).ativo is True

    def test_a_trava_vale_tambem_no_delete(self, cliente, dados, sessao, autenticar):
        resposta = cliente.delete(
            "/api/v1/setores/1", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 400
        assert _setor(sessao, 1).ativo is True

    def test_usuarios_inativos_nao_impedem(self, cliente, dados, sessao, autenticar):
        """
        Setor extinto anos atrás ainda tem ex-funcionários apontando para ele, e
        esses vínculos são o histórico que não se apaga. Contá-los tornaria todo
        setor antigo indesativável — o oposto do que a trava quer.
        """
        for usuario_id in (dados["admin_id"], dados["tecnico_id"], dados["comum_id"]):
            _usuario(sessao, usuario_id).setor_id = None
        setor_id = _setor_vazio(sessao)
        sessao.add(Usuario(id=40, nome="ex.funcionario", role_id=3, setor_id=setor_id, ativo=False))
        sessao.commit()

        resposta = cliente.patch(
            f"/api/v1/setores/{setor_id}/desativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 200

    def test_setor_ja_inativo_passa_pelas_tres_rotas(self, cliente, dados, sessao, autenticar):
        """
        A regressão que passou despercebida na primeira escrita desta entrega.

        Setor inativo COM usuários ativos dentro é estado alcançável: a API
        aceita vincular alguém a setor inativo (ver
        `test_setor_inativo_ainda_e_um_setor`), e um setor pode ser desativado
        vazio e receber gente depois.

        Nesse estado, a trava não deve disparar em rota nenhuma — ninguém está
        desativando coisa alguma, o setor já está desativado. Enquanto a
        condição "só se estiver ativo" morava no chamador, o `PUT` respondia 200
        e os `PATCH`/`DELETE` respondiam 400 falando de usuários vinculados: a
        divergência entre rotas que este passo existe para eliminar, cometida
        dentro dele mesmo.
        """
        headers = _como_admin(autenticar, dados)
        sessao.add(Setor(id=2, nome="Extinto", ativo=False))
        sessao.flush()
        sessao.add(Usuario(id=40, nome="preso.no.setor", role_id=3, setor_id=2, ativo=True))
        sessao.commit()

        assert cliente.patch("/api/v1/setores/2/desativar", headers=headers).status_code == 200
        assert cliente.delete("/api/v1/setores/2", headers=headers).status_code == 204
        assert cliente.put(
            "/api/v1/setores/2", json={"ativo": False}, headers=headers
        ).status_code == 200

        # E nenhuma das três gravou evento: não houve mudança para registrar.
        sessao.expire_all()
        assert sessao.query(EventoDeSetor).count() == 0

    def test_a_trava_continua_valendo_no_setor_ativo(self, cliente, dados, sessao, autenticar):
        """
        O par do teste acima. Sem ele, a correção poderia ter sido "remover a
        trava", que faria o de cima passar e desfaria a entrega.
        """
        resposta = cliente.patch(
            "/api/v1/setores/1/desativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 400

    def test_reativar_nao_e_travado(self, cliente, dados, sessao, autenticar):
        """
        A trava existe para não deixar gente presa num setor que sumiu do
        formulário. Reativar é exatamente o que desfaz esse estado — travá-lo
        deixaria o setor 1, que tem três pessoas dentro, inalcançável de volta.
        """
        _setor(sessao, 1).ativo = False
        sessao.commit()

        resposta = cliente.patch(
            "/api/v1/setores/1/reativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 200
        assert resposta.json()["ativo"] is True
