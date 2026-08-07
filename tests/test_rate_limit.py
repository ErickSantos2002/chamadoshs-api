"""
Testes do limitador de tentativas de login.

Cobrem a JanelaDeslizante isolada, a leitura do IP real por trás do proxy, e o
ciclo 401 -> 429 no endpoint. São a evidência de que a proteção contra força
bruta funciona: sem eles, qualquer mexida no /auth/login passa a ser um salto
no escuro.

Nenhum teste depende do relógio real — a JanelaDeslizante aceita o instante
como parâmetro justamente para isso.
"""

import threading

import pytest
from fastapi.testclient import TestClient

import main
from app.api.deps import get_db
from app.api.endpoints import auth as auth_ep
from app.core.rate_limit import JanelaDeslizante

T0 = 1000.0  # instante arbitrário; monotonic não tem época definida


# ---------------------------------------------------------------------------
# JanelaDeslizante
# ---------------------------------------------------------------------------

def test_chave_nova_esta_liberada():
    j = JanelaDeslizante(max_eventos=3, janela_segundos=100)
    assert j.segundos_ate_liberar("a", T0) == 0


def test_abaixo_do_limite_continua_liberado():
    j = JanelaDeslizante(max_eventos=3, janela_segundos=100)
    j.registrar("a", T0)
    j.registrar("a", T0 + 1)
    assert j.segundos_ate_liberar("a", T0 + 2) == 0


def test_no_limite_bloqueia_e_informa_a_espera():
    j = JanelaDeslizante(max_eventos=3, janela_segundos=100)
    for i in range(3):
        j.registrar("a", T0 + i)

    espera = j.segundos_ate_liberar("a", T0 + 3)
    assert espera > 0
    # A liberação acontece quando a marca mais antiga sai da janela.
    assert espera <= 100


def test_chaves_sao_independentes():
    j = JanelaDeslizante(max_eventos=1, janela_segundos=100)
    j.registrar("a", T0)
    assert j.segundos_ate_liberar("a", T0) > 0
    assert j.segundos_ate_liberar("b", T0) == 0


def test_janela_desliza_e_libera_vaga():
    """
    A janela anda com o relógio: não existe a virada em que o atacante
    recupera todo o orçamento de uma vez.
    """
    j = JanelaDeslizante(max_eventos=3, janela_segundos=100)
    for i in range(3):
        j.registrar("a", T0 + i)

    assert j.segundos_ate_liberar("a", T0 + 99) > 0
    # Passados 100s da primeira marca, ela expira e abre exatamente uma vaga.
    assert j.segundos_ate_liberar("a", T0 + 101) == 0


def test_limpar_zera_a_contagem():
    j = JanelaDeslizante(max_eventos=2, janela_segundos=100)
    j.registrar("x", T0)
    j.registrar("x", T0)
    assert j.segundos_ate_liberar("x", T0) > 0

    j.limpar("x")
    assert j.segundos_ate_liberar("x", T0) == 0


def test_teto_de_chaves_impede_crescimento_sem_limite():
    """
    Sem teto, um ataque que varia o usuário a cada tentativa faria a própria
    proteção consumir memória sem limite.
    """
    j = JanelaDeslizante(max_eventos=5, janela_segundos=100, max_chaves=10)
    for i in range(500):
        j.registrar(f"user{i}", T0)

    assert len(j._eventos) <= 10


def test_sem_perda_de_contagem_sob_concorrencia():
    """
    O endpoint de login é `def`, não `async def`: o FastAPI o executa num
    threadpool, então há concorrência real sobre a estrutura interna.
    """
    j = JanelaDeslizante(max_eventos=10_000, janela_segundos=100)

    def martelar():
        for _ in range(500):
            j.registrar("concorrente")

    threads = [threading.Thread(target=martelar) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(j._eventos["concorrente"]) == 8 * 500


@pytest.mark.parametrize("max_eventos,janela", [(0, 100), (-1, 100), (5, 0), (5, -1)])
def test_configuracao_invalida_falha_na_construcao(max_eventos, janela):
    with pytest.raises(ValueError):
        JanelaDeslizante(max_eventos=max_eventos, janela_segundos=janela)


# ---------------------------------------------------------------------------
# Identificação do IP por trás do proxy
# ---------------------------------------------------------------------------

class _RequisicaoFalsa:
    def __init__(self, headers, host="10.0.0.1"):
        self.headers = headers
        self.client = type("Cliente", (), {"host": host})()


@pytest.fixture
def hops(monkeypatch):
    def definir(valor):
        monkeypatch.setattr(main.settings, "PROXY_HOPS_CONFIAVEIS", valor)

    return definir


def test_ip_com_um_proxy_usa_o_ultimo_elemento(hops):
    """
    Cada proxy anexa ao FIM do X-Forwarded-For o endereço que enxergou. O
    primeiro elemento veio do cliente e é falsificável — lê-lo permitiria
    furar o limite por IP à vontade.
    """
    hops(1)
    req = _RequisicaoFalsa({"x-forwarded-for": "1.1.1.1 , 203.0.113.9"})
    assert auth_ep._ip_do_cliente(req) == "203.0.113.9"


def test_ip_sem_proxy_ignora_o_header(hops):
    hops(0)
    req = _RequisicaoFalsa({"x-forwarded-for": "1.1.1.1"})
    assert auth_ep._ip_do_cliente(req) == "10.0.0.1"


def test_ip_sem_header_usa_o_da_conexao(hops):
    hops(1)
    req = _RequisicaoFalsa({})
    assert auth_ep._ip_do_cliente(req) == "10.0.0.1"


def test_ip_com_dois_proxies_pula_os_dois_ultimos(hops):
    hops(2)
    req = _RequisicaoFalsa({"x-forwarded-for": "1.1.1.1, 203.0.113.9, 10.1.0.5"})
    assert auth_ep._ip_do_cliente(req) == "203.0.113.9"


# ---------------------------------------------------------------------------
# /auth/login sob força bruta
# ---------------------------------------------------------------------------

class _ConsultaFalsa:
    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None  # usuário inexistente -> 401


class _BancoFalso:
    def query(self, *args, **kwargs):
        return _ConsultaFalsa()


@pytest.fixture
def cliente():
    """TestClient com o banco substituído e os contadores zerados."""
    main.app.dependency_overrides[get_db] = lambda: _BancoFalso()
    auth_ep._falhas_por_usuario.reset()
    auth_ep._falhas_por_ip.reset()

    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c

    main.app.dependency_overrides.clear()
    auth_ep._falhas_por_usuario.reset()
    auth_ep._falhas_por_ip.reset()


def _tentar(cliente, nome="admin", senha="chute"):
    return cliente.post("/api/v1/auth/login", json={"nome": nome, "senha": senha})


def test_tentativas_ate_o_limite_retornam_401(cliente):
    limite = main.settings.LOGIN_MAX_FALHAS_POR_USUARIO
    codigos = [_tentar(cliente).status_code for _ in range(limite)]
    assert codigos == [401] * limite


def test_excedido_o_limite_retorna_429(cliente):
    limite = main.settings.LOGIN_MAX_FALHAS_POR_USUARIO
    for _ in range(limite):
        _tentar(cliente)

    resposta = _tentar(cliente)
    assert resposta.status_code == 429


def test_resposta_429_traz_retry_after_numerico(cliente):
    for _ in range(main.settings.LOGIN_MAX_FALHAS_POR_USUARIO):
        _tentar(cliente)

    resposta = _tentar(cliente)
    retry = resposta.headers.get("retry-after")
    assert retry is not None
    assert retry.isdigit()
    assert int(retry) > 0


def test_alternar_a_caixa_nao_reseta_a_contagem(cliente):
    """
    O login é case-insensitive (Usuario.nome.ilike). Se a contagem não fosse,
    alternar maiúsculas multiplicaria as tentativas disponíveis.
    """
    for _ in range(main.settings.LOGIN_MAX_FALHAS_POR_USUARIO):
        _tentar(cliente, nome="admin")

    assert _tentar(cliente, nome="ADMIN").status_code == 429
    assert _tentar(cliente, nome="  Admin  ").status_code == 429


def test_bloqueio_de_um_usuario_nao_atinge_outro(cliente):
    """
    O limite por IP é bem mais folgado que o por usuário, justamente para o
    escritório atrás de um único IP público não cair junto.
    """
    for _ in range(main.settings.LOGIN_MAX_FALHAS_POR_USUARIO):
        _tentar(cliente, nome="admin")

    assert _tentar(cliente, nome="outro.usuario").status_code == 401
