"""
Testes da trilha de auditoria do cadastro de setores (`eventos_de_setor`).

A tabela é irmã de `eventos_de_conta` e responde à mesma pergunta — "quem fez o
quê com qual setor, e quando". A diferença está no alvo, e é ela que estes
testes precisam proteger.

Em `eventos_de_conta`, o alvo é FK sem ON DELETE, e o banco RECUSA apagar uma
conta que aparece na trilha. Ali isso é o ponto. Aqui seria uma armadilha: o
passo seguinte torna setor apagável de verdade, e a mesma FK faria um setor
renomeado uma vez nunca mais poder ser excluído — o evento sobreviveria ao
setor só para impedi-lo de morrer.

O que substitui a FK é o par `setor_id` + `setor_nome` congelado. Os testes de
`TestTrilhaSobreviveAoSetor` são os que provam que a substituição funciona, e
são o motivo de o passo 3 poder acontecer sem perder histórico.
"""

from app.models import EventoDeSetor, Setor
from app.services.evento_setor_service import (
    ACAO_ALTERACAO_DE_DESCRICAO,
    ACAO_ALTERACAO_DE_NOME,
    ACAO_CRIACAO,
    ACAO_DESATIVACAO,
    ACAO_REATIVACAO,
    SEM_VALOR,
)


def _como_admin(autenticar, dados):
    return autenticar(dados["admin_id"], "admin.teste", "Administrador")


def _eventos(sessao, setor_id=None):
    sessao.expire_all()
    consulta = sessao.query(EventoDeSetor)
    if setor_id is not None:
        consulta = consulta.filter(EventoDeSetor.setor_id == setor_id)
    return consulta.order_by(EventoDeSetor.id).all()


def _unico(sessao, setor_id=None):
    eventos = _eventos(sessao, setor_id)
    assert len(eventos) == 1, f"esperava 1 evento, vieram {len(eventos)}"
    return eventos[0]


def _setor_vazio(sessao, setor_id=2, nome="Financeiro", descricao=None, ativo=True):
    sessao.add(Setor(id=setor_id, nome=nome, descricao=descricao, ativo=ativo))
    sessao.commit()
    return setor_id


class TestTodosOsCaminhosGravam:
    """
    O buraco que a trilha teria se só as rotas novas gravassem: setor é criado
    e editado pelo POST e pelo PUT, que são o que o frontend usa hoje.
    """

    def test_criar_setor_grava_evento(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/setores/",
            json={"nome": "Compras", "descricao": "Setor de compras"},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 201

        evento = _unico(sessao, resposta.json()["id"])
        assert evento.acao == ACAO_CRIACAO
        assert evento.ator_id == dados["admin_id"]
        # O nome de nascimento é o começo da corrente que as renomeações
        # continuam.
        assert evento.valor_novo == "Compras"
        assert evento.origem == "POST /api/v1/setores/"

    def test_put_grava_alteracao(self, cliente, dados, sessao, autenticar):
        setor_id = _setor_vazio(sessao)

        cliente.put(
            f"/api/v1/setores/{setor_id}",
            json={"nome": "Financeiro e Contabilidade"},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, setor_id)
        assert evento.acao == ACAO_ALTERACAO_DE_NOME
        assert (evento.valor_anterior, evento.valor_novo) == (
            "Financeiro",
            "Financeiro e Contabilidade",
        )
        assert evento.origem == "PUT /api/v1/setores/{id}"

    def test_patch_desativar_grava(self, cliente, dados, sessao, autenticar):
        setor_id = _setor_vazio(sessao)

        cliente.patch(
            f"/api/v1/setores/{setor_id}/desativar", headers=_como_admin(autenticar, dados)
        )

        evento = _unico(sessao, setor_id)
        assert evento.acao == ACAO_DESATIVACAO
        assert (evento.valor_anterior, evento.valor_novo) == ("true", "false")

    def test_patch_reativar_grava(self, cliente, dados, sessao, autenticar):
        setor_id = _setor_vazio(sessao, ativo=False)

        cliente.patch(
            f"/api/v1/setores/{setor_id}/reativar", headers=_como_admin(autenticar, dados)
        )

        evento = _unico(sessao, setor_id)
        assert evento.acao == ACAO_REATIVACAO
        assert (evento.valor_anterior, evento.valor_novo) == ("false", "true")

    def test_descricao_vazia_vira_texto_e_nao_nulo(self, cliente, dados, sessao, autenticar):
        setor_id = _setor_vazio(sessao)

        cliente.put(
            f"/api/v1/setores/{setor_id}",
            json={"descricao": "Contas a pagar e receber"},
            headers=_como_admin(autenticar, dados),
        )

        evento = _unico(sessao, setor_id)
        assert evento.acao == ACAO_ALTERACAO_DE_DESCRICAO
        assert (evento.valor_anterior, evento.valor_novo) == (
            SEM_VALOR,
            "Contas a pagar e receber",
        )

    def test_uma_requisicao_com_dois_campos_gera_dois_eventos(
        self, cliente, dados, sessao, autenticar
    ):
        setor_id = _setor_vazio(sessao)

        cliente.put(
            f"/api/v1/setores/{setor_id}",
            json={"nome": "Fin", "descricao": "nova"},
            headers=_como_admin(autenticar, dados),
        )

        acoes = {e.acao for e in _eventos(sessao, setor_id)}
        assert acoes == {ACAO_ALTERACAO_DE_NOME, ACAO_ALTERACAO_DE_DESCRICAO}


class TestTrilhaRegistraMudancaNaoRequisicao:
    """Mesma regra da trilha de contas: linha só quando algo mudou."""

    def test_reenviar_os_mesmos_valores_nao_gera_evento(
        self, cliente, dados, sessao, autenticar
    ):
        setor_id = _setor_vazio(sessao, descricao="original")

        resposta = cliente.put(
            f"/api/v1/setores/{setor_id}",
            json={"nome": "Financeiro", "descricao": "original", "ativo": True},
            headers=_como_admin(autenticar, dados),
        )

        assert resposta.status_code == 200
        assert _eventos(sessao) == []

    def test_requisicao_recusada_nao_deixa_rastro(self, cliente, dados, sessao, autenticar):
        """
        O evento e a mudança vivem na mesma transação. O setor 1 tem três
        usuários ativos, então a desativação é barrada — e nada pode ficar
        gravado dizendo que ela aconteceu.
        """
        resposta = cliente.patch(
            "/api/v1/setores/1/desativar", headers=_como_admin(autenticar, dados)
        )

        assert resposta.status_code == 400
        assert _eventos(sessao) == []


class TestTrilhaSobreviveAoSetor:
    """
    A razão de esta tabela existir separada da de contas, e o que o passo 3
    depende para não perder histórico.
    """

    def test_o_alvo_nao_tem_foreign_key(self):
        """
        Guarda estrutural, e a mais importante do arquivo.

        Uma FK aqui pareceria uma melhoria — "o alvo devia apontar para
        setores" — e só cobraria o preço no passo 3, quando o hard delete
        começasse a ser recusado pelo banco por causa de eventos antigos. O
        SQLite dos testes nem sequer aplica FK por padrão, então o teste
        funcional abaixo passaria mesmo com ela declarada: quem pega esse caso é
        esta asserção.
        """
        assert EventoDeSetor.__table__.c["setor_id"].foreign_keys == set(), (
            "eventos_de_setor.setor_id ganhou uma FK — o hard delete de setor "
            "do passo 3 passa a ser recusado pelo banco assim que o setor "
            "tiver qualquer evento"
        )

    def test_o_ator_mantem_a_foreign_key(self):
        """
        A metade que continua valendo: quem agiu não pode evaporar da trilha.
        Não há conflito com o hard delete, porque quem se apaga é o setor.
        """
        fks = EventoDeSetor.__table__.c["ator_id"].foreign_keys
        assert len(fks) == 1
        for fk in fks:
            assert fk.ondelete is None, (
                f"eventos_de_setor.ator_id ganhou ON DELETE {fk.ondelete} — "
                "apagar a conta passaria a apagar a trilha"
            )

    def test_ator_e_alvo_sao_obrigatorios(self):
        colunas = EventoDeSetor.__table__.c
        assert colunas["setor_id"].nullable is False
        assert colunas["ator_id"].nullable is False
        # Sem o nome congelado, um setor apagado deixaria a trilha como uma
        # lista de ids órfãos.
        assert colunas["setor_nome"].nullable is False

    def test_evento_continua_legivel_depois_de_o_setor_sumir(
        self, cliente, dados, sessao, autenticar
    ):
        """
        O ensaio do passo 3: apagar a linha de `setores` e conferir que a
        trilha continua dizendo o que era aquele setor.
        """
        setor_id = _setor_vazio(sessao)
        cliente.patch(
            f"/api/v1/setores/{setor_id}/desativar", headers=_como_admin(autenticar, dados)
        )

        sessao.query(Setor).filter(Setor.id == setor_id).delete()
        sessao.commit()

        evento = _unico(sessao, setor_id)
        assert evento.setor_nome == "Financeiro"
        assert evento.acao == ACAO_DESATIVACAO
        assert evento.setor_id == setor_id

    def test_renomear_nao_reescreve_a_historia(self, cliente, dados, sessao, autenticar):
        """
        O nome é copiado para dentro do evento, não resolvido na leitura. Dois
        eventos separados por uma renomeação continuam mostrando o de/para,
        enquanto um join com `setores` mostraria o nome atual nos dois.
        """
        setor_id = _setor_vazio(sessao)
        headers = _como_admin(autenticar, dados)

        cliente.patch(f"/api/v1/setores/{setor_id}/desativar", headers=headers)
        cliente.put(
            f"/api/v1/setores/{setor_id}", json={"nome": "Financeiro (extinto)"}, headers=headers
        )

        desativacao, renomeacao = _eventos(sessao, setor_id)
        assert desativacao.setor_nome == "Financeiro"
        assert (renomeacao.valor_anterior, renomeacao.valor_novo) == (
            "Financeiro",
            "Financeiro (extinto)",
        )
        # O evento da renomeação fica sob o nome NOVO: procurar o setor pelo
        # nome atual encontra também o momento em que ele passou a se chamar
        # assim.
        assert renomeacao.setor_nome == "Financeiro (extinto)"
