"""
Concorrência da TI em PostgreSQL real (API-12).

Até a API-11 o PUT da TI conferia `versao_esperada` sem travar a linha: duas
requisições com a mesma versão conferiam antes de qualquer UPDATE e passavam
as duas — na homologação local, 12 de 20 rodadas. Desde a API-12, quando a
versão vem, a TI segue o caminho da Qualidade: `SELECT ... FOR UPDATE`,
conferência na linha travada, chamado e histórico num commit só, webhook
depois do commit. Sem versão, o fluxo de antes (cliente antigo).

O molde é o de `test_concorrencia_versao_postgres.py`: cada requisição com a
sua sessão e a sua conexão; a ordem é imposta por uma `Pausa` logo depois da
conferência de versão e comprovada pelo banco (`pg_blocking_pids`), nunca
por sleep. A largada conjunta (barreira, sem pausa) entra em rodadas, para
mostrar que o resultado não depende do interleaving.

O que este arquivo NÃO protege, e diz: a escrita da TI sem versão (ações
rápidas do front, resolver, motivo do cancelamento) continua valendo a
última — `TestSemVersaoSegueUltimaEscrita`.
"""

import threading

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import main
from app.api.deps import get_db
from app.api.endpoints import chamados as chamados_endpoint
from app.services.chamado_service import adicionar_historico
from app.services.versao_service import VERSAO_DESATUALIZADA
from concorrencia import LOCK_TIMEOUT_DOS_TESTES, TEMPO_MAXIMO, Pausa, em_paralelo, esperar_bloqueio, sql_emitido
from pg_descartavel import banco_descartavel, modelo_da_api

pytestmark = pytest.mark.postgres

TI = 100
SOLUCAO_A = "Trocado o cabo de força da impressora"
SOLUCAO_B = "Reinstalado o driver da impressora"
RODADAS = 25


# --------------------------------------------------------------------------
# Banco, sessões e cliente
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def banco_modelo():
    with modelo_da_api("modelo_concorrencia_ti") as url:
        yield url


@pytest.fixture
def url_do_banco(banco_modelo):
    with banco_descartavel(modelo=banco_modelo) as url:
        yield url


@pytest.fixture
def engine(url_do_banco):
    engine = create_engine(
        url_do_banco.replace("postgresql://", "postgresql+psycopg2://", 1),
        connect_args={"options": f"-c lock_timeout={LOCK_TIMEOUT_DOS_TESTES}"},
    )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sessao(engine):
    """Substitui o `sessao` SQLite do conftest: cadastro e leituras do teste."""
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def cliente(engine):
    """Uma sessão nova por requisição, fechada no fim — como o `get_db` de produção."""
    Sessao = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _get_db_por_requisicao():
        db = Sessao()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = _get_db_por_requisicao
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


@pytest.fixture
def webhook(monkeypatch):
    chamadas = []
    trava = threading.Lock()

    def registrar(**kwargs):
        with trava:
            chamadas.append(kwargs)

    monkeypatch.setattr(chamados_endpoint, "enviar_webhook_tecnico", registrar)
    return chamadas


@pytest.fixture
def pausa(monkeypatch):
    """Pausa a primeira requisição logo depois de conferir a versão (com a linha travada)."""
    p = Pausa(chamados_endpoint.conferir_versao)
    monkeypatch.setattr(chamados_endpoint, "conferir_versao", p)
    yield p
    p.liberar()


@pytest.fixture
def base(qualidade, sessao, webhook):
    """
    O chamado 100 da TI, com uma segunda categoria e uma conta de serviço da
    TI. Ids do banco de teste, não de produção.
    """
    sessao.execute(text("INSERT INTO categorias (id, nome) VALUES (2, 'Rede')"))
    sessao.execute(text(
        "INSERT INTO usuarios (id, nome, role_id, setor_id, ativo, conta_de_servico) "
        "VALUES (50, 'painel.ti', 2, 1, true, true)"
    ))
    sessao.commit()
    return {**qualidade, "servico_ti_id": 50, "v0": _estado(sessao)["versao"]}


# --------------------------------------------------------------------------
# Leitura, escrita e cena
# --------------------------------------------------------------------------

def _estado(sessao, chamado_id=TI):
    """Lido por SQL, sem objeto em memória: o que está gravado."""
    sessao.rollback()
    linha = sessao.execute(
        text(
            "SELECT status, prioridade, categoria_id, tecnico_responsavel_id, solucao, cancelado, arquivado, "
            "versao FROM chamados WHERE id = :id"
        ),
        {"id": chamado_id},
    ).mappings().one()
    historicos = sessao.execute(
        text(
            "SELECT acao, status_anterior, status_novo, usuario_id FROM historico_chamados "
            "WHERE chamado_id = :id ORDER BY id"
        ),
        {"id": chamado_id},
    ).all()
    return {**linha, "historicos": [tuple(h) for h in historicos]}


def _linha(sessao, chamado_id=TI):
    sessao.rollback()
    return dict(sessao.execute(text("SELECT * FROM chamados WHERE id = :id"), {"id": chamado_id}).mappings().one())


def _gravar(sessao, chamado_id=TI, **campos):
    atribuicoes = ", ".join(f"{campo} = :{campo}" for campo in campos)
    sessao.execute(text(f"UPDATE chamados SET {atribuicoes} WHERE id = :id"), {**campos, "id": chamado_id})
    sessao.commit()
    return _estado(sessao, chamado_id)["versao"]


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _tecnico(autenticar, d):
    return autenticar(d["tecnico_id"], "tecnico.teste", "Tecnico")


def _put(cliente, corpo, headers, chamado_id=TI):
    return cliente.put(f"/api/v1/chamados/{chamado_id}", json=corpo, headers=headers)


def _marca(cliente, rota, corpo, headers, chamado_id=TI):
    url = f"/api/v1/chamados/{chamado_id}/{rota}"
    if corpo is None:
        return cliente.patch(url, headers=headers)
    return cliente.patch(url, json=corpo, headers=headers)


def _desatualizada(versao_atual):
    return {"detail": VERSAO_DESATUALIZADA, "codigo": "versao_desatualizada", "versao_atual": versao_atual}


def _ok(resposta, status=200):
    assert resposta.status_code == status, resposta.text
    return resposta.json()


def _cena(url, pausa, primeira, segunda):
    """
    A para na pausa com a linha travada; B é disparada e o teste espera o
    PostgreSQL mostrar B bloqueada pelo backend de A; A segue. Devolve (A, B).
    """
    esperar_a = em_paralelo(primeira)
    pausa.esperar_parar()
    esperar_b = em_paralelo(segunda)
    esperar_bloqueio(url, pausa.pid)
    pausa.liberar()
    return esperar_a(), esperar_b()


# Classe B: o mesmo campo, dois valores. (campo no corpo, valor de A, valor de B, coluna lida)
MESMO_CAMPO = [
    ("prioridade", "Alta", "Baixa", "prioridade"),
    ("status", "Em Andamento", "Aguardando", "status"),
    ("categoria_id", 2, None, "categoria_id"),
    ("tecnico_responsavel_id", "tecnico", "admin", "tecnico_responsavel_id"),
    ("solucao", SOLUCAO_A, SOLUCAO_B, "solucao"),
]


def _valor(d, valor):
    return {"tecnico": d["tecnico_id"], "admin": d["admin_id"]}.get(valor, valor) if isinstance(valor, str) else valor


# --------------------------------------------------------------------------
# Classe B — o mesmo campo, a mesma versão
# --------------------------------------------------------------------------

class TestClasseBMesmoCampo:
    @pytest.mark.parametrize("ordem", ["A antes de B", "B antes de A"])
    @pytest.mark.parametrize("campo,valor_a,valor_b,coluna", MESMO_CAMPO, ids=[c[0] for c in MESMO_CAMPO])
    def test_com_a_ordem_imposta_so_a_primeira_grava(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa, webhook, ordem, campo, valor_a, valor_b, coluna
    ):
        d, v0 = base, base["v0"]
        quem = {"A": (_admin(autenticar, d), _valor(d, valor_a)), "B": (_tecnico(autenticar, d), _valor(d, valor_b))}
        primeira, segunda = ("A", "B") if ordem == "A antes de B" else ("B", "A")

        def escrever(nome):
            headers, valor = quem[nome]
            return lambda: _put(cliente, {campo: valor, "versao_esperada": v0}, headers)

        r1, r2 = _cena(url_do_banco, pausa, escrever(primeira), escrever(segunda))

        assert _ok(r1)["versao"] == v0 + 1
        assert r2.status_code == 409 and r2.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        vencedor = quem[primeira][1]
        assert (estado[coluna], estado["versao"]) == (vencedor, v0 + 1)
        # Histórico e webhook só da escrita confirmada.
        if campo == "status":
            id_vencedor = d["admin_id"] if primeira == "A" else d["tecnico_id"]
            assert estado["historicos"] == [("Alteração de status", "Aberto", vencedor, id_vencedor)]
        else:
            assert estado["historicos"] == []
        if campo == "tecnico_responsavel_id":
            assert [(w["tecnico_id"], w["acao"]) for w in webhook] == [(vencedor, "atribuido")]
        else:
            assert webhook == []

    def test_a_recusada_nao_grava_nenhum_dos_seus_campos(self, cliente, base, sessao, autenticar, url_do_banco, pausa, webhook):
        """B leva vários campos; perde para A, e nenhum deles é gravado."""
        d, v0 = base, base["v0"]
        corpo_b = {
            "prioridade": "Crítica",
            "categoria_id": 2,
            "status": "Aguardando",
            "tecnico_responsavel_id": d["tecnico_id"],
            "solucao": SOLUCAO_B,
            "observacoes": "edição de B",
            "versao_esperada": v0,
        }
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"prioridade": "Alta", "versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _put(cliente, corpo_b, _tecnico(autenticar, d)),
        )

        _ok(a)
        assert b.status_code == 409
        estado = _estado(sessao)
        assert (estado["prioridade"], estado["categoria_id"], estado["status"]) == ("Alta", 1, "Aberto")
        assert (estado["tecnico_responsavel_id"], estado["solucao"]) == (None, None)
        assert estado["historicos"] == [] and webhook == []

    def test_largando_juntos_em_rodadas_exatamente_um_vence(self, cliente, base, sessao, autenticar, webhook):
        """
        Sem pausa: as duas threads largam da mesma barreira, rodada após
        rodada. Na API-11, a mesma cena deu 12 de 20 rodadas com as duas
        gravando. Aqui, em toda rodada, uma grava e a outra recebe 409.
        """
        d = base
        admin, tecnico = _admin(autenticar, d), _tecnico(autenticar, d)
        resultados = []
        for rodada in range(RODADAS):
            v = _estado(sessao)["versao"]
            largada = threading.Barrier(2, timeout=TEMPO_MAXIMO)
            valores = ("Alta", "Baixa") if rodada % 2 == 0 else ("Crítica", "Média")

            def escrever(headers, prioridade):
                largada.wait()
                return _put(cliente, {"prioridade": prioridade, "versao_esperada": v}, headers)

            esperas = [
                em_paralelo(lambda: escrever(admin, valores[0])),
                em_paralelo(lambda: escrever(tecnico, valores[1])),
            ]
            respostas = [esperar() for esperar in esperas]
            codigos = sorted(r.status_code for r in respostas)
            vencedora = next((r.json() for r in respostas if r.status_code == 200), None)
            estado = _estado(sessao)
            resultados.append((codigos, estado["versao"] - v, vencedora and vencedora["prioridade"] == estado["prioridade"]))

        assert all(r == ([200, 409], 1, True) for r in resultados), resultados


# --------------------------------------------------------------------------
# Classe A — campos diferentes
# --------------------------------------------------------------------------

class TestClasseACamposDiferentes:
    def test_mesma_versao_ao_mesmo_tempo_a_segunda_recebe_409(self, cliente, base, sessao, autenticar, url_do_banco, pausa):
        """
        A versão é do chamado, não do campo: B, que mexe noutro campo, também
        recebe 409. É o esperado — o front relê e oferece salvar de novo, sem
        repetir sozinho. Nada de A é desfeito.
        """
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"prioridade": "Alta", "versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _put(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _tecnico(autenticar, d)),
        )
        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["prioridade"], estado["status"]) == ("Alta", "Aberto")

    def test_releitura_e_versao_nova_as_duas_ficam(self, cliente, base, sessao, autenticar):
        """O caminho do FE-5: corpo mínimo, versão relida. Nenhum campo não enviado é sobrescrito."""
        d, v0 = base, base["v0"]
        _ok(_put(cliente, {"prioridade": "Alta", "versao_esperada": v0}, _admin(autenticar, d)))
        v1 = _ok(cliente.get(f"/api/v1/chamados/{TI}", headers=_tecnico(autenticar, d)))["versao"]
        _ok(_put(cliente, {"status": "Em Andamento", "versao_esperada": v1}, _tecnico(autenticar, d)))
        estado = _estado(sessao)
        assert (estado["prioridade"], estado["status"], estado["versao"]) == ("Alta", "Em Andamento", v0 + 2)
        assert estado["historicos"] == [("Alteração de status", "Aberto", "Em Andamento", d["tecnico_id"])]


# --------------------------------------------------------------------------
# Marcas da TI com versão, e PUT × marca
# --------------------------------------------------------------------------

class TestMarcasDaTiComVersao:
    @pytest.mark.parametrize(
        "rota,coluna",
        [("arquivar", "arquivado"), ("cancelar", "cancelado")],
    )
    def test_put_primeiro_e_marca_com_a_mesma_versao_e_409(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa, rota, coluna
    ):
        d, v0 = base, base["v0"]
        admin = _admin(autenticar, d)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"prioridade": "Alta", "versao_esperada": v0}, admin),
            lambda: _marca(cliente, rota, {"versao_esperada": v0}, admin),
        )
        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado[coluna], estado["prioridade"]) == (False, "Alta")
        assert estado["historicos"] == []

    @pytest.mark.parametrize("rota,coluna", [("arquivar", "arquivado"), ("cancelar", "cancelado")])
    def test_marca_primeiro_e_put_com_a_mesma_versao_e_409(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa, webhook, rota, coluna
    ):
        d, v0 = base, base["v0"]
        admin = _admin(autenticar, d)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _marca(cliente, rota, {"versao_esperada": v0}, admin),
            lambda: _put(cliente, {"tecnico_responsavel_id": d["tecnico_id"], "versao_esperada": v0}, admin),
        )
        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado[coluna], estado["tecnico_responsavel_id"]) == (True, None)
        assert [h[0] for h in estado["historicos"]] == [
            "Arquivamento de chamado" if rota == "arquivar" else "Cancelamento de chamado"
        ]
        assert webhook == []

    def test_desarquivar_com_versao_trava(self, cliente, base, sessao, autenticar, url_do_banco, pausa):
        d = base
        admin = _admin(autenticar, d)
        v1 = _gravar(sessao, arquivado=True)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _marca(cliente, "desarquivar", {"versao_esperada": v1}, admin),
            lambda: _put(cliente, {"prioridade": "Alta", "versao_esperada": v1}, admin),
        )
        _ok(a)
        assert b.status_code == 409
        estado = _estado(sessao)
        assert (estado["arquivado"], estado["prioridade"]) == (False, "Média")

    def test_marca_sem_versao_segue_sem_trava(self, cliente, base, autenticar, engine):
        with sql_emitido(engine) as comandos:
            _ok(_marca(cliente, "arquivar", None, _admin(autenticar, base)))
            _ok(_marca(cliente, "desarquivar", {}, _admin(autenticar, base)))
        assert comandos and not [c for c in comandos if "FOR UPDATE" in c.upper()]


# --------------------------------------------------------------------------
# Sem versão: o fluxo de antes (risco residual, documentado)
# --------------------------------------------------------------------------

class TestSemVersaoSegueUltimaEscrita:
    def test_put_sem_versao_nao_pede_o_lock(self, cliente, base, autenticar, engine):
        with sql_emitido(engine) as comandos:
            _ok(_put(cliente, {"status": "Em Andamento"}, _admin(autenticar, base)))
        assert comandos and not [c for c in comandos if "FOR UPDATE" in c.upper()]

    def test_put_com_versao_pede_o_lock(self, cliente, base, autenticar, engine):
        with sql_emitido(engine) as comandos:
            _ok(_put(cliente, {"status": "Em Andamento", "versao_esperada": base["v0"]}, _admin(autenticar, base)))
        travas = [c for c in comandos if "FOR UPDATE" in c.upper()]
        assert len(travas) == 1 and "chamados" in travas[0]

    def test_largando_juntos_sem_versao_as_duas_gravam(self, cliente, base, sessao, autenticar):
        """Risco residual: cliente sem versão continua sendo 'vale a última'."""
        d = base
        largada = threading.Barrier(2, timeout=TEMPO_MAXIMO)

        def escrever(headers, prioridade):
            largada.wait()
            return _put(cliente, {"prioridade": prioridade}, headers)

        esperas = [
            em_paralelo(lambda: escrever(_admin(autenticar, d), "Alta")),
            em_paralelo(lambda: escrever(_tecnico(autenticar, d), "Baixa")),
        ]
        assert sorted(esperar().status_code for esperar in esperas) == [200, 200]
        assert _estado(sessao)["prioridade"] in ("Alta", "Baixa")

    def test_acao_rapida_sem_versao_espera_a_trava_e_grava_por_cima(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa
    ):
        """
        A (com versão) segura a linha; a ação rápida sem versão, como o front
        manda hoje, espera o UPDATE dela e grava depois — não recebe 409. A
        última escrita vence, e o histórico dela traz o status anterior lido
        antes da espera ("Aberto"), não o que A gravou: o fluxo sem versão
        não relê sob trava. Risco residual, não corrigido nesta etapa.
        """
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _put(cliente, {"status": "Aguardando"}, _tecnico(autenticar, d)),
        )
        _ok(a)
        _ok(b)
        estado = _estado(sessao)
        assert (estado["status"], estado["versao"]) == ("Aguardando", v0 + 2)
        assert [h[1:3] for h in estado["historicos"]] == [("Aberto", "Em Andamento"), ("Aberto", "Aguardando")]


# --------------------------------------------------------------------------
# Falhas, autorização e casos especiais
# --------------------------------------------------------------------------

class FalhaDepoisDoFlush:
    """Põe o histórico na transação, manda ao banco, para, e lança."""

    def __init__(self):
        self._parou = threading.Event()
        self._seguir = threading.Event()
        self.pid = None

    def __call__(self, db, **campos):
        adicionar_historico(db=db, **campos)
        db.flush()
        self.pid = db.execute(text("SELECT pg_backend_pid()")).scalar()
        self._parou.set()
        self._seguir.wait(TEMPO_MAXIMO)
        raise RuntimeError("falha simulada depois do flush")

    def esperar_parar(self):
        assert self._parou.wait(TEMPO_MAXIMO), "a requisição não chegou à falha"

    def liberar(self):
        self._seguir.set()


class TestFalhas:
    def test_falha_antes_do_commit_desfaz_tudo_solta_a_trava_e_nao_avisa(
        self, cliente, base, sessao, autenticar, url_do_banco, monkeypatch, webhook
    ):
        d, v0 = base, base["v0"]
        falha = FalhaDepoisDoFlush()
        monkeypatch.setattr(chamados_endpoint, "adicionar_historico", falha)
        antes = _linha(sessao)
        corpo = {"status": "Em Andamento", "tecnico_responsavel_id": d["tecnico_id"], "versao_esperada": v0}

        esperar = em_paralelo(lambda: _put(cliente, corpo, _admin(autenticar, d)))
        observador = psycopg2.connect(url_do_banco)
        try:
            falha.esperar_parar()
            with observador.cursor() as cur:
                cur.execute("SELECT versao, tecnico_responsavel_id FROM chamados WHERE id = %s", (TI,))
                assert cur.fetchone() == (v0, None)
                with pytest.raises(psycopg2.errors.LockNotAvailable):
                    cur.execute("SELECT 1 FROM chamados WHERE id = %s FOR UPDATE NOWAIT", (TI,))
            observador.rollback()
            falha.liberar()
            with pytest.raises(RuntimeError, match="falha simulada"):
                esperar()
            with observador.cursor() as cur:
                cur.execute("SELECT 1 FROM chamados WHERE id = %s FOR UPDATE NOWAIT", (TI,))
            observador.rollback()
        finally:
            falha.liberar()
            observador.close()
        assert _linha(sessao) == antes
        assert _estado(sessao)["historicos"] == []
        assert webhook == []

    def test_falha_depois_do_commit_reenviar_a_mesma_versao_e_409(
        self, cliente, base, sessao, autenticar, monkeypatch
    ):
        """
        A gravação entrou e a resposta não saiu (falha depois do commit). O
        cliente que reenvia com a mesma versão recebe 409 com a versão que
        a própria escrita gerou — não grava duas vezes.
        """
        d, v0 = base, base["v0"]
        original = chamados_endpoint._anexar_sla
        estouros = []

        def anexar_que_falha_uma_vez(chamados, db):
            if not estouros:
                estouros.append(1)
                raise RuntimeError("falha simulada depois do commit")
            return original(chamados, db)

        monkeypatch.setattr(chamados_endpoint, "_anexar_sla", anexar_que_falha_uma_vez)
        corpo = {"status": "Em Andamento", "versao_esperada": v0}
        with pytest.raises(RuntimeError, match="depois do commit"):
            _put(cliente, corpo, _admin(autenticar, d))
        assert (_estado(sessao)["status"], _estado(sessao)["versao"]) == ("Em Andamento", v0 + 1)

        resposta = _put(cliente, corpo, _admin(autenticar, d))
        assert resposta.status_code == 409 and resposta.json() == _desatualizada(v0 + 1)
        assert len(_estado(sessao)["historicos"]) == 1

    def test_mesmos_valores_com_versao_nao_sobe_e_nao_grava_historico(self, cliente, base, sessao, autenticar):
        v0 = base["v0"]
        corpo = _ok(_put(cliente, {"prioridade": "Média", "status": "Aberto", "versao_esperada": v0}, _admin(autenticar, base)))
        assert corpo["versao"] == v0
        assert _estado(sessao)["historicos"] == []


class TestAutorizacaoAntesDaTrava:
    """
    Quem não lê o chamado recebe o 404 de um id que não existe, e quem não
    altera, 403 — sem a versão no corpo e sem esperar a trava de ninguém:
    a autorização vem antes do `FOR UPDATE`.
    """

    @pytest.fixture
    def linha_travada(self, url_do_banco):
        externa = psycopg2.connect(url_do_banco)
        with externa.cursor() as cur:
            cur.execute("SELECT id FROM chamados WHERE id = %s FOR UPDATE", (TI,))
        yield externa
        externa.rollback()
        externa.close()

    @pytest.mark.parametrize(
        "quem,codigo",
        [
            ("tecnico_da_qualidade", 404),
            ("servico_ti", 403),
            ("comum", 403),
            ("sem_token", 401),
        ],
    )
    def test_recusa_sem_versao_no_corpo_e_sem_esperar(self, cliente, base, sessao, autenticar, linha_travada, quem, codigo):
        d = base
        headers = {
            "tecnico_da_qualidade": autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico"),
            "servico_ti": autenticar(d["servico_ti_id"], "painel.ti", "Tecnico"),
            "comum": autenticar(d["comum_id"], "usuario.teste", "Usuario"),
            "sem_token": {},
        }[quem]
        resposta = em_paralelo(lambda: _put(cliente, {"prioridade": "Alta", "versao_esperada": 999}, headers))()
        assert resposta.status_code == codigo, resposta.text
        assert "versao_atual" not in resposta.json() and "codigo" not in resposta.json()

    def test_inexistente_e_404_sem_versao(self, cliente, base, autenticar):
        resposta = _put(cliente, {"prioridade": "Alta", "versao_esperada": 1}, _admin(autenticar, base), 999999)
        assert resposta.status_code == 404 and "versao_atual" not in resposta.json()

    @pytest.mark.parametrize("valor", [None, True, "1", 0, -1, 1.5])
    def test_versao_invalida_e_422_e_nada_gravado(self, cliente, base, sessao, autenticar, valor):
        antes = _linha(sessao)
        resposta = _put(cliente, {"prioridade": "Alta", "versao_esperada": valor}, _admin(autenticar, base))
        assert resposta.status_code == 422 and "versao_atual" not in resposta.json()
        assert _linha(sessao) == antes

    def test_permissao_revogada_enquanto_espera_a_trava_ainda_grava(
        self, cliente, base, sessao, autenticar, url_do_banco, linha_travada
    ):
        """
        Limite conhecido, o mesmo da Qualidade desde a API-4c: a autorização
        é lida antes da trava, e a trava é só da linha do chamado. O técnico
        que sai da TI enquanto espera grava a escrita já autorizada, se a
        versão bater. Registrado, não corrigido: travar também a conta mudaria
        a ordem de locks de todas as rotas.
        """
        d, v0 = base, base["v0"]
        esperar = em_paralelo(
            lambda: _put(cliente, {"prioridade": "Baixa", "versao_esperada": v0}, _tecnico(autenticar, d))
        )
        with linha_travada.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            pid = cur.fetchone()[0]
        esperar_bloqueio(url_do_banco, pid)
        sessao.execute(text("UPDATE usuarios SET setor_id = 2 WHERE id = :id"), {"id": d["tecnico_id"]})
        sessao.commit()
        linha_travada.rollback()

        assert _ok(esperar())["prioridade"] == "Baixa"
        # A próxima escrita já vê a revogação: 404 (não lê mais a TI).
        assert _put(cliente, {"prioridade": "Alta"}, _tecnico(autenticar, d)).status_code == 404


class TestQualidadeSegueIgual:
    def test_qualidade_sem_versao_ainda_e_428(self, cliente, base, sessao, autenticar):
        sessao.execute(text(
            "INSERT INTO chamados (id, protocolo, solicitante_id, titulo, descricao, status, prioridade, "
            "setor_destino, tecnico_responsavel_id) VALUES (101, 'CH-TESTE-101', :s, 'Laudo sem assinatura', "
            "'O laudo chegou sem a assinatura do responsável', 'Aberto', 'Média', 'QUALIDADE', :a)"
        ), {"s": base["comum_id"], "a": base["atendente_id"]})
        sessao.commit()
        resposta = _put(cliente, {"prioridade": "Alta"}, _admin(autenticar, base), 101)
        assert resposta.status_code == 428 and resposta.json() == {"detail": "Informe a versão do chamado"}
