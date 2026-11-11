"""
A versão do chamado pelas rotas e pelo ORM, em PostgreSQL real (API-4a).

Os mesmos fixtures da suíte (`dados`, `qualidade`, `cliente`, `autenticar`),
com uma troca só: o `sessao` daqui é um PostgreSQL descartável criado a partir
do `schema_chamados.sql`, com o trigger da versão. Assim cada rota é a de
produção, e a contagem é a do trigger — não uma imitação.

Também prova que o `schema_chamados.sql` (banco novo) e a migration (banco
existente) instalam o mesmo trigger: a migration, rodada num banco criado pelo
schema, responde "já aplicada".

Aqui só se prova que ela sobe uma vez por escrita e que a resposta devolve a
versão já gravada. As escritas da Qualidade mandam `versao_esperada`, que
desde a API-4b elas exigem; a conferência em si está em
`test_precondicao_de_versao_postgres.py`.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Chamado
from pg_descartavel import banco_descartavel, executar_script, ler

pytestmark = pytest.mark.postgres

SOLUCAO_OK = "Laudo reemitido com a assinatura do responsável"


@pytest.fixture(scope="module")
def banco_novo():
    """
    Banco criado só pelo `schema_chamados.sql`. Os cadastros semeados por ele
    saem: os fixtures da suíte gravam os seus, com ids fixos.
    """
    with banco_descartavel("modelo_versao_api") as url:
        executar_script(url, ler("schema_chamados.sql"))
        executar_script(url, "TRUNCATE roles, setores, categorias RESTART IDENTITY CASCADE")
        yield url


@pytest.fixture
def sessao(banco_novo):
    """Substitui o `sessao` SQLite do conftest por uma cópia nova do banco acima."""
    with banco_descartavel(modelo=banco_novo) as url:
        engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://", 1))
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()
            engine.dispose()


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _no_banco(sessao, chamado_id) -> int:
    """A versão gravada, lida por SQL — sem passar pelo objeto em memória."""
    sessao.rollback()
    return sessao.execute(text("SELECT versao FROM chamados WHERE id = :id"), {"id": chamado_id}).scalar_one()


def _responde_e_grava(resposta, sessao, versao, status=200):
    assert resposta.status_code == status, resposta.text
    corpo = resposta.json()
    assert corpo["versao"] == versao
    assert _no_banco(sessao, corpo["id"]) == versao
    return corpo


def test_schema_e_migration_instalam_o_mesmo_trigger(banco_novo):
    avisos = executar_script(banco_novo, ler("migrations/2026-10-28-add-versao-chamados.sql"))
    assert any("já aplicada" in a for a in avisos), avisos


class TestPeloOrm:
    def test_o_objeto_em_memoria_relê_a_versao_depois_do_flush(self, dados, sessao):
        """
        `server_onupdate=FetchedValue()`: sem ele, `chamado.versao` seguiria 1
        depois do UPDATE, dentro da mesma transação, até um refresh manual.
        """
        chamado = sessao.get(Chamado, dados["chamado_id"])
        assert chamado.versao == 1
        chamado.status = "Em Andamento"
        sessao.flush()
        assert chamado.versao == 2
        sessao.commit()
        assert chamado.versao == 2

    def test_versao_atribuida_no_objeto_e_ignorada_pelo_banco(self, dados, sessao):
        chamado = sessao.get(Chamado, dados["chamado_id"])
        chamado.prioridade = "Alta"
        chamado.versao = 40  # vai no UPDATE, e o trigger a descarta
        sessao.commit()
        assert chamado.versao == 2

    def test_commit_sem_mudanca_nao_sobe(self, dados, sessao):
        chamado = sessao.get(Chamado, dados["chamado_id"])
        chamado.status = chamado.status
        sessao.commit()
        assert _no_banco(sessao, dados["chamado_id"]) == 1

    def test_rollback_do_orm_preserva_a_versao(self, dados, sessao):
        chamado = sessao.get(Chamado, dados["chamado_id"])
        chamado.status = "Aguardando"
        sessao.flush()
        sessao.rollback()
        assert _no_banco(sessao, dados["chamado_id"]) == 1


class TestPelasRotas:
    def test_criacao_comeca_em_1(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/chamados/",
            json={
                "titulo": "Impressora do RH não liga",
                "descricao": "Não dá sinal de vida desde ontem à tarde",
                "categoria_id": 1,
                "solicitante_id": dados["comum_id"],
            },
            headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
        )
        _responde_e_grava(resposta, sessao, 1, status=201)

    def test_put_sobe_1_e_a_resposta_ja_traz_a_nova(self, cliente, dados, sessao, autenticar):
        url = f"/api/v1/chamados/{dados['chamado_id']}"
        _responde_e_grava(cliente.put(url, json={"status": "Em Andamento"}, headers=_admin(autenticar, dados)), sessao, 2)
        _responde_e_grava(
            cliente.put(url, json={"prioridade": "Alta", "solucao": None}, headers=_admin(autenticar, dados)),
            sessao,
            3,
        )

    def test_put_com_os_mesmos_valores_nao_sobe(self, cliente, dados, sessao, autenticar):
        """O que a edição completa da TI faz em todo salvamento: reenviar o que já está lá."""
        url = f"/api/v1/chamados/{dados['chamado_id']}"
        _responde_e_grava(
            cliente.put(url, json={"status": "Aberto", "prioridade": "Média"}, headers=_admin(autenticar, dados)),
            sessao,
            1,
        )

    def test_put_de_varios_campos_sobe_1(self, cliente, dados, sessao, autenticar):
        _responde_e_grava(
            cliente.put(
                f"/api/v1/chamados/{dados['chamado_id']}",
                json={"status": "Resolvido", "solucao": "Troquei o cabo de força.", "prioridade": "Baixa"},
                headers=_admin(autenticar, dados),
            ),
            sessao,
            2,
        )

    def test_detalhe_e_listagem_mostram_a_versao_gravada(self, cliente, dados, sessao, autenticar):
        cliente.put(f"/api/v1/chamados/{dados['chamado_id']}", json={"status": "Aguardando"}, headers=_admin(autenticar, dados))

        detalhe = cliente.get(f"/api/v1/chamados/{dados['chamado_id']}", headers=_admin(autenticar, dados))
        listagem = cliente.get("/api/v1/chamados/", headers=_admin(autenticar, dados))

        assert detalhe.json()["versao"] == 2
        assert [c["versao"] for c in listagem.json() if c["id"] == dados["chamado_id"]] == [2]

    def test_atendimento_sobe_1(self, cliente, chamado_qualidade_do_tecnico, sessao, autenticar):
        # API-13: quem atende é o Técnico da Qualidade, e não mais a ana (comum).
        d = chamado_qualidade_do_tecnico
        atendente = autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico")
        url = f"/api/v1/chamados/{d['chamado_qualidade_id']}/atendimento"

        # A versão de cada escrita é a devolvida pela anterior, como o cliente faz.
        primeira = _responde_e_grava(
            cliente.patch(url, json={"status": "Em Andamento", "versao_esperada": 1}, headers=atendente), sessao, 2
        )
        _responde_e_grava(
            cliente.patch(
                url,
                json={"status": "Resolvido", "solucao": SOLUCAO_OK, "versao_esperada": primeira["versao"]},
                headers=atendente,
            ),
            sessao,
            3,
        )

    def test_atendimento_recusado_nao_sobe(self, cliente, chamado_qualidade_do_tecnico, sessao, autenticar):
        d = chamado_qualidade_do_tecnico
        resposta = cliente.patch(
            f"/api/v1/chamados/{d['chamado_qualidade_id']}/atendimento",
            # Aberto → Resolvido: 409 de transição, com a versão certa.
            json={"status": "Resolvido", "solucao": SOLUCAO_OK, "versao_esperada": 1},
            headers=autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico"),
        )
        assert resposta.status_code == 409
        assert "codigo" not in resposta.json()
        assert _no_banco(sessao, d["chamado_qualidade_id"]) == 1

    def test_reatribuicao_da_qualidade_sobe_1(self, cliente, chamado_qualidade, sessao, autenticar):
        d = chamado_qualidade
        _responde_e_grava(
            cliente.put(
                f"/api/v1/chamados/{d['chamado_qualidade_id']}",
                json={"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": 1},
                headers=_admin(autenticar, d),
            ),
            sessao,
            2,
        )

    def test_cancelar_arquivar_e_desarquivar_sobem_1_cada(self, cliente, dados, sessao, autenticar):
        base = f"/api/v1/chamados/{dados['chamado_id']}"
        admin = _admin(autenticar, dados)
        _responde_e_grava(cliente.patch(f"{base}/arquivar", headers=admin), sessao, 2)
        _responde_e_grava(cliente.patch(f"{base}/desarquivar", headers=admin), sessao, 3)
        _responde_e_grava(cliente.patch(f"{base}/cancelar", headers=admin), sessao, 4)

    def test_avaliar_sobe_1(self, cliente, dados, sessao, autenticar):
        cliente.put(f"/api/v1/chamados/{dados['chamado_id']}", json={"status": "Resolvido"}, headers=_admin(autenticar, dados))
        _responde_e_grava(
            cliente.patch(
                f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
                json={"avaliacao": 4},
                headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
            ),
            sessao,
            3,
        )

    def test_comentario_nao_sobe_a_versao_do_chamado(self, cliente, dados, sessao, autenticar):
        resposta = cliente.post(
            "/api/v1/comentarios/",
            json={"chamado_id": dados["chamado_id"], "comentario": "Passei no RH, volto à tarde."},
            headers=_admin(autenticar, dados),
        )
        assert resposta.status_code in (200, 201), resposta.text
        assert _no_banco(sessao, dados["chamado_id"]) == 1
