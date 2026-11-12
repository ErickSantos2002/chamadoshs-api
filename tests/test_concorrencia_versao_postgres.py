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

import psycopg2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import main
from app.api.deps import get_db
from app.api.endpoints import chamados as chamados_endpoint
from app.models import Chamado, Usuario
from app.models.historico import HistoricoChamado
from app.models.sla_config import SLAConfig
from app.schemas.sla import SLAInfo
from app.services.chamado_service import adicionar_historico
from app.services.sla_service import calcular_sla
from app.services.versao_service import VERSAO_DESATUALIZADA
from concorrencia import LOCK_TIMEOUT_DOS_TESTES, TEMPO_MAXIMO, Pausa, em_paralelo, esperar_bloqueio, sql_emitido
from pg_descartavel import banco_descartavel, modelo_da_api

pytestmark = pytest.mark.postgres

QUALIDADE = 101
SOLUCAO = "Laudo reemitido com a assinatura do responsável"
# Um segundo Técnico da Qualidade, para as reatribuições terem um destino
# elegível que não é o responsável (API-13: só o Técnico dela é elegível).
OUTRO_TECNICO_DA_QUALIDADE = 46


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
def base(chamado_qualidade_do_tecnico, sessao, webhook):
    """
    O cenário da Qualidade com o webhook interceptado, e a versão inicial.

    O responsável é o Técnico da Qualidade, o único que atende desde a API-13
    (até a API-12 era a ana, de perfil comum), e há um segundo Técnico dela
    como destino das reatribuições.
    """
    d = chamado_qualidade_do_tecnico
    sessao.add(Usuario(
        id=OUTRO_TECNICO_DA_QUALIDADE, nome="beto.qualidade", role_id=2,
        setor_id=d["setor_qualidade_id"], ativo=True,
    ))
    sessao.commit()
    return {**d, "outro_tecnico_da_qualidade_id": OUTRO_TECNICO_DA_QUALIDADE, "v0": _estado(sessao)["versao"]}


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
    # API-13: quem atende é o Técnico da Qualidade, e não mais a ana (comum).
    return autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico")


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
        d = base
        # Estado legado (antes da API-13): a ana, de perfil comum, volta a ser
        # a responsável, para as duas reatribuições irem a Técnicos elegíveis
        # diferentes dela. Até a API-12 a segunda ia ao administrador da
        # Qualidade, que desde a API-13 não é elegível.
        v0 = _gravar(sessao, tecnico_responsavel_id=d["atendente_id"])
        admin = _admin(autenticar, d)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": v0}, admin),
            lambda: _put(cliente, {"tecnico_responsavel_id": d["outro_tecnico_da_qualidade_id"], "versao_esperada": v0}, admin),
        )

        assert _ok(a)["tecnico_responsavel_id"] == d["tecnico_da_qualidade_id"]
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["versao"]) == (d["tecnico_da_qualidade_id"], v0 + 1)
        # Só a reatribuição que valeu deixa histórico (API-14); a recusada, nenhum.
        assert estado["historicos"] == [("Atribuição de responsável", None, None)]
        assert webhook == []


class TestT4bDistribuicaoDoChamadoSemResponsavel:
    """
    API-14: o chamado nasce sem responsável e a equipe o distribui. "Assumir"
    é uma atribuição como as outras: de duas com a mesma versão, uma vale.
    """

    @pytest.fixture
    def na_fila(self, base, sessao):
        return {**base, "v0": _gravar(sessao, tecnico_responsavel_id=None)}

    def _beto(self, autenticar, d):
        return autenticar(d["outro_tecnico_da_qualidade_id"], "beto.qualidade", "Tecnico")

    def test_dois_assumem_ao_mesmo_tempo_e_so_o_primeiro_fica(
        self, cliente, na_fila, sessao, autenticar, url_do_banco, pausa, webhook
    ):
        d, v0 = na_fila, na_fila["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(
                cliente, {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": v0},
                _atendente(autenticar, d),
            ),
            lambda: _put(
                cliente, {"tecnico_responsavel_id": d["outro_tecnico_da_qualidade_id"], "versao_esperada": v0},
                self._beto(autenticar, d),
            ),
        )

        assert _ok(a)["tecnico_responsavel_id"] == d["tecnico_da_qualidade_id"]
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["versao"]) == (d["tecnico_da_qualidade_id"], v0 + 1)
        assert estado["historicos"] == [("Atribuição de responsável", None, None)]
        autores = sessao.execute(
            text("SELECT usuario_id, descricao FROM historico_chamados WHERE chamado_id = :id"), {"id": QUALIDADE}
        ).all()
        assert [tuple(linha) for linha in autores] == [
            (d["tecnico_da_qualidade_id"], "Responsável definido: bruno.qualidade (antes: aguardando atribuição)")
        ]
        assert webhook == []

    def test_largando_juntos_exatamente_um_assume(self, cliente, na_fila, sessao, autenticar):
        """Sem pausa: quem vence é do acaso; quantos vencem, não."""
        d, v0 = na_fila, na_fila["v0"]
        largada = threading.Barrier(2, timeout=TEMPO_MAXIMO)
        candidatos = {
            d["tecnico_da_qualidade_id"]: _atendente(autenticar, d),
            d["outro_tecnico_da_qualidade_id"]: self._beto(autenticar, d),
        }

        def assumir(usuario_id):
            largada.wait()
            return _put(cliente, {"tecnico_responsavel_id": usuario_id, "versao_esperada": v0}, candidatos[usuario_id])

        esperas = {uid: em_paralelo(lambda uid=uid: assumir(uid)) for uid in candidatos}
        respostas = {uid: esperar() for uid, esperar in esperas.items()}

        assert sorted(r.status_code for r in respostas.values()) == [200, 409]
        (vencedor,) = [uid for uid, r in respostas.items() if r.status_code == 200]
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["versao"]) == (vencedor, v0 + 1)
        assert estado["historicos"] == [("Atribuição de responsável", None, None)]

    def test_atribuicao_primeiro_o_inicio_com_a_versao_antiga_e_409(
        self, cliente, na_fila, sessao, autenticar, url_do_banco, pausa
    ):
        d, v0 = na_fila, na_fila["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(
                cliente, {"tecnico_responsavel_id": d["outro_tecnico_da_qualidade_id"], "versao_esperada": v0},
                _admin(autenticar, d),
            ),
            lambda: _put(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
        )

        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["status"]) == (d["outro_tecnico_da_qualidade_id"], "Aberto")

        # Com a versão nova, o colega atende o chamado já atribuído a outro.
        _ok(_put(cliente, {"status": "Em Andamento", "versao_esperada": v0 + 1}, _atendente(autenticar, d)))
        assert _estado(sessao)["historicos"] == [
            ("Atribuição de responsável", None, None),
            ("Alteração de status", "Aberto", "Em Andamento"),
        ]

    @pytest.mark.parametrize("rota", [_put, _atender], ids=["put", "atendimento"])
    def test_inicio_recusado_solta_o_lock_e_nao_mexe_na_versao(
        self, cliente, na_fila, sessao, autenticar, url_do_banco, pausa, rota
    ):
        # A começa o atendimento do chamado sem responsável e para com a linha
        # travada; B, que atribui, espera. A é recusada (409 de estado, não de
        # versão), o rollback solta o lock, e a atribuição de B vale com a
        # mesma versão — a recusa não gravou nada.
        d, v0 = na_fila, na_fila["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: rota(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
            lambda: _put(
                cliente, {"tecnico_responsavel_id": d["tecnico_da_qualidade_id"], "versao_esperada": v0},
                _atendente(autenticar, d),
            ),
        )

        assert a.status_code == 409
        assert a.json() == {"detail": chamados_endpoint.AGUARDANDO_ATRIBUICAO}
        assert _ok(b)["versao"] == v0 + 1
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["status"], estado["versao"]) == (
            d["tecnico_da_qualidade_id"], "Aberto", v0 + 1,
        )
        assert estado["historicos"] == [("Atribuição de responsável", None, None)]


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
            lambda: _put(
                cliente, {"tecnico_responsavel_id": d["outro_tecnico_da_qualidade_id"], "versao_esperada": v0},
                _admin(autenticar, d),
            ),
            lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
        )

        _ok(a)
        # A autorização, relida sob o lock, vem antes da versão. Desde a API-13
        # o antigo responsável é Técnico da Qualidade e segue lendo o chamado
        # pelo perfil: ouve o 403 "Só o responsável atual", sem versao_atual.
        # Até a API-12 era a ana, de perfil comum, que perdia a leitura (D4) e
        # ouvia o 404 de um id que não existe (API-6, D12).
        assert b.status_code == 403
        assert b.json() == {"detail": "Só o responsável atual pode atender este chamado"}
        estado = _estado(sessao)
        # O único histórico é o da reatribuição (API-14); o atendimento recusado não deixa nenhum.
        assert (estado["tecnico_responsavel_id"], estado["status"], estado["historicos"]) == (
            d["outro_tecnico_da_qualidade_id"], "Aberto", [("Atribuição de responsável", None, None)],
        )

    def test_atendimento_primeiro_a_reatribuicao_antiga_e_409(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa
    ):
        d, v0 = base, base["v0"]
        admin = _admin(autenticar, d)
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
            lambda: _put(cliente, {"tecnico_responsavel_id": d["outro_tecnico_da_qualidade_id"], "versao_esperada": v0}, admin),
        )

        _ok(a)
        assert b.status_code == 409 and b.json() == _desatualizada(v0 + 1)
        assert _estado(sessao)["tecnico_responsavel_id"] == d["tecnico_da_qualidade_id"]

        # Com a versão nova: a elegibilidade continua valendo...
        inelegivel = _put(cliente, {"tecnico_responsavel_id": d["inativo_id"], "versao_esperada": v0 + 1}, admin)
        assert inelegivel.status_code == 400
        # ...a reatribuição válida passa, e o antigo responsável deixa de atender.
        _ok(_put(cliente, {"tecnico_responsavel_id": d["outro_tecnico_da_qualidade_id"], "versao_esperada": v0 + 1}, admin))
        antigo = _atender(cliente, {"status": "Aguardando", "versao_esperada": v0 + 2}, _atendente(autenticar, d))
        # Desde a API-13 o antigo responsável é Técnico da Qualidade e segue
        # lendo pelo perfil: 403 de quem não é o responsável atual. Até a
        # API-12 era a ana, de perfil comum, que perdia a leitura e ouvia 404.
        assert antigo.status_code == 403
        assert antigo.json() == {"detail": "Só o responsável atual pode atender este chamado"}
        estado = _estado(sessao)
        assert (estado["tecnico_responsavel_id"], estado["status"], estado["versao"]) == (
            d["outro_tecnico_da_qualidade_id"], "Em Andamento", v0 + 2,
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


# --------------------------------------------------------------------------
# T8–T14
# --------------------------------------------------------------------------

def _linha(sessao, chamado_id=QUALIDADE):
    """A linha inteira, para provar que nada mudou."""
    sessao.rollback()
    return dict(sessao.execute(text("SELECT * FROM chamados WHERE id = :id"), {"id": chamado_id}).mappings().one())


def _historicos(sessao, chamado_id=QUALIDADE):
    return _estado(sessao, chamado_id)["historicos"]


class FalhaDepoisDoFlush:
    """
    Substitui a função do endpoint que grava o histórico: põe o histórico na
    transação, manda o INSERT ao banco (flush), para até o teste liberar, e
    então lança. O UPDATE do chamado e o INSERT do histórico já estão no banco,
    sem commit — é o pior momento para falhar.
    """

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


class TestT8RollbackDepoisDoFlush:
    @pytest.mark.parametrize(
        "rota,funcao",
        [("put", "adicionar_historico"), ("arquivar", "adicionar_historico"), ("atendimento", "registrar_historico")],
    )
    def test_falha_no_meio_desfaz_chamado_e_historico_e_solta_o_lock(
        self, cliente, base, sessao, autenticar, url_do_banco, monkeypatch, rota, funcao
    ):
        d, v0 = base, base["v0"]
        falha = FalhaDepoisDoFlush()
        monkeypatch.setattr(chamados_endpoint, funcao, falha)
        antes = _linha(sessao)
        requisicao = {
            "put": lambda: _put(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _admin(autenticar, d)),
            "arquivar": lambda: _marca(cliente, "arquivar", {"versao_esperada": v0}, _admin(autenticar, d)),
            "atendimento": lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _atendente(autenticar, d)),
        }[rota]

        esperar = em_paralelo(requisicao)
        observador = psycopg2.connect(url_do_banco)
        try:
            falha.esperar_parar()
            with observador.cursor() as cur:
                # O INSERT do histórico foi ao banco (a sessão segura o lock da tabela)...
                cur.execute(
                    "SELECT count(*) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                    "WHERE l.pid = %s AND c.relname = 'historico_chamados' AND l.mode = 'RowExclusiveLock'",
                    (falha.pid,),
                )
                assert cur.fetchone()[0] == 1
                # ...mas, sem commit, ninguém o vê, nem a versão nova.
                cur.execute("SELECT versao FROM chamados WHERE id = %s", (QUALIDADE,))
                assert cur.fetchone()[0] == v0
                cur.execute("SELECT count(*) FROM historico_chamados WHERE chamado_id = %s", (QUALIDADE,))
                assert cur.fetchone()[0] == 0
                # E a linha está travada pela requisição.
                with pytest.raises(psycopg2.errors.LockNotAvailable):
                    cur.execute("SELECT 1 FROM chamados WHERE id = %s FOR UPDATE NOWAIT", (QUALIDADE,))
            observador.rollback()

            falha.liberar()
            with pytest.raises(RuntimeError, match="falha simulada"):
                esperar()

            # Rollback dos dois, e o lock solto.
            with observador.cursor() as cur:
                cur.execute("SELECT 1 FROM chamados WHERE id = %s FOR UPDATE NOWAIT", (QUALIDADE,))
            observador.rollback()
        finally:
            falha.liberar()
            observador.close()
        assert _linha(sessao) == antes
        assert _historicos(sessao) == []


class TestT9PutDeVariosCamposDesatualizado:
    def test_nenhum_campo_e_gravado(self, cliente, base, sessao, autenticar):
        d, v0 = base, base["v0"]
        v1 = _gravar(sessao, observacoes="mudado por outra pessoa")
        antes = _linha(sessao)
        corpo = {
            "titulo": "Laudo do lote 42 reemitido pela Qualidade",
            "prioridade": "Crítica",
            "urgencia": "Urgente",
            "status": "Em Andamento",
            "tecnico_responsavel_id": d["outro_tecnico_da_qualidade_id"],
            "solucao": SOLUCAO,
            "observacoes": "edição em cima de dado velho",
            "avaliacao": 3,
            "versao_esperada": v0,
        }

        resposta = _put(cliente, corpo, _admin(autenticar, d))

        assert resposta.status_code == 409 and resposta.json() == _desatualizada(v1)
        assert _linha(sessao) == antes
        assert _historicos(sessao) == []

    def test_a_versao_vem_antes_da_validacao_do_responsavel(self, cliente, base, sessao, autenticar):
        d, v0 = base, base["v0"]
        v1 = _gravar(sessao, prioridade="Alta")

        resposta = _put(cliente, {"tecnico_responsavel_id": d["inativo_id"], "versao_esperada": v0}, _admin(autenticar, d))

        assert resposta.status_code == 409 and resposta.json() == _desatualizada(v1)


class TestT10VersaoPorRota:
    def test_cada_escrita_efetiva_sobe_um_e_a_resposta_diz_a_gravada(self, cliente, base, sessao, autenticar):
        d, v = base, base["v0"]
        admin, atendente = _admin(autenticar, d), _atendente(autenticar, d)
        solicitante = autenticar(d["comum_id"], "usuario.teste", "Usuario")

        def avaliar(nota):
            return cliente.patch(f"/api/v1/chamados/{QUALIDADE}/avaliar", json={"avaliacao": nota}, headers=solicitante)

        passos = [
            ("PUT de prioridade", lambda v: _put(cliente, {"prioridade": "Alta", "versao_esperada": v}, admin), 1),
            ("PUT sem mudança", lambda v: _put(cliente, {"prioridade": "Alta", "versao_esperada": v}, admin), 0),
            ("atendimento", lambda v: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v}, atendente), 1),
            ("arquivar", lambda v: _marca(cliente, "arquivar", {"versao_esperada": v}, admin), 1),
            ("desarquivar", lambda v: _marca(cliente, "desarquivar", {"versao_esperada": v}, admin), 1),
            ("PUT de resolução", lambda v: _put(cliente, {"status": "Resolvido", "solucao": SOLUCAO, "versao_esperada": v}, admin), 1),
            ("avaliação", lambda v: avaliar(5), 1),
            ("mesma avaliação", lambda v: avaliar(5), 0),
            ("cancelar", lambda v: _marca(cliente, "cancelar", {"versao_esperada": v}, admin), 1),
        ]
        for nome, passo, incremento in passos:
            corpo = _ok(passo(v))
            gravada = _estado(sessao)["versao"]
            assert (corpo["versao"], gravada) == (v + incremento, v + incremento), nome
            v = gravada

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE chamados SET status = status WHERE id = 101",
            "UPDATE chamados SET updated_at = now(), data_atualizacao = now() WHERE id = 101",
        ],
    )
    def test_update_sem_mudanca_de_dado_nao_sobe(self, base, sessao, sql):
        sessao.execute(text(sql))
        sessao.commit()
        assert _estado(sessao)["versao"] == base["v0"]


class TestT11TiSemControleDeVersao:
    TI = 100

    def test_ti_segue_sem_versao_sem_lock_e_com_o_webhook(self, cliente, base, sessao, autenticar, engine, webhook):
        d = base
        admin = _admin(autenticar, d)
        with sql_emitido(engine) as comandos:
            editado = _ok(_put(cliente, {"tecnico_responsavel_id": d["tecnico_id"], "status": "Em Andamento"}, admin, self.TI))
            _ok(_marca(cliente, "arquivar", None, admin, self.TI))
            _ok(_marca(cliente, "desarquivar", None, admin, self.TI))
            _ok(_marca(cliente, "cancelar", {}, admin, self.TI))

        assert comandos and not [c for c in comandos if "FOR UPDATE" in c.upper()]
        assert editado["tecnico_responsavel_id"] == d["tecnico_id"]
        assert _historicos(sessao, self.TI)[0] == ("Alteração de status", "Aberto", "Em Andamento")
        assert [(w["tecnico_id"], w["acao"]) for w in webhook] == [(d["tecnico_id"], "atribuido")]

    def test_a_qualidade_por_contraste_pede_o_lock(self, cliente, base, autenticar, engine):
        with sql_emitido(engine) as comandos:
            _ok(_put(cliente, {"prioridade": "Alta", "versao_esperada": base["v0"]}, _admin(autenticar, base)))
        assert [c for c in comandos if "FOR UPDATE" in c.upper()]

    def test_ti_com_versao_velha_ainda_e_409(self, cliente, base, sessao, autenticar):
        v1 = _gravar(sessao, self.TI, prioridade="Alta")
        resposta = _put(cliente, {"status": "Em Andamento", "versao_esperada": v1 - 1}, _admin(autenticar, base), self.TI)
        assert resposta.status_code == 409 and resposta.json() == _desatualizada(v1)

    def test_lock_externo_bloqueia_a_qualidade_e_nao_a_ti(self, cliente, base, autenticar, url_do_banco):
        """
        Outra transação segura FOR KEY SHARE nas duas linhas. O UPDATE simples
        da TI não conflita com ele; o SELECT ... FOR UPDATE da Qualidade, sim.
        """
        admin = _admin(autenticar, base)
        externa = psycopg2.connect(url_do_banco)
        try:
            with externa.cursor() as cur:
                cur.execute("SELECT id FROM chamados WHERE id IN (100, 101) FOR KEY SHARE")
                cur.execute("SELECT pg_backend_pid()")
                pid_externo = cur.fetchone()[0]

            # TI: termina com o lock externo ainda de pé.
            _ok(em_paralelo(lambda: _put(cliente, {"prioridade": "Alta"}, admin, self.TI))())

            # Qualidade: espera o lock externo — e o banco mostra quem bloqueia quem.
            esperar = em_paralelo(lambda: _put(cliente, {"prioridade": "Alta", "versao_esperada": base["v0"]}, admin))
            esperar_bloqueio(url_do_banco, pid_externo)
            externa.rollback()
            assert _ok(esperar())["versao"] == base["v0"] + 1
        finally:
            externa.close()


class TestT12VersaoAusente:
    @pytest.mark.parametrize("rota", ["put", "atendimento", "cancelar", "arquivar", "desarquivar", "marca com corpo vazio"])
    def test_428_e_nada_gravado(self, cliente, base, sessao, autenticar, rota):
        d = base
        admin = _admin(autenticar, d)
        antes = _linha(sessao)
        resposta = {
            "put": lambda: _put(cliente, {"prioridade": "Alta"}, admin),
            "atendimento": lambda: _atender(cliente, {"status": "Em Andamento"}, _atendente(autenticar, d)),
            "cancelar": lambda: _marca(cliente, "cancelar", None, admin),
            "arquivar": lambda: _marca(cliente, "arquivar", None, admin),
            "desarquivar": lambda: _marca(cliente, "desarquivar", None, admin),
            "marca com corpo vazio": lambda: _marca(cliente, "arquivar", {}, admin),
        }[rota]()

        assert resposta.status_code == 428 and resposta.json() == {"detail": "Informe a versão do chamado"}
        assert _linha(sessao) == antes
        assert _historicos(sessao) == []


class TestT13VersaoInvalida:
    @pytest.mark.parametrize("valor", [None, True, "1", 0, -1, 1.5])
    @pytest.mark.parametrize("rota", ["put", "arquivar"])
    def test_422_e_nada_gravado(self, cliente, base, sessao, autenticar, rota, valor):
        admin = _admin(autenticar, base)
        antes = _linha(sessao)
        if rota == "put":
            resposta = _put(cliente, {"prioridade": "Alta", "versao_esperada": valor}, admin)
        else:
            resposta = _marca(cliente, "arquivar", {"versao_esperada": valor}, admin)

        assert resposta.status_code == 422
        assert "versao_atual" not in resposta.json()
        assert _linha(sessao) == antes

    def test_versao_de_outro_chamado_e_409_com_a_versao_deste(self, cliente, base, sessao, autenticar):
        sessao.execute(text(
            "INSERT INTO chamados (id, protocolo, solicitante_id, titulo, descricao, status, prioridade, "
            "setor_destino, tecnico_responsavel_id) SELECT 102, 'CH-TESTE-102', solicitante_id, titulo, "
            "descricao, status, prioridade, setor_destino, tecnico_responsavel_id FROM chamados WHERE id = 101"
        ))
        sessao.commit()
        for prioridade in ("Alta", "Crítica", "Baixa"):
            versao_do_outro = _gravar(sessao, 102, prioridade=prioridade)
        assert versao_do_outro != base["v0"]

        resposta = _put(cliente, {"status": "Em Andamento", "versao_esperada": versao_do_outro}, _admin(autenticar, base))

        assert resposta.status_code == 409 and resposta.json() == _desatualizada(base["v0"])


class TestT14SqlDireto:
    def test_update_por_fora_sobe_a_versao_e_o_cliente_antigo_recebe_409(self, cliente, base, sessao, autenticar):
        v1 = _gravar(sessao, prioridade="Alta")
        assert v1 == base["v0"] + 1
        resposta = _put(cliente, {"status": "Em Andamento", "versao_esperada": base["v0"]}, _admin(autenticar, base))
        assert resposta.status_code == 409 and resposta.json() == _desatualizada(v1)

    def test_update_por_fora_espera_a_api_e_as_duas_mudancas_ficam(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa
    ):
        v0 = base["v0"]

        def por_fora():
            conexao = psycopg2.connect(url_do_banco)
            try:
                with conexao.cursor() as cur:
                    cur.execute("UPDATE chamados SET observacoes = 'ajuste por SQL' WHERE id = %s", (QUALIDADE,))
                conexao.commit()
            finally:
                conexao.close()

        a, _ = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"status": "Em Andamento", "versao_esperada": v0}, _admin(autenticar, base)),
            por_fora,
        )

        assert _ok(a)["versao"] == v0 + 1
        linha = _linha(sessao)
        assert (linha["status"], linha["observacoes"], linha["versao"]) == ("Em Andamento", "ajuste por SQL", v0 + 2)


# --------------------------------------------------------------------------
# Avaliação × atendimento
# --------------------------------------------------------------------------

class TestAvaliacaoEAtendimento:
    @pytest.fixture
    def resolvido(self, base, sessao, autenticar):
        v = _gravar(sessao, status="Resolvido", solucao=SOLUCAO)
        return {**base, "v": v, "solicitante": autenticar(base["comum_id"], "usuario.teste", "Usuario")}

    @staticmethod
    def _avaliar(cliente, headers, nota=4):
        return cliente.patch(f"/api/v1/chamados/{QUALIDADE}/avaliar", json={"avaliacao": nota}, headers=headers)

    def test_avaliacao_primeiro_e_reabertura_antiga_e_409(self, cliente, resolvido, sessao, autenticar):
        d, v = resolvido, resolvido["v"]
        assert _ok(self._avaliar(cliente, d["solicitante"]))["versao"] == v + 1

        resposta = _atender(cliente, {"status": "Em Andamento", "versao_esperada": v}, _atendente(autenticar, d))

        assert resposta.status_code == 409 and resposta.json() == _desatualizada(v + 1)
        estado = _estado(sessao)
        assert (estado["status"], estado["avaliacao"]) == ("Resolvido", 4)

    def test_concorrentes_as_duas_gravam_sem_perder_nada(self, cliente, resolvido, sessao, autenticar, url_do_banco, pausa):
        """
        A avaliação não trava nem confere versão (fora do escopo da API-4b): lê
        "Resolvido" sem lock, e o UPDATE dela espera o da reabertura. As duas
        gravam — status de uma, nota da outra. É o comportamento de hoje,
        registrado: a nota fica num chamado já reaberto.
        """
        d, v = resolvido, resolvido["v"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _atender(cliente, {"status": "Em Andamento", "versao_esperada": v}, _atendente(autenticar, d)),
            lambda: self._avaliar(cliente, d["solicitante"]),
        )

        _ok(a)
        _ok(b)
        estado = _estado(sessao)
        assert (estado["status"], estado["avaliacao"], estado["versao"]) == ("Em Andamento", 4, v + 2)
        assert [h[0] for h in estado["historicos"]] == ["Alteração de status", "Avaliação do atendimento"]

    def test_atendente_nao_avalia(self, cliente, resolvido, sessao, autenticar):
        resposta = self._avaliar(cliente, _atendente(autenticar, resolvido))
        assert resposta.status_code == 403
        assert _estado(sessao)["versao"] == resolvido["v"]


# --------------------------------------------------------------------------
# Segurança: a versão atual só vai para quem pode escrever
# --------------------------------------------------------------------------

class TestSegurancaDaVersao:
    @pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer token-invalido"}])
    def test_401_nao_diz_a_versao(self, cliente, base, sessao, headers):
        v1 = _gravar(sessao, prioridade="Alta")
        for resposta in (
            _put(cliente, {"status": "Em Andamento", "versao_esperada": v1 - 1}, headers),
            _atender(cliente, {"status": "Em Andamento", "versao_esperada": v1 - 1}, headers),
            _marca(cliente, "arquivar", {"versao_esperada": v1 - 1}, headers),
        ):
            assert resposta.status_code == 401
            assert "versao_atual" not in resposta.json()

    def test_403_por_perfil_ou_autoria_nao_diz_a_versao(self, cliente, base, sessao, autenticar):
        # A ana, de perfil comum, volta a responsável por SQL (estado legado,
        # anterior à API-13): ela lê o chamado e não pode escrever por perfil
        # nem por autoria. O Técnico da Qualidade, que hoje atende, é da equipe
        # e escreveria — não serve para este caso.
        v1 = _gravar(sessao, prioridade="Alta", tecnico_responsavel_id=base["atendente_id"])
        comum = autenticar(base["comum_id"], "usuario.teste", "Usuario")
        atendente = autenticar(base["atendente_id"], "ana.qualidade", "Usuario")
        for resposta in (
            _marca(cliente, "arquivar", {"versao_esperada": v1 - 1}, comum),
            _put(cliente, {"status": "Em Andamento", "versao_esperada": v1 - 1}, atendente),
            _marca(cliente, "cancelar", {"versao_esperada": v1 - 1}, atendente),
        ):
            assert resposta.status_code == 403
            assert "versao_atual" not in resposta.json()
        assert _linha(sessao)["versao"] == v1

    def test_quem_nao_atende_espera_o_lock_e_recebe_403_sem_a_versao(
        self, cliente, base, sessao, autenticar, url_do_banco, pausa
    ):
        """O atendimento trava antes de autorizar; mesmo depois de esperar, quem não é o responsável não vê a versão."""
        d, v0 = base, base["v0"]
        a, b = _cena(
            url_do_banco, pausa,
            lambda: _put(cliente, {"prioridade": "Alta", "versao_esperada": v0}, _admin(autenticar, d)),
            lambda: _atender(
                cliente, {"status": "Em Andamento", "versao_esperada": v0},
                autenticar(d["outro_tecnico_da_qualidade_id"], "beto.qualidade", "Tecnico"),
            ),
        )

        _ok(a)
        assert b.status_code == 403 and "versao_atual" not in b.json()
        assert _estado(sessao)["status"] == "Aberto"

    def test_o_409_tem_so_detail_codigo_e_versao_atual(self, cliente, base, sessao, autenticar):
        v1 = _gravar(sessao, prioridade="Alta")
        resposta = _put(cliente, {"status": "Em Andamento", "versao_esperada": v1 - 1}, _admin(autenticar, base))
        assert resposta.status_code == 409
        assert set(resposta.json()) == {"detail", "codigo", "versao_atual"}


# --------------------------------------------------------------------------
# Transações que não atualizam nada
# --------------------------------------------------------------------------

class TestSemAtualizacao:
    def test_put_com_os_mesmos_valores_mantem_versao_e_historico(self, cliente, base, sessao, autenticar):
        v0 = base["v0"]
        corpo = _ok(_put(cliente, {"status": "Aberto", "prioridade": "Média", "versao_esperada": v0}, _admin(autenticar, base)))
        assert corpo["versao"] == v0
        assert (_estado(sessao)["versao"], _historicos(sessao)) == (v0, [])

    @pytest.mark.parametrize(
        "marca,campo,detalhe",
        [("arquivar", "arquivado", "Chamado já está arquivado"), ("cancelar", "cancelado", "Chamado já está cancelado")],
    )
    def test_marca_repetida_e_400_sem_mudar_a_versao(self, cliente, base, sessao, autenticar, marca, campo, detalhe):
        v = _gravar(sessao, **{campo: True})
        antes = _linha(sessao)
        resposta = _marca(cliente, marca, {"versao_esperada": v}, _admin(autenticar, base))
        assert resposta.status_code == 400 and resposta.json() == {"detail": detalhe}
        assert _linha(sessao) == antes

    def test_desarquivar_o_que_nao_esta_arquivado_e_400(self, cliente, base, sessao, autenticar):
        antes = _linha(sessao)
        resposta = _marca(cliente, "desarquivar", {"versao_esperada": base["v0"]}, _admin(autenticar, base))
        assert resposta.status_code == 400
        assert _linha(sessao) == antes

    def test_transicao_invalida_e_409_de_estado_sem_codigo_de_versao(self, cliente, base, sessao, autenticar):
        antes = _linha(sessao)
        resposta = _atender(
            cliente, {"status": "Resolvido", "solucao": SOLUCAO, "versao_esperada": base["v0"]}, _atendente(autenticar, base)
        )
        assert resposta.status_code == 409
        assert resposta.json() == {"detail": "Transição de Aberto para Resolvido não permitida"}
        assert _linha(sessao) == antes
        assert _historicos(sessao) == []
