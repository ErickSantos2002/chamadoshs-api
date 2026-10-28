"""
Matriz de concorrência da API-4 (API-4c), em PostgreSQL real.

Cada requisição usa a SUA sessão e a SUA conexão, como em produção (o
`get_db` daqui abre uma sessão por requisição), e duas requisições correm ao
mesmo tempo em threads. O que é real: transações, `SELECT ... FOR UPDATE`,
UPDATE, trigger da versão, commit e rollback.

A sincronização é explícita, nunca por sleep:

1. a requisição A para numa `Pausa` logo depois de conferir a versão — com a
   linha já travada pela transação dela;
2. a requisição B é disparada, e o teste espera o PostgreSQL mostrar, em
   `pg_blocking_pids`, que B está bloqueada pelo backend de A;
3. A segue e faz commit; B ganha o lock, relê a linha e decide.

O resultado não depende de qual thread o sistema operacional escolher: a
ordem é imposta pela pausa e comprovada pelo banco.

Cenários: T1–T7 da auditoria da API-4, reatribuição × atendimento nas duas
ordens e marcas × PUT. Rollback, versionamento por rota, TI, 428, 422, SQL
direto, avaliação e segurança estão na segunda metade do arquivo.
"""

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import main
from app.api.deps import get_db
from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.schemas.sla import SLAInfo
from app.services.sla_service import calcular_sla
from app.services.versao_service import VERSAO_DESATUALIZADA
from concorrencia import LOCK_TIMEOUT_DOS_TESTES, TEMPO_MAXIMO, Pausa, em_paralelo, esperar_bloqueio
from pg_descartavel import banco_descartavel, modelo_da_api

pytestmark = pytest.mark.postgres

QUALIDADE = 101
SOLUCAO = "Laudo reemitido com a assinatura do responsável"


# --------------------------------------------------------------------------
# Banco, sessões e cliente
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def banco_modelo():
    with modelo_da_api("modelo_concorrencia") as url:
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
    """
    Substitui o `sessao` SQLite do conftest. Só os fixtures de cadastro e as
    leituras do teste usam esta sessão — as requisições têm as delas.
    """
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
    p.liberar()  # nunca deixa thread presa, nem com o teste falhando


@pytest.fixture
def base(chamado_qualidade, sessao, webhook):
    """O cenário da Qualidade com o webhook interceptado, e a versão inicial."""
    return {**chamado_qualidade, "v0": _estado(sessao)["versao"]}


# --------------------------------------------------------------------------
# Leitura e escrita
# --------------------------------------------------------------------------

def _estado(sessao, chamado_id=QUALIDADE):
    """Lido por SQL, sem objeto em memória: o que está gravado."""
    sessao.rollback()
    linha = sessao.execute(
        text(
            "SELECT status, prioridade, tecnico_responsavel_id, solucao, cancelado, arquivado, avaliacao, "
            "data_resolucao, tempo_resolucao_minutos, versao, updated_at FROM chamados WHERE id = :id"
        ),
        {"id": chamado_id},
    ).mappings().one()
    historicos = sessao.execute(
        text("SELECT acao, status_anterior, status_novo FROM historico_chamados WHERE chamado_id = :id ORDER BY id"),
        {"id": chamado_id},
    ).all()
    return {**linha, "historicos": [tuple(h) for h in historicos]}


def _gravar(sessao, chamado_id=QUALIDADE, **campos):
    """Prepara o cenário por SQL. Muda a versão (o trigger conta): devolve a nova."""
    atribuicoes = ", ".join(f"{campo} = :{campo}" for campo in campos)
    sessao.execute(text(f"UPDATE chamados SET {atribuicoes} WHERE id = :id"), {**campos, "id": chamado_id})
    sessao.commit()
    return _estado(sessao, chamado_id)["versao"]


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _atendente(autenticar, d):
    return autenticar(d["atendente_id"], "ana.qualidade", "Usuario")


def _put(cliente, corpo, headers, chamado_id=QUALIDADE):
    return cliente.put(f"/api/v1/chamados/{chamado_id}", json=corpo, headers=headers)


def _atender(cliente, corpo, headers, chamado_id=QUALIDADE):
    return cliente.patch(f"/api/v1/chamados/{chamado_id}/atendimento", json=corpo, headers=headers)


def _marca(cliente, rota, corpo, headers, chamado_id=QUALIDADE):
    url = f"/api/v1/chamados/{chamado_id}/{rota}"
    if corpo is None:
        return cliente.patch(url, headers=headers)
    return cliente.patch(url, json=corpo, headers=headers)


def _desatualizada(versao_atual):
    return {"detail": VERSAO_DESATUALIZADA, "codigo": "versao_desatualizada", "versao_atual": versao_atual}


def _cena(url, pausa, primeira, segunda):
    """
    A para na pausa com a linha travada; B é disparada e o teste espera o
    PostgreSQL mostrar B bloqueada pelo backend de A; A segue. Devolve as duas
    respostas, (A, B).
    """
    esperar_a = em_paralelo(primeira)
    pausa.esperar_parar()
    esperar_b = em_paralelo(segunda)
    esperar_bloqueio(url, pausa.pid)
    pausa.liberar()
    return esperar_a(), esperar_b()


def _ok(resposta, status=200):
    assert resposta.status_code == status, resposta.text
    return resposta.json()


# --------------------------------------------------------------------------
# T1–T7
# --------------------------------------------------------------------------

class TestT1DoisPutsSimultaneos:
    def test_com_a_ordem_imposta_um_grava_e_o_outro_recebe_409(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa
    ):
        d, v0 = base, base["v0"]
        admin = _admin(autenticar, d)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"status": "Em Andamento", "versao_esperada": v0}, admin),
            lambda: _put(cliente, {"status": "Aguardando", "prioridade": "Alta", "versao_esperada": v0}, admin),
        )

        assert _ok(a)["versao"] == v0 + 1
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["status"], estado["prioridade"], estado["versao"]) == ("Em Andamento", "Média", v0 + 1)
        assert estado["historicos"] == [("Alteração de status", "Aberto", "Em Andamento")]

    def test_largando_juntos_exatamente_um_vence(self, cliente, base, sessao, autenticar):
        """Sem pausa: as duas threads largam da mesma barreira. Quem vence é do acaso; quantos vencem, não."""
        d, v0 = base, base["v0"]
        admin = _admin(autenticar, d)
        largada = threading.Barrier(2, timeout=TEMPO_MAXIMO)
        corpos = {"Em Andamento": {"status": "Em Andamento"}, "Aguardando": {"status": "Aguardando"}}

        def escrever(corpo):
            largada.wait()
            return _put(cliente, {**corpo, "versao_esperada": v0}, admin)

        esperas = [em_paralelo(lambda c=c: escrever(c)) for c in corpos.values()]
        respostas = [esperar() for esperar in esperas]

        assert sorted(r.status_code for r in respostas) == [200, 409]
        vencedora = next(r for r in respostas if r.status_code == 200).json()
        perdedora = next(r for r in respostas if r.status_code == 409).json()
        assert perdedora == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["status"], estado["versao"]) == (vencedora["status"], v0 + 1)
        assert estado["historicos"] == [("Alteração de status", "Aberto", vencedora["status"])]


class TestT2PatchResolveEPutAntigo:
    def test_put_com_a_versao_de_antes_da_resolucao_e_409(self, cliente, base, sessao, autenticar):
        v0 = _gravar(sessao, status="Em Andamento")
        resolvido = _ok(_atender(
            cliente, {"status": "Resolvido", "solucao": SOLUCAO, "versao_esperada": v0}, _atendente(autenticar, base)
        ))
        antes = _estado(sessao)

        resposta = _put(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _admin(autenticar, base))

        assert resposta.status_code == 409 and resposta.json() == _desatualizada(resolvido["versao"])
        assert _estado(sessao) == antes
        assert (antes["status"], antes["solucao"]) == ("Resolvido", SOLUCAO)
        assert antes["historicos"] == [("Alteração de status", "Em Andamento", "Resolvido")]


class TestT3PutEPatchDesatualizado:
    def test_patch_com_a_versao_de_antes_do_put_e_409(self, cliente, base, sessao, autenticar, webhook):
        v0 = base["v0"]
        editado = _ok(_put(cliente, {"prioridade": "Alta", "versao_esperada": v0}, _admin(autenticar, base)))
        antes = _estado(sessao)

        resposta = _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, base))

        assert resposta.status_code == 409 and resposta.json() == _desatualizada(editado["versao"])
        assert _estado(sessao) == antes
        assert (antes["status"], antes["prioridade"], antes["historicos"]) == ("Aberto", "Alta", [])
        assert webhook == []


class TestT4DuasReatribuicoes:
    def test_so_a_primeira_reatribuicao_vale(self, cliente, base, sessao, autenticar, url_do_banco, pausa, webhook):
        d, v0 = base, base["v0"]
        admin = _admin(autenticar, d)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": v0}, admin),
            lambda: _put(cliente, {"tecnico_responsavel_id": d["admin_da_qualidade_id"], "versao_esperada": v0}, admin),
        )

        assert _ok(a)["tecnico_responsavel_id"] == d["tecnico_da_qualidade_id"]
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["versao"]) == (d["tecnico_da_qualidade_id"], v0 + 1)
        # O PUT só registra histórico de status; reatribuição não escreve nenhum.
        assert estado["historicos"] == []
        assert webhook == []


class TestT5PutEsperaOLockDoPatch:
    def test_put_espera_o_atendimento_e_ve_a_versao_nova(self, cliente, base, sessao, autenticar, url_do_banco, pausa):
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
            lambda: _put(cliente, {"status": "Aguardando", "versao_esperada": v0}, _admin(autenticar, d)),
        )

        assert _ok(a)["versao"] == v0 + 1
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["status"], estado["versao"]) == ("Em Andamento", v0 + 1)
        assert estado["historicos"] == [("Alteração de status", "Aberto", "Em Andamento")]


class TestT6SolucaoStatusEHistorico:
    @pytest.fixture
    def em_andamento(self, cliente, base, sessao, autenticar):
        """Chamado em atendimento pela API (com histórico), e prazo de SLA para a prioridade."""
        # O schema já semeia os prazos; o teste fixa os seus para não depender deles.
        sessao.merge(SLAConfig(prioridade="Média", minutos_resposta=60, minutos_resolucao=480))
        sessao.commit()
        corpo = _ok(_atender(cliente, {"status": "Em Andamento", "versao_esperada": base["v0"]}, _atendente(autenticar, base)))
        return {**base, "v1": corpo["versao"]}

    def test_resolucao_concorrente_fica_inteira_e_o_sla_segue_a_vencedora(
        self, cliente, em_andamento, sessao, autenticar, url_do_banco, pausa
    ):
        d, v1 = em_andamento, em_andamento["v1"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _atender(cliente, {"status": "Resolvido", "solucao": SOLUCAO, "versao_esperada": v1}, _atendente(autenticar, d)),
            lambda: _put(cliente, {"status": "Aguardando", "versao_esperada": v1}, _admin(autenticar, d)),
        )

        vencedora = _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v1 + 1)
        estado = _estado(sessao)
        assert (estado["status"], estado["solucao"], estado["versao"]) == ("Resolvido", SOLUCAO, v1 + 1)
        assert estado["data_resolucao"] is not None and estado["tempo_resolucao_minutos"] is not None
        assert estado["historicos"] == [
            ("Alteração de status", "Aberto", "Em Andamento"),
            ("Alteração de status", "Em Andamento", "Resolvido"),
        ]

        # SLA: a resposta da vencedora, a leitura de agora e o cálculo direto
        # sobre o que está gravado dizem a mesma coisa.
        lido = _ok(cliente.get(f"/api/v1/chamados/{QUALIDADE}", headers=_admin(autenticar, d)))["sla"]
        sessao.expire_all()
        chamado = sessao.get(Chamado, QUALIDADE)
        historicos = sessao.query(HistoricoChamado).filter(HistoricoChamado.chamado_id == QUALIDADE).all()
        calculado = calcular_sla(chamado=chamado, historicos=historicos, config=sessao.get(SLAConfig, "Média"))
        assert SLAInfo(**vencedora["sla"]) == SLAInfo(**lido) == SLAInfo(**calculado)

    def test_status_anterior_do_historico_e_o_lido_sob_o_lock(
        self, cliente, em_andamento, sessao, autenticar, url_do_banco, pausa
    ):
        """
        B lê o chamado em "Em Andamento" ANTES do lock, e só o trava depois de A
        o pôr em "Aguardando". B manda a versão que A vai produzir, então passa —
        e o histórico de B tem de partir de "Aguardando", o estado real, e não do
        "Em Andamento" da primeira leitura.
        """
        d, v1 = em_andamento, em_andamento["v1"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _atender(cliente, {"status": "Aguardando", "versao_esperada": v1}, _atendente(autenticar, d)),
            lambda: _put(cliente, {"status": "Resolvido", "solucao": SOLUCAO, "versao_esperada": v1 + 1}, _admin(autenticar, d)),
        )

        assert _ok(a)["versao"] == v1 + 1
        assert _ok(b)["versao"] == v1 + 2
        assert _estado(sessao)["historicos"][-2:] == [
            ("Alteração de status", "Em Andamento", "Aguardando"),
            ("Alteração de status", "Aguardando", "Resolvido"),
        ]


class TestT7MarcasConcorrentes:
    @pytest.mark.parametrize(
        "rota,depois",
        [("cancelar", (True, False)), ("arquivar", (False, True))],
    )
    def test_marca_primeiro_e_atendimento_antigo_e_409(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa, rota, depois
    ):
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _marca(cliente, rota, {"versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
        )

        _ok(a)
        # A versão vem antes da recusa de "cancelado/arquivado": 409 de versão.
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["cancelado"], estado["arquivado"], estado["status"], estado["versao"]) == (*depois, "Aberto", v0 + 1)
        assert len(estado["historicos"]) == 1 and estado["historicos"][0][1:] == (None, None)

    @pytest.mark.parametrize("rota", ["cancelar", "arquivar"])
    def test_atendimento_primeiro_e_marca_antiga_e_409(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa, rota
    ):
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
            lambda: _marca(cliente, rota, {"versao_esperada": v0}, _admin(autenticar, d)),
        )

        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["cancelado"], estado["arquivado"], estado["status"]) == (False, False, "Em Andamento")
        assert estado["historicos"] == [("Alteração de status", "Aberto", "Em Andamento")]

    def test_desarquivar_e_put_antigo_e_409(self, cliente, base, sessao, autenticar, url_do_banco, pausa):
        d = base
        v0 = _gravar(sessao, arquivado=True)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _marca(cliente, "desarquivar", {"versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _put(cliente, {"prioridade": "Alta", "versao_esperada": v0}, _admin(autenticar, d)),
        )

        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["arquivado"], estado["prioridade"], estado["versao"]) == (False, "Média", v0 + 1)
        assert [h[0] for h in estado["historicos"]] == ["Desarquivamento de chamado"]


# --------------------------------------------------------------------------
# Reatribuição × atendimento, e marcas × PUT
# --------------------------------------------------------------------------

class TestReatribuicaoEAtendimento:
    def test_reatribuicao_primeiro_o_antigo_responsavel_recebe_403_sem_a_versao(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa
    ):
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
        )

        _ok(a)
        # A autorização, relida sob o lock, vem antes da versão: 403, e sem versao_atual.
        assert b.status_code == 403
        assert b.json() == {"detail": "Só o responsável atual pode atender este chamado"}
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["status"], estado["historicos"]) == (
            d["tecnico_da_qualidade_id"], "Aberto", [],
        )

    def test_atendimento_primeiro_a_reatribuicao_antiga_e_409(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa
    ):
        d, v0 = base, base["v0"]
        admin = _admin(autenticar, d)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
            lambda: _put(cliente, {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": v0}, admin),
        )

        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        assert _estado(sessao)["tecnico_responsavel_id"] == d["atendente_id"]

        # Com a versão nova: a elegibilidade continua valendo...
        inelegivel = _put(cliente, {"tecnico_responsavel_id": d["inativo_id"], "versao_esperada": v0 + 1}, admin)
        assert inelegivel.status_code == 400
        # ...a reatribuição válida passa, e o antigo responsável deixa de atender.
        _ok(_put(cliente, {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": v0 + 1}, admin))
        antigo = _atender(cliente, {"status": "Aguardando", "versao_esperada": v0 + 2}, _atendente(autenticar, d))
        assert antigo.status_code == 403 and "versao_atual" not in antigo.json()
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["status"], estado["versao"]) == (
            d["tecnico_da_qualidade_id"], "Em Andamento", v0 + 2,
        )


class TestMarcasEPut:
    def test_cancelar_primeiro_e_put_antigo_e_409(self, cliente, base, sessao, autenticar, url_do_banco, pausa):
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _marca(cliente, "cancelar", {"versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _put(cliente, {"status": "Em Andamento", "prioridade": "Alta", "versao_esperada": v0}, _admin(autenticar, d)),
        )

        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["cancelado"], estado["status"], estado["prioridade"]) == (True, "Aberto", "Média")
        assert [h[0] for h in estado["historicos"]] == ["Cancelamento de chamado"]

    def test_put_primeiro_e_arquivar_antigo_e_409(self, cliente, base, sessao, autenticar, url_do_banco, pausa):
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _marca(cliente, "arquivar", {"versao_esperada": v0}, _admin(autenticar, d)),
        )

        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["arquivado"], estado["status"]) == (False, "Em Andamento")
        assert estado["historicos"] == [("Alteração de status", "Aberto", "Em Andamento")]
