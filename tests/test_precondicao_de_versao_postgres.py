"""
Pré-condição de versão (API-4b) em PostgreSQL real: contagem, atomicidade e
o lock.

O que o SQLite não prova e aqui se prova:

- a versão sobe uma vez por escrita aceita, e a recusa (428/409) não executa
  UPDATE nenhum — `updated_at`, que o trigger reescreve em todo UPDATE, fica
  igual;
- falha de verdade no commit (chave estrangeira) desfaz chamado e histórico
  juntos, no PUT e nas marcas da Qualidade;
- a escrita da Qualidade espera o lock de outra transação e, quando ele sai,
  confere a versão GRAVADA por ela — e recusa, em vez de sobrescrever;
- a TI não pede o lock;
- recusa não deixa a linha travada.

Os testes de concorrência são pontuais: um caso por rota, para mostrar que a
conferência é feita sob o lock. A matriz completa de duas sessões é da API-4c.
"""

import psycopg2
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import main
from app.api.deps import get_db
from app.api.endpoints import chamados as chamados_endpoint
from app.services.versao_service import VERSAO_AUSENTE, VERSAO_DESATUALIZADA
from concorrencia import LOCK_TIMEOUT_DOS_TESTES, em_paralelo, esperar_bloqueio, pid_de, sql_emitido
from pg_descartavel import banco_descartavel, executar_script, ler

pytestmark = pytest.mark.postgres

SOLUCAO_OK = "Laudo reemitido com a assinatura do responsável"
QUALIDADE = 101


@pytest.fixture(scope="module")
def banco_novo():
    with banco_descartavel("modelo_precondicao") as url:
        executar_script(url, ler("schema_chamados.sql"))
        executar_script(url, "TRUNCATE roles, setores, categorias RESTART IDENTITY CASCADE")
        yield url


@pytest.fixture
def url_do_banco(banco_novo):
    with banco_descartavel(modelo=banco_novo) as url:
        yield url


@pytest.fixture
def sessao(url_do_banco):
    engine = create_engine(
        url_do_banco.replace("postgresql://", "postgresql+psycopg2://", 1),
        # Teto de espera por lock, bem acima das esperas do teste (`concorrencia.py`):
        # nenhum teste depende de o lock_timeout estourar.
        connect_args={"options": f"-c lock_timeout={LOCK_TIMEOUT_DOS_TESTES}"},
    )
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def cliente(sessao):
    """
    Como o do conftest, mas desfazendo o que sobrar no fim de cada requisição —
    o que o `db.close()` do `get_db` real faz. Sem isso, uma recusa deixaria a
    transação aberta e a linha travada na sessão do teste.
    """
    from fastapi.testclient import TestClient

    def _get_db_de_teste():
        try:
            yield sessao
        finally:
            sessao.rollback()

    main.app.dependency_overrides[get_db] = _get_db_de_teste
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


@pytest.fixture
def outra_conexao(url_do_banco):
    """Uma segunda transação, fora da API: a "outra pessoa"."""
    conexao = psycopg2.connect(url_do_banco)
    try:
        yield conexao
    finally:
        conexao.rollback()
        conexao.close()


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _atendente(autenticar, d):
    return autenticar(d["atendente_id"], "ana.qualidade", "Usuario")


def _estado(sessao, chamado_id):
    """Lido por SQL, sem passar pelo objeto em memória."""
    sessao.rollback()
    linha = sessao.execute(
        text(
            "SELECT status, prioridade, tecnico_responsavel_id, cancelado, arquivado, versao, updated_at "
            "FROM chamados WHERE id = :id"
        ),
        {"id": chamado_id},
    ).mappings().one()
    historicos = sessao.execute(
        text(
            "SELECT acao, status_anterior, status_novo FROM historico_chamados "
            "WHERE chamado_id = :id ORDER BY id"
        ),
        {"id": chamado_id},
    ).all()
    return {**linha, "historicos": [tuple(h) for h in historicos]}


def _put(cliente, chamado_id, corpo, headers):
    return cliente.put(f"/api/v1/chamados/{chamado_id}", json=corpo, headers=headers)


def _atender(cliente, corpo, headers):
    return cliente.patch(f"/api/v1/chamados/{QUALIDADE}/atendimento", json=corpo, headers=headers)


def _marca(cliente, rota, corpo, headers, chamado_id=QUALIDADE):
    return cliente.patch(f"/api/v1/chamados/{chamado_id}/{rota}", json=corpo, headers=headers)


def _desatualizada(versao_atual):
    return {"detail": VERSAO_DESATUALIZADA, "codigo": "versao_desatualizada", "versao_atual": versao_atual}


class TestPutDaQualidade:
    def test_versao_certa_grava_sobe_1_e_registra_o_status_anterior(
        self, cliente, chamado_qualidade, sessao, autenticar
    ):
        resposta = _put(
            cliente, QUALIDADE, {"status": "Em Andamento", "versao_esperada": 1}, _admin(autenticar, chamado_qualidade)
        )

        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["versao"] == 2
        estado = _estado(sessao, QUALIDADE)
        assert (estado["status"], estado["versao"]) == ("Em Andamento", 2)
        assert estado["historicos"] == [("Alteração de status", "Aberto", "Em Andamento")]

    def test_versao_antiga_e_409_e_nao_executa_update(self, cliente, chamado_qualidade, sessao, autenticar):
        admin = _admin(autenticar, chamado_qualidade)
        assert _put(cliente, QUALIDADE, {"prioridade": "Alta", "versao_esperada": 1}, admin).status_code == 200
        antes = _estado(sessao, QUALIDADE)

        resposta = _put(cliente, QUALIDADE, {"status": "Em Andamento", "versao_esperada": 1}, admin)

        assert resposta.status_code == 409
        assert resposta.json() == _desatualizada(2)
        # `updated_at` igual: o trigger o reescreve em todo UPDATE, até no vazio.
        assert _estado(sessao, QUALIDADE) == antes

    def test_sem_versao_e_428_e_nao_executa_update(self, cliente, chamado_qualidade, sessao, autenticar):
        antes = _estado(sessao, QUALIDADE)
        resposta = _put(cliente, QUALIDADE, {"status": "Em Andamento"}, _admin(autenticar, chamado_qualidade))
        assert resposta.status_code == 428
        assert resposta.json() == {"detail": VERSAO_AUSENTE}
        assert _estado(sessao, QUALIDADE) == antes

    def test_escritas_em_sequencia_com_a_versao_devolvida(self, cliente, chamado_qualidade, sessao, autenticar):
        admin = _admin(autenticar, chamado_qualidade)
        versao = 1
        for corpo in ({"status": "Em Andamento"}, {"prioridade": "Alta"}, {"status": "Aguardando"}):
            resposta = _put(cliente, QUALIDADE, {**corpo, "versao_esperada": versao}, admin)
            assert resposta.status_code == 200, resposta.text
            assert resposta.json()["versao"] == versao + 1
            versao = resposta.json()["versao"]
        assert _estado(sessao, QUALIDADE)["versao"] == 4

    def test_mesmos_valores_com_a_versao_certa_nao_sobe(self, cliente, chamado_qualidade, sessao, autenticar):
        resposta = _put(
            cliente, QUALIDADE, {"status": "Aberto", "prioridade": "Média", "versao_esperada": 1},
            _admin(autenticar, chamado_qualidade),
        )
        assert resposta.status_code == 200
        assert resposta.json()["versao"] == 1
        assert _estado(sessao, QUALIDADE)["historicos"] == []


class TestAtendimento:
    def test_versao_certa_grava_e_sobe_1(self, cliente, chamado_qualidade, sessao, autenticar):
        atendente = _atendente(autenticar, chamado_qualidade)
        primeira = _atender(cliente, {"status": "Em Andamento", "versao_esperada": 1}, atendente)
        assert primeira.json()["versao"] == 2
        segunda = _atender(
            cliente, {"status": "Resolvido", "solucao": SOLUCAO_OK, "versao_esperada": 2}, atendente
        )
        assert segunda.status_code == 200, segunda.text
        estado = _estado(sessao, QUALIDADE)
        assert (estado["status"], estado["versao"]) == ("Resolvido", 3)
        assert [h[1:] for h in estado["historicos"]] == [("Aberto", "Em Andamento"), ("Em Andamento", "Resolvido")]

    def test_versao_antiga_e_409_e_nao_executa_update(self, cliente, chamado_qualidade, sessao, autenticar):
        atendente = _atendente(autenticar, chamado_qualidade)
        assert _atender(cliente, {"status": "Em Andamento", "versao_esperada": 1}, atendente).status_code == 200
        antes = _estado(sessao, QUALIDADE)

        resposta = _atender(cliente, {"status": "Aguardando", "versao_esperada": 1}, atendente)

        assert resposta.status_code == 409
        assert resposta.json() == _desatualizada(2)
        assert _estado(sessao, QUALIDADE) == antes

    def test_sem_versao_e_428(self, cliente, chamado_qualidade, sessao, autenticar):
        antes = _estado(sessao, QUALIDADE)
        resposta = _atender(cliente, {"status": "Em Andamento"}, _atendente(autenticar, chamado_qualidade))
        assert resposta.status_code == 428
        assert _estado(sessao, QUALIDADE) == antes


class TestMarcasDaQualidade:
    @pytest.mark.parametrize(
        "rota,depois",
        [("cancelar", (True, False)), ("arquivar", (False, True))],
    )
    def test_versao_certa_grava_sobe_1_com_historico(
        self, cliente, chamado_qualidade, sessao, autenticar, rota, depois
    ):
        resposta = _marca(cliente, rota, {"versao_esperada": 1}, _admin(autenticar, chamado_qualidade))
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["versao"] == 2
        estado = _estado(sessao, QUALIDADE)
        assert (estado["cancelado"], estado["arquivado"], estado["versao"]) == (*depois, 2)
        assert len(estado["historicos"]) == 1

    def test_arquivar_e_desarquivar_encadeados(self, cliente, chamado_qualidade, sessao, autenticar):
        admin = _admin(autenticar, chamado_qualidade)
        arquivado = _marca(cliente, "arquivar", {"versao_esperada": 1}, admin)
        desarquivado = _marca(cliente, "desarquivar", {"versao_esperada": arquivado.json()["versao"]}, admin)
        assert desarquivado.status_code == 200
        assert desarquivado.json()["versao"] == 3
        assert len(_estado(sessao, QUALIDADE)["historicos"]) == 2

    @pytest.mark.parametrize("rota", ["cancelar", "arquivar"])
    def test_versao_antiga_e_409_e_nao_executa_update(self, cliente, chamado_qualidade, sessao, autenticar, rota):
        admin = _admin(autenticar, chamado_qualidade)
        assert _put(cliente, QUALIDADE, {"prioridade": "Alta", "versao_esperada": 1}, admin).status_code == 200
        antes = _estado(sessao, QUALIDADE)

        resposta = _marca(cliente, rota, {"versao_esperada": 1}, admin)

        assert resposta.status_code == 409
        assert resposta.json() == _desatualizada(2)
        assert _estado(sessao, QUALIDADE) == antes

    @pytest.mark.parametrize("rota", ["cancelar", "arquivar"])
    def test_sem_versao_e_428(self, cliente, chamado_qualidade, sessao, autenticar, rota):
        antes = _estado(sessao, QUALIDADE)
        resposta = cliente.patch(f"/api/v1/chamados/{QUALIDADE}/{rota}", headers=_admin(autenticar, chamado_qualidade))
        assert resposta.status_code == 428
        assert _estado(sessao, QUALIDADE) == antes


class TestAtomicidade:
    """Falha de verdade, no commit, desfaz chamado e histórico juntos."""

    @pytest.fixture
    def historico_com_autor_inexistente(self, monkeypatch):
        """O histórico vai com um usuário que não existe: a FK falha no commit."""
        original = chamados_endpoint.adicionar_historico

        def com_autor_inexistente(db, **kwargs):
            return original(db, **{**kwargs, "usuario_id": 999999})

        monkeypatch.setattr(chamados_endpoint, "adicionar_historico", com_autor_inexistente)

    def test_put_falha_no_historico_desfaz_o_chamado(
        self, cliente, chamado_qualidade, sessao, autenticar, historico_com_autor_inexistente
    ):
        antes = _estado(sessao, QUALIDADE)
        with pytest.raises(IntegrityError):
            _put(
                cliente, QUALIDADE, {"status": "Em Andamento", "prioridade": "Alta", "versao_esperada": 1},
                _admin(autenticar, chamado_qualidade),
            )
        assert _estado(sessao, QUALIDADE) == antes

    @pytest.mark.parametrize("rota", ["cancelar", "arquivar"])
    def test_marca_falha_no_historico_desfaz_a_marca(
        self, cliente, chamado_qualidade, sessao, autenticar, historico_com_autor_inexistente, rota
    ):
        antes = _estado(sessao, QUALIDADE)
        with pytest.raises(IntegrityError):
            _marca(cliente, rota, {"versao_esperada": 1}, _admin(autenticar, chamado_qualidade))
        assert _estado(sessao, QUALIDADE) == antes

    def test_put_falha_no_chamado_nao_grava_o_historico(
        self, cliente, chamado_qualidade, sessao, autenticar, monkeypatch
    ):
        # Pula a validação do responsável para a FK do chamado falhar no commit.
        monkeypatch.setattr(chamados_endpoint, "_validar_responsavel_da_qualidade", lambda *a: None)
        antes = _estado(sessao, QUALIDADE)
        with pytest.raises(IntegrityError):
            _put(
                cliente, QUALIDADE,
                {"status": "Em Andamento", "tecnico_responsavel_id": 999999, "versao_esperada": 1},
                _admin(autenticar, chamado_qualidade),
            )
        assert _estado(sessao, QUALIDADE) == antes


class TestConcorrenciaPontual:
    """
    Outra transação trava a linha, grava e só então solta. A escrita da API,
    feita com a versão de antes, espera o lock e recusa com a versão nova —
    a mudança da outra transação fica de pé.
    """

    @pytest.fixture
    def outra_pessoa_grava(self, outra_conexao):
        """Trava a linha e muda a prioridade, sem commit ainda."""
        with outra_conexao.cursor() as cur:
            cur.execute("SELECT id FROM chamados WHERE id = %s FOR UPDATE", (QUALIDADE,))
            cur.execute("UPDATE chamados SET prioridade = 'Crítica' WHERE id = %s", (QUALIDADE,))
        return outra_conexao

    @pytest.mark.parametrize(
        "escrita",
        [
            lambda c, a, d: _put(c, QUALIDADE, {"status": "Em Andamento", "versao_esperada": 1}, _admin(a, d)),
            lambda c, a, d: _atender(c, {"status": "Em Andamento", "versao_esperada": 1}, _atendente(a, d)),
            lambda c, a, d: _marca(c, "arquivar", {"versao_esperada": 1}, _admin(a, d)),
            lambda c, a, d: _marca(c, "cancelar", {"versao_esperada": 1}, _admin(a, d)),
        ],
        ids=["put", "atendimento", "arquivar", "cancelar"],
    )
    def test_espera_o_lock_e_recusa_com_a_versao_gravada_pela_outra(
        self, cliente, chamado_qualidade, sessao, autenticar, url_do_banco, outra_pessoa_grava, escrita
    ):
        esperar = em_paralelo(lambda: escrita(cliente, autenticar, chamado_qualidade))
        esperar_bloqueio(url_do_banco, pid_de(outra_pessoa_grava))
        outra_pessoa_grava.commit()

        resposta = esperar()

        assert resposta.status_code == 409, resposta.text
        assert resposta.json() == _desatualizada(2)
        estado = _estado(sessao, QUALIDADE)
        assert (estado["prioridade"], estado["status"], estado["versao"]) == ("Crítica", "Aberto", 2)
        assert (estado["cancelado"], estado["arquivado"]) == (False, False)
        assert estado["historicos"] == []

    def test_a_ti_nao_pede_o_lock(self, cliente, dados, sessao, autenticar, outra_conexao):
        """
        `FOR KEY SHARE` na outra transação não barra o UPDATE comum, mas barra
        o `FOR UPDATE`. A prova é de estrutura, não de relógio: a TI não manda
        `FOR UPDATE` nenhum, e grava com o lock da outra transação de pé.
        """
        with outra_conexao.cursor() as cur:
            cur.execute("SELECT id FROM chamados WHERE id = %s FOR KEY SHARE", (dados["chamado_id"],))

        # Em thread: se a TI passar a pedir o lock, o teste falha pela espera
        # dele, e não pelo lock_timeout da sessão.
        with sql_emitido(sessao.get_bind()) as comandos:
            resposta = em_paralelo(
                lambda: _put(cliente, dados["chamado_id"], {"status": "Em Andamento"}, _admin(autenticar, dados))
            )()
        assert resposta.status_code == 200
        assert comandos and not [c for c in comandos if "FOR UPDATE" in c.upper()]

    def test_a_qualidade_pede_o_lock(
        self, cliente, chamado_qualidade, sessao, autenticar, url_do_banco, outra_conexao
    ):
        """No mesmo cenário, a Qualidade espera: o banco a mostra bloqueada pela outra transação."""
        with outra_conexao.cursor() as cur:
            cur.execute("SELECT id FROM chamados WHERE id = %s FOR KEY SHARE", (QUALIDADE,))

        esperar = em_paralelo(
            lambda: _put(cliente, QUALIDADE, {"prioridade": "Alta", "versao_esperada": 1}, _admin(autenticar, chamado_qualidade))
        )
        esperar_bloqueio(url_do_banco, pid_de(outra_conexao))
        outra_conexao.rollback()

        resposta = esperar()
        assert resposta.status_code == 200, resposta.text
        assert _estado(sessao, QUALIDADE)["prioridade"] == "Alta"

    @pytest.mark.parametrize(
        "corpo,status",
        [({"status": "Em Andamento"}, 428), ({"status": "Em Andamento", "versao_esperada": 5}, 409)],
        ids=["428", "409"],
    )
    def test_recusa_nao_deixa_a_linha_travada(
        self, cliente, chamado_qualidade, autenticar, outra_conexao, corpo, status
    ):
        assert _put(cliente, QUALIDADE, corpo, _admin(autenticar, chamado_qualidade)).status_code == status
        with outra_conexao.cursor() as cur:
            cur.execute("SELECT id FROM chamados WHERE id = %s FOR UPDATE NOWAIT", (QUALIDADE,))
            assert cur.fetchone() == (QUALIDADE,)
