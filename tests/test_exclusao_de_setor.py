"""
Testes do `DELETE /api/v1/setores/{id}`, que passou a excluir de verdade.

É a única mudança do plano que altera o contrato de uma rota existente, e por
isso foi a última: até a versão anterior este `DELETE` desativava, e só depois
de o frontend migrar para `PATCH .../desativar` é que ele pôde virar exclusão
sem ambiguidade.

Três assuntos aqui, e o terceiro é o que fecha o desenho inteiro:

1. **Apaga mesmo.** Trivial de escrever e fácil de errar por engano oposto —
   um `soft delete` disfarçado passaria em qualquer teste que só olhasse o
   status 204.

2. **A trava conta TODOS os vinculados, não só os ativos.** É uma trava
   diferente da de desativação, apesar do nome parecido, porque responde a
   outra pergunta: a FK `usuarios.setor_id` não distingue conta ativa de
   inativa, então um único ex-funcionário faz o banco recusar. Sem a checagem,
   isso viraria 500 do driver em vez de 400 com explicação.

3. **A trilha sobrevive ao alvo.** `eventos_de_setor` não tem FK para
   `setores` — decisão tomada lá no passo 2, quando setor ainda nem era
   apagável — exatamente para que o evento de exclusão possa ser gravado na
   mesma transação que apaga o setor. É aqui que aquela decisão para de ser
   teórica: com FK, esta transação seria impossível, e a trilha perderia o
   evento mais importante que um setor pode ter.
"""

from app.models import EventoDeSetor, Setor, Usuario
from app.services.evento_setor_service import ACAO_EXCLUSAO


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


def _existe(sessao, setor_id) -> bool:
    sessao.expire_all()
    return sessao.query(Setor).filter(Setor.id == setor_id).count() == 1


def _setor(sessao, setor_id=2, nome="Financeiro", ativo=True):
    sessao.add(Setor(id=setor_id, nome=nome, ativo=ativo))
    sessao.commit()
    return setor_id


def _usuario_no_setor(sessao, setor_id, usuario_id=40, nome="alguem", ativo=True):
    sessao.add(Usuario(id=usuario_id, nome=nome, role_id=3, setor_id=setor_id, ativo=ativo))
    sessao.commit()


class TestApagaDeVerdade:
    def test_setor_vazio_e_removido(self, cliente, dados, sessao, autenticar):
        setor_id = _setor(sessao)

        resposta = cliente.delete(
            f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 204
        assert not _existe(sessao, setor_id)

    def test_nao_e_soft_delete_disfarcado(self, cliente, dados, sessao, autenticar):
        """
        O engano oposto: devolver 204 e apenas marcar `ativo = false` passaria
        em qualquer teste que olhasse só o status, e deixaria o passo inteiro
        sem efeito.
        """
        setor_id = _setor(sessao)
        cliente.delete(f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados))

        sessao.expire_all()
        assert sessao.query(Setor).filter(Setor.id == setor_id).first() is None

    def test_setor_inativo_tambem_e_removido(self, cliente, dados, sessao, autenticar):
        """Estado do setor não importa para a exclusão; vínculo é que importa."""
        setor_id = _setor(sessao, ativo=False)

        resposta = cliente.delete(
            f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 204
        assert not _existe(sessao, setor_id)

    def test_setor_inexistente_devolve_404(self, cliente, dados, autenticar):
        resposta = cliente.delete(
            "/api/v1/setores/9999", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 404

    def test_tecnico_pode_excluir(self, cliente, dados, sessao, autenticar):
        """
        Setor passou a ser cadastro de técnico em 13/08/2026. A trilha registra
        quem apagou, então a rastreabilidade não depende do perfil.
        """
        setor_id = _setor(sessao)

        resposta = cliente.delete(
            f"/api/v1/setores/{setor_id}",
            headers=autenticar(dados["tecnico_id"], "tecnico.teste", "Tecnico"),
        )

        assert resposta.status_code == 204
        assert not _existe(sessao, setor_id)

    def test_usuario_comum_nao_pode(self, cliente, dados, sessao, autenticar):
        setor_id = _setor(sessao)

        resposta = cliente.delete(
            f"/api/v1/setores/{setor_id}",
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )

        assert resposta.status_code == 403
        assert _existe(sessao, setor_id)


class TestTravaDeVinculo:
    """
    A diferença que separa esta trava da de desativação, e que é fácil de
    escrever errado copiando a outra.
    """

    def test_usuario_ativo_impede(self, cliente, dados, sessao, autenticar):
        setor_id = _setor(sessao)
        _usuario_no_setor(sessao, setor_id)

        resposta = cliente.delete(
            f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 400
        assert _existe(sessao, setor_id)

    def test_usuario_INATIVO_tambem_impede(self, cliente, dados, sessao, autenticar):
        """
        **O teste central deste arquivo.**

        Ex-funcionário de setor extinto NÃO impede desativar — é histórico, e
        contá-lo tornaria todo setor antigo indesativável. Mas impede APAGAR,
        porque a FK `usuarios.setor_id` não distingue: o vínculo dele continua
        apontando para a linha.

        Copiar a contagem da trava de desativação (`ativo.is_(True)`) para cá
        deixaria este caso passar pela checagem e estourar no banco — 500 do
        driver, com a mensagem de FK, no lugar de um 400 explicando o que fazer.
        """
        setor_id = _setor(sessao)
        _usuario_no_setor(sessao, setor_id, nome="ex.funcionario", ativo=False)

        resposta = cliente.delete(
            f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 400
        assert "1 usuário(s) vinculado(s)" in resposta.json()["detail"]
        assert _existe(sessao, setor_id)

    def test_a_mensagem_diz_o_que_fazer(self, cliente, dados, sessao, autenticar):
        """
        Recusar sem apontar a saída deixa quem administra sem próximo passo —
        e as duas saídas são diferentes: mover as contas, ou desativar em vez
        de apagar.
        """
        setor_id = _setor(sessao)
        _usuario_no_setor(sessao, setor_id)

        detalhe = cliente.delete(
            f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados)
        ).json()["detail"]

        assert "outro setor" in detalhe
        assert "desativar" in detalhe

    def test_desativar_continua_ignorando_os_inativos(self, cliente, dados, sessao, autenticar):
        """
        O contraste explícito: o MESMO setor, com o MESMO ex-funcionário, pode
        ser desativado e não pode ser apagado. Se as duas travas forem
        unificadas por engano, um destes dois testes cai.
        """
        setor_id = _setor(sessao)
        _usuario_no_setor(sessao, setor_id, nome="ex.funcionario", ativo=False)
        headers = _como_admin(autenticar, dados)

        assert cliente.patch(
            f"/api/v1/setores/{setor_id}/desativar", headers=headers
        ).status_code == 200
        assert cliente.delete(f"/api/v1/setores/{setor_id}", headers=headers).status_code == 400

    def test_esvaziar_o_setor_libera_a_exclusao(self, cliente, dados, sessao, autenticar):
        """
        O caminho que a mensagem de erro indica, exercitado de ponta a ponta.
        Sem este teste, a trava poderia estar recusando por outro motivo.
        """
        setor_id = _setor(sessao)
        _usuario_no_setor(sessao, setor_id)
        headers = _como_admin(autenticar, dados)

        assert cliente.delete(f"/api/v1/setores/{setor_id}", headers=headers).status_code == 400

        cliente.put("/api/v1/usuarios/40", json={"setor_id": None}, headers=headers)

        assert cliente.delete(f"/api/v1/setores/{setor_id}", headers=headers).status_code == 204
        assert not _existe(sessao, setor_id)


class TestATrilhaSobreviveAoSetor:
    """
    Onde a decisão do passo 2 — alvo sem FK — para de ser teórica.
    """

    def test_a_exclusao_gera_evento(self, cliente, dados, sessao, autenticar):
        setor_id = _setor(sessao)

        cliente.delete(f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados))

        sessao.expire_all()
        eventos = sessao.query(EventoDeSetor).all()
        assert len(eventos) == 1
        assert eventos[0].acao == ACAO_EXCLUSAO
        assert eventos[0].ator_id == dados["admin_id"]

    def test_o_evento_guarda_o_nome_do_setor_que_sumiu(self, cliente, dados, sessao, autenticar):
        """
        O setor não existe mais para ser consultado. Se o nome não estivesse
        congelado na linha, a trilha diria apenas que "o setor 2" foi apagado —
        e nada permitiria saber qual era.
        """
        setor_id = _setor(sessao, nome="Compras")

        cliente.delete(f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados))

        sessao.expire_all()
        evento = sessao.query(EventoDeSetor).one()
        assert evento.setor_nome == "Compras"
        assert evento.valor_anterior == "Compras"
        assert not _existe(sessao, setor_id)

    def test_a_historia_anterior_do_setor_nao_e_apagada(self, cliente, dados, sessao, autenticar):
        """
        Com FK no alvo, apagar o setor exigiria apagar os eventos antes — ou o
        banco recusaria a exclusão. Nos dois casos a trilha perderia a história
        exatamente do setor sobre o qual mais se vai perguntar depois.
        """
        setor_id = _setor(sessao, nome="Compras")
        headers = _como_admin(autenticar, dados)

        cliente.put(f"/api/v1/setores/{setor_id}", json={"nome": "Suprimentos"}, headers=headers)
        cliente.patch(f"/api/v1/setores/{setor_id}/desativar", headers=headers)
        cliente.delete(f"/api/v1/setores/{setor_id}", headers=headers)

        sessao.expire_all()
        eventos = sessao.query(EventoDeSetor).order_by(EventoDeSetor.id).all()
        assert [e.acao for e in eventos] == ["alteracao_de_nome", "desativacao", "exclusao"]
        # A corrente inteira continua legível, do nome de origem ao fim.
        assert eventos[0].valor_anterior == "Compras"
        assert eventos[-1].valor_anterior == "Suprimentos"
        assert not _existe(sessao, setor_id)

    def test_a_exclusao_aparece_na_consulta_da_trilha(self, cliente, dados, sessao, autenticar):
        """
        A leitura pela API, não só a linha no banco: é por ela que a tela de
        auditoria responde "o que houve com o setor Compras?" depois que ele
        deixou de existir.
        """
        setor_id = _setor(sessao, nome="Compras")
        headers = _como_admin(autenticar, dados)

        cliente.delete(f"/api/v1/setores/{setor_id}", headers=headers)

        eventos = cliente.get("/api/v1/eventos/?alvo=setor", headers=headers).json()
        assert len(eventos) == 1
        assert eventos[0]["acao"] == ACAO_EXCLUSAO
        assert eventos[0]["alvo_nome"] == "Compras"
        assert eventos[0]["ator_nome"] == "admin.teste"

    def test_requisicao_recusada_nao_deixa_evento(self, cliente, dados, sessao, autenticar):
        """
        O evento e a exclusão vivem na mesma transação: uma recusa pela trava
        de vínculo não pode gravar que o setor foi apagado.
        """
        setor_id = _setor(sessao)
        _usuario_no_setor(sessao, setor_id)

        cliente.delete(f"/api/v1/setores/{setor_id}", headers=_como_admin(autenticar, dados))

        sessao.expire_all()
        assert sessao.query(EventoDeSetor).count() == 0
