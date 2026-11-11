"""
`GET /chamados/responsaveis-ti` (API-9, F5-1): quem a tela pode oferecer como
novo responsável de chamado da TI.

Até a API-8 não havia essa lista: o frontend montava o seletor com
`GET /usuarios/` e um filtro de perfil, que oferecia técnicos de outro setor,
administradores de fora da TI e contas inativas — e o PUT os recusava. A lista
agora sai da mesma regra do PUT (`responsavel_ti_service`), e o que se prova
aqui é isso: quem pode pedir a lista, o que ela contém, e que ela e a
validação não discordam para nenhuma conta, em nenhuma configuração.
"""

import logging

import pytest
from sqlalchemy import event

import main
from app.models import Role, Usuario
from app.services.responsavel_ti_service import pode_ser_novo_responsavel
from leitura_cenario import CHAMADOS, ROLE_DE, cenario_de_leitura  # noqa: F401

API = "/api/v1"
ROTA = f"{API}/chamados/responsaveis-ti"
NEGADO = {"detail": "Requer perfil: Administrador ou Técnico da TI"}

# Candidatas além das do cenário de leitura. Ids e nomes fora de ordem de
# propósito: a lista sai por nome, não por id nem por ordem de cadastro.
TECNICO_TI_INATIVO = 60
CONTA_DE_SERVICO_TI = 61
PERFIL_DESCONHECIDO_TI = 62
PRIMEIRO_POR_NOME = 65  # técnico da TI, id alto e nome que vem antes de todos
ADMIN_TI_ULTIMO = 66  # administrador da TI, último por nome

# Elegíveis com SETORES_TI_IDS válida ("1"), na ordem esperada:
# aaa.tecnico.ti (65), admin.teste (10), tecnico.teste (20), zeca.ti (66).
ELEGIVEIS_NA_TI = [PRIMEIRO_POR_NOME, 10, 20, ADMIN_TI_ULTIMO]
TECNICO_COMERCIAL = 55  # do cenário de leitura: técnico no setor 4

# SETORES_TI_IDS → a lista esperada.
CONFIGURACOES = {
    "valida": ("1", ELEGIVEIS_NA_TI),
    "ausente": (None, []),
    "vazia": ("", []),
    "invalida": ("1,x", []),
    "com_duplicidade": ("1,1", ELEGIVEIS_NA_TI),
    "conflitante_com_qualidade": ("1,2", ELEGIVEIS_NA_TI),
    "so_qualidade": ("2", []),
    "outro_setor": ("4", [TECNICO_COMERCIAL]),
    "setor_inexistente": ("999", []),
    "valida_com_inexistente": ("1,999", ELEGIVEIS_NA_TI),
}

# Quem pede a lista, com a configuração válida.
AUTORIZADOS = {"admin", "admin_da_qualidade", "tecnico_ti"}
NEGADOS = {
    "tecnico_qualidade",
    "tecnico_sem_setor",
    "tecnico_outro_setor",
    "solicitante",
    "atendente",
    "colega_do_solicitante",
    "usuario_sem_setor",
    "conta_de_servico",
}


@pytest.fixture
def candidatos(cenario_de_leitura, sessao):
    sessao.add(Role(id=4, nome="Auditor"))
    sessao.flush()
    sessao.add_all([
        Usuario(id=TECNICO_TI_INATIVO, nome="tecnico.ti.inativo", role_id=2, setor_id=1, ativo=False),
        Usuario(
            id=CONTA_DE_SERVICO_TI, nome="painel.ti", role_id=2, setor_id=1, ativo=True,
            conta_de_servico=True,
        ),
        Usuario(id=PERFIL_DESCONHECIDO_TI, nome="auditor.ti", role_id=4, setor_id=1, ativo=True),
        Usuario(
            id=PRIMEIRO_POR_NOME, nome="aaa.tecnico.ti", role_id=2, setor_id=1, ativo=True,
            senha_hash="$2b$12$hash.de.teste.que.nao.pode.vazar",
        ),
        Usuario(id=ADMIN_TI_ULTIMO, nome="zeca.ti", role_id=1, setor_id=1, ativo=True),
    ])
    sessao.commit()
    return cenario_de_leitura


@pytest.fixture
def como(autenticar, cenario_de_leitura):
    def _como(quem):
        return autenticar(cenario_de_leitura[quem], quem, ROLE_DE.get(quem, "Usuario"))

    return _como


@pytest.fixture
def configurar(monkeypatch):
    def _configurar(configuracao):
        valor, _ = CONFIGURACOES[configuracao]
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", valor)

    return _configurar


def _ids(resposta):
    assert resposta.status_code == 200, resposta.text
    return [item["id"] for item in resposta.json()]


class TestQuemPede:
    @pytest.mark.parametrize("quem", sorted(AUTORIZADOS))
    def test_administrador_e_tecnico_da_ti_recebem_a_lista(self, cliente, como, candidatos, quem):
        assert _ids(cliente.get(ROTA, headers=como(quem))) == ELEGIVEIS_NA_TI

    @pytest.mark.parametrize("quem", sorted(NEGADOS))
    def test_os_outros_recebem_403(self, cliente, como, candidatos, quem):
        resposta = cliente.get(ROTA, headers=como(quem))
        assert (resposta.status_code, resposta.json()) == (403, NEGADO)

    def test_sem_token_401(self, cliente, candidatos):
        assert cliente.get(ROTA).status_code == 401

    def test_token_invalido_401(self, cliente, candidatos):
        assert cliente.get(ROTA, headers={"Authorization": "Bearer nao-e-um-token"}).status_code == 401

    def test_conta_inativa_recebe_o_403_de_sempre(self, cliente, autenticar, candidatos):
        h = autenticar(TECNICO_TI_INATIVO, "tecnico.ti.inativo", "Tecnico")
        resposta = cliente.get(ROTA, headers=h)
        assert (resposta.status_code, resposta.json()) == (403, {"detail": "Usuário inativo"})

    def test_o_perfil_do_token_nao_vale_o_do_banco_sim(self, cliente, autenticar, candidatos):
        """Token de usuário comum que diz ser Administrador: a role vem do banco."""
        h = autenticar(candidatos["solicitante"], "usuario.teste", "Administrador")
        assert cliente.get(ROTA, headers=h).status_code == 403

    @pytest.mark.parametrize("configuracao", CONFIGURACOES)
    def test_por_configuracao(self, cliente, como, candidatos, configurar, configuracao):
        """O administrador pede sempre; o técnico, só se a lista o puser na TI."""
        configurar(configuracao)
        assert cliente.get(ROTA, headers=como("admin")).status_code == 200
        ti_inclui_1 = 1 in main.settings.setores_ti_ids
        assert cliente.get(ROTA, headers=como("tecnico_ti")).status_code == (200 if ti_inclui_1 else 403)
        assert cliente.get(ROTA, headers=como("tecnico_qualidade")).status_code == 403
        assert cliente.get(ROTA, headers=como("solicitante")).status_code == 403
        comercial = cliente.get(ROTA, headers=como("tecnico_outro_setor")).status_code
        assert comercial == (200 if configuracao == "outro_setor" else 403)


class TestOQueVem:
    @pytest.mark.parametrize("configuracao", CONFIGURACOES)
    def test_lista_por_configuracao(self, cliente, como, candidatos, configurar, configuracao):
        configurar(configuracao)
        _, esperada = CONFIGURACOES[configuracao]
        assert _ids(cliente.get(ROTA, headers=como("admin"))) == esperada

    def test_so_id_e_nome(self, cliente, como, candidatos):
        resposta = cliente.get(ROTA, headers=como("admin"))
        assert resposta.json()[0] == {"id": PRIMEIRO_POR_NOME, "nome": "aaa.tecnico.ti"}
        assert all(set(item) == {"id", "nome"} for item in resposta.json())
        for proibido in ("senha", "hash", "$2b$", "ativo", "setor", "role", "conta_de_servico", "token"):
            assert proibido not in resposta.text

    @pytest.mark.parametrize(
        "conta",
        [
            TECNICO_TI_INATIVO,
            CONTA_DE_SERVICO_TI,
            PERFIL_DESCONHECIDO_TI,
            30,  # usuário comum no setor da TI
            52,  # outro usuário comum no setor da TI
            41,  # técnico da Qualidade
            45,  # administrador da Qualidade
            54,  # técnico sem setor
            TECNICO_COMERCIAL,  # técnico de outro setor
            42,  # inativo da Qualidade
            43,  # conta de serviço da Qualidade
        ],
    )
    def test_nao_contem_inelegiveis(self, cliente, como, candidatos, conta):
        assert conta not in _ids(cliente.get(ROTA, headers=como("admin")))

    def test_parametros_do_cliente_nao_ampliam_a_lista(self, cliente, como, candidatos):
        sem = _ids(cliente.get(ROTA, headers=como("admin")))
        com = _ids(cliente.get(
            ROTA,
            headers=como("admin"),
            params={
                "setor_id": 4, "setores_ti_ids": "1,2,4", "ativo": "false", "incluir_inativos": "true",
                "conta_de_servico": "true", "role": "Tecnico", "limit": 1000, "skip": 0,
            },
        ))
        assert com == sem == ELEGIVEIS_NA_TI

    def test_mudanca_de_conta_vale_no_proximo_pedido(self, cliente, sessao, como, candidatos):
        """Sem cache: desativar, reativar e mudar de setor aparecem na hora."""
        assert cliente.patch(f"{API}/usuarios/{PRIMEIRO_POR_NOME}/desativar", headers=como("admin")).status_code == 200
        assert PRIMEIRO_POR_NOME not in _ids(cliente.get(ROTA, headers=como("admin")))
        assert cliente.patch(f"{API}/usuarios/{PRIMEIRO_POR_NOME}/reativar", headers=como("admin")).status_code == 200
        assert PRIMEIRO_POR_NOME in _ids(cliente.get(ROTA, headers=como("admin")))
        sessao.get(Usuario, PRIMEIRO_POR_NOME).setor_id = 2
        sessao.commit()
        assert PRIMEIRO_POR_NOME not in _ids(cliente.get(ROTA, headers=como("admin")))

    def test_configuracao_ausente_deixa_diagnostico_no_log(self, cliente, como, candidatos, configurar, caplog):
        configurar("ausente")
        with caplog.at_level(logging.WARNING, logger="app.services.responsavel_ti_service"):
            assert _ids(cliente.get(ROTA, headers=como("admin"))) == []
        assert any("SETORES_TI_IDS" in r.getMessage() for r in caplog.records)

    def test_numero_de_consultas_nao_cresce_com_a_lista(self, cliente, sessao, como, candidatos):
        """Sem N+1: a role vem no mesmo SELECT das contas."""
        engine = sessao.get_bind()
        contadas = []

        def _contar(*_):
            contadas.append(1)

        def _consultas():
            contadas.clear()
            event.listen(engine, "before_cursor_execute", _contar)
            try:
                assert cliente.get(ROTA, headers=como("admin")).status_code == 200
            finally:
                event.remove(engine, "before_cursor_execute", _contar)
            return len(contadas)

        antes = _consultas()
        sessao.add_all([
            Usuario(id=700 + i, nome=f"tecnico.extra.{i:02d}", role_id=2, setor_id=1, ativo=True) for i in range(15)
        ])
        sessao.commit()
        assert _consultas() == antes
        assert len(cliente.get(ROTA, headers=como("admin")).json()) == len(ELEGIVEIS_NA_TI) + 15


class TestRota:
    def test_nao_e_lida_como_id_de_chamado(self, cliente, como, candidatos):
        resposta = cliente.get(ROTA, headers=como("admin"))
        assert resposta.status_code == 200
        assert isinstance(resposta.json(), list)
        assert "protocolo" not in resposta.text

    def test_as_rotas_de_chamado_por_id_seguem_iguais(self, cliente, como, candidatos):
        cid = CHAMADOS["ti_sem_responsavel"]
        assert cliente.get(f"{API}/chamados/{cid}", headers=como("admin")).json()["id"] == cid
        assert cliente.get(f"{API}/chamados/987654", headers=como("admin")).status_code == 404
        assert cliente.get(f"{API}/chamados/nao-e-id", headers=como("admin")).status_code == 422

    def test_sonda_d6_do_atendimento_intacta(self, cliente, como, candidatos):
        """O frontend sonda a rota de atendimento por GET e espera 405."""
        resposta = cliente.get(f"{API}/chamados/0/atendimento", headers=como("solicitante"))
        assert (resposta.status_code, resposta.json()) == (405, {"detail": "Method Not Allowed"})

    def test_atendentes_da_qualidade_seguem_abertos(self, cliente, como, candidatos):
        assert cliente.get(f"{API}/chamados/atendentes-qualidade", headers=como("solicitante")).status_code == 200

    def test_esta_no_openapi_com_o_esquema_minimo(self, cliente):
        esquema = cliente.get("/openapi.json").json()
        rota = esquema["paths"]["/api/v1/chamados/responsaveis-ti"]
        assert set(rota) == {"get"}
        assert set(esquema["components"]["schemas"]["ResponsavelTI"]["properties"]) == {"id", "nome"}


class TestListaEValidacaoNaoDiscordam:
    """A lista é exatamente quem o PUT aceita como novo responsável."""

    @pytest.mark.parametrize("configuracao", CONFIGURACOES)
    def test_para_toda_conta(self, cliente, sessao, como, candidatos, configurar, configuracao):
        configurar(configuracao)
        lista = set(_ids(cliente.get(ROTA, headers=como("admin"))))
        cid = CHAMADOS["ti_sem_responsavel"]
        aceitos = set()
        for conta in sorted(u.id for u in sessao.query(Usuario).all()):
            resposta = cliente.put(f"{API}/chamados/{cid}", headers=como("admin"), json={"tecnico_responsavel_id": conta})
            assert resposta.status_code in (200, 400), resposta.text
            if resposta.status_code == 200:
                aceitos.add(conta)
        assert aceitos == lista

    @pytest.mark.parametrize("configuracao", CONFIGURACOES)
    def test_e_a_funcao_da_regra(self, cliente, sessao, como, candidatos, configurar, configuracao):
        configurar(configuracao)
        lista = _ids(cliente.get(ROTA, headers=como("admin")))
        sessao.expire_all()
        assert set(lista) == {u.id for u in sessao.query(Usuario).all() if pode_ser_novo_responsavel(u)}
