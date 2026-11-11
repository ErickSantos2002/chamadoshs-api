"""
`SETORES_TI_IDS` e a classificação dos técnicos (API-6, D10 e H1).

Até a API-5, técnico de qualquer setor que não fosse o da Qualidade era da
TI: lia os dois setores de destino e alterava qualquer chamado. Agora a TI é
uma lista explícita de setores, e o que não está nela não tem alcance por
perfil — nem por exclusão, nem com a configuração ausente. Desde a API-13 o
alcance da TI é só o setor de destino TI; até a API-12 eram os dois (D1).

Três partes: a leitura da variável (sem banco), a classificação dos sete
tipos de conta (no serviço) e o comportamento das rotas com a configuração
ausente, vazia, inválida ou em conflito com a Qualidade.
"""

import logging

import pytest

import main
from app.core.config import Settings, interpretar_setores_ti
from app.models import Chamado, Role, Usuario
from app.services.leitura_service import (
    pode_alterar_como_equipe,
    pode_ler_chamado,
    setores_lidos_pelo_perfil,
)
from leitura_cenario import CHAMADOS, DA_TI, ROLE_DE, cenario_de_leitura  # noqa: F401

API = "/api/v1"


class TestInterpretacao:
    @pytest.mark.parametrize(
        "valor,ids",
        [
            ("1", {1}),
            (" 1 , 7 ", {1, 7}),
            ("7,1", {1, 7}),
            ("12", {12}),
        ],
    )
    def test_lista_valida(self, valor, ids):
        lidos = interpretar_setores_ti(valor)
        assert lidos.estado == "valida"
        assert lidos.ids == ids
        assert not lidos.duplicados

    def test_repetidos_valem_uma_vez(self):
        lidos = interpretar_setores_ti("7,1,7")
        assert (lidos.estado, lidos.ids, lidos.duplicados) == ("valida", {1, 7}, True)

    def test_ausente_e_vazia_sao_estados_diferentes(self):
        assert interpretar_setores_ti(None).estado == "ausente"
        assert interpretar_setores_ti("").estado == "vazia"
        assert interpretar_setores_ti("   ").estado == "vazia"
        assert interpretar_setores_ti(None).ids == interpretar_setores_ti("").ids == frozenset()

    @pytest.mark.parametrize(
        "valor",
        ["0", "-1", "abc", "1,", ",1", "1,,2", "1;2", "1 2", "1.0", "[1,2]", "1,2O", "+1", "١", "1e3"],
    )
    def test_um_item_invalido_descarta_a_lista_inteira(self, valor):
        """Nem os ids válidos da lista são aproveitados: meio aplicada esconde o erro."""
        lidos = interpretar_setores_ti(valor)
        assert lidos.estado == "invalida"
        assert lidos.ids == frozenset()


class TestLidaDoAmbiente:
    """A variável lida do ambiente, como na subida — sem nunca impedir a API de subir."""

    def _settings(self, monkeypatch, setores_ti, qualidade=None):
        for nome, valor in (("SETORES_TI_IDS", setores_ti), ("SETOR_QUALIDADE_ID", qualidade)):
            if valor is None:
                monkeypatch.delenv(nome, raising=False)
            else:
                monkeypatch.setenv(nome, valor)
        return Settings(_env_file=None)

    def test_formato_com_virgula_nao_derruba_a_subida(self, monkeypatch):
        assert self._settings(monkeypatch, "1,7").setores_ti_ids == {1, 7}

    @pytest.mark.parametrize(
        "valor,trecho",
        [
            (None, "não definida"),
            ("", "vazia"),
            ("1,x", "não é uma lista de ids"),
        ],
    )
    def test_sem_lista_valida_ninguem_e_da_ti_e_o_log_diz(self, monkeypatch, caplog, valor, trecho):
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            config = self._settings(monkeypatch, valor)
        assert config.setores_ti_ids == frozenset()
        assert any(trecho in r.getMessage() for r in caplog.records)

    def test_repetidos_avisam(self, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            config = self._settings(monkeypatch, "1,1")
        assert config.setores_ti_ids == {1}
        assert any("repetidos" in r.getMessage() for r in caplog.records)

    def test_o_setor_da_qualidade_nunca_vale_como_ti(self, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            config = self._settings(monkeypatch, "1,2", qualidade="2")
        assert config.setores_ti_ids == {1}
        assert any("inclui o setor da Qualidade" in r.getMessage() for r in caplog.records)

    def test_lista_valida_sem_conflito_nao_avisa(self, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.config"):
            self._settings(monkeypatch, "1", qualidade="2")
        assert not [r for r in caplog.records if "SETORES_TI_IDS" in r.getMessage()]


def _usuario(sessao, usuario_id) -> Usuario:
    return sessao.get(Usuario, usuario_id)


class TestClassificacao:
    """Os sete tipos de conta da API-6, no serviço."""

    @pytest.mark.parametrize(
        "quem,alcance",
        [
            ("admin", set()),  # lê e altera tudo por outro caminho, não pelo alcance
            ("tecnico_ti", {"TI"}),  # API-13, setor em SETORES_TI_IDS; até a API-12, os dois (D1)
            ("tecnico_qualidade", {"QUALIDADE"}),  # D2
            ("tecnico_outro_setor", set()),  # D10
            ("tecnico_sem_setor", set()),  # H1
            ("solicitante", set()),  # usuário comum
            ("atendente", set()),  # usuário comum da Qualidade: atende pelo vínculo
        ],
    )
    def test_alcance_por_perfil(self, cenario_de_leitura, sessao, quem, alcance):
        assert setores_lidos_pelo_perfil(_usuario(sessao, cenario_de_leitura[quem])) == alcance

    def test_perfil_desconhecido_nao_tem_alcance(self, cenario_de_leitura, sessao):
        visitante = Usuario(id=999, nome="visitante", role_id=99, setor_id=1, ativo=True)
        visitante.role = Role(id=99, nome="Visitante")
        assert setores_lidos_pelo_perfil(visitante) == frozenset()
        assert not any(pode_alterar_como_equipe(visitante, c) for c in sessao.query(Chamado))

    @pytest.mark.parametrize(
        "quem,alteraveis",
        [
            ("admin", set(CHAMADOS)),
            ("admin_da_qualidade", set(CHAMADOS)),
            ("tecnico_ti", DA_TI),  # API-13: até a API-12, todos
            ("tecnico_qualidade", {"q_atribuido", "q_reatribuido"}),
            ("tecnico_outro_setor", set()),
            ("tecnico_sem_setor", set()),
            ("solicitante", set()),
            ("atendente", set()),
            ("outro_solicitante", set()),
        ],
    )
    def test_alterar_como_equipe_nao_vem_do_vinculo(self, cenario_de_leitura, sessao, quem, alteraveis):
        """
        O técnico da Qualidade lê o `ti_com_tecnico_da_q` (é o responsável),
        mas não o altera pelas rotas da equipe: o vínculo dá leitura, não poder.
        """
        usuario = _usuario(sessao, cenario_de_leitura[quem])
        chamados = {c.id: c for c in sessao.query(Chamado)}
        assert {n for n, cid in CHAMADOS.items() if pode_alterar_como_equipe(usuario, chamados[cid])} == alteraveis

    def test_o_que_a_equipe_altera_ela_le(self, cenario_de_leitura, sessao):
        for quem in ROLE_DE:
            usuario = _usuario(sessao, cenario_de_leitura[quem])
            for chamado in sessao.query(Chamado):
                if pode_alterar_como_equipe(usuario, chamado):
                    assert pode_ler_chamado(usuario, chamado), (quem, chamado.id)


@pytest.fixture
def como(cliente, autenticar, cenario_de_leitura):
    def _como(quem):
        return autenticar(cenario_de_leitura[quem], quem, ROLE_DE.get(quem, "Usuario"))

    return _como


def _ids_listados(cliente, headers):
    r = cliente.get(f"{API}/chamados/", headers=headers, params={"incluir_arquivados": True, "incluir_cancelados": True})
    assert r.status_code == 200
    return {c["id"] for c in r.json()}


class TestConfiguracao:
    """As rotas com a configuração de cada jeito. Sempre fecha; nunca derruba o resto."""

    @pytest.mark.parametrize("valor", [None, "", "abc", "1,x"])
    def test_sem_lista_valida_o_tecnico_da_ti_fica_so_com_o_vinculo(self, cliente, como, monkeypatch, valor):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", valor)
        tecnico = como("tecnico_ti")
        assert _ids_listados(cliente, tecnico) == set()
        assert cliente.get(f"{API}/chamados/{CHAMADOS['ti_sem_responsavel']}", headers=tecnico).status_code == 404

    def test_sem_lista_valida_o_resto_continua(self, cliente, como, monkeypatch, cenario_de_leitura):
        """Admin, Qualidade, conta autenticada e abertura de chamado não dependem da TI configurada."""
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", None)
        assert _ids_listados(cliente, como("admin")) == set(CHAMADOS.values())
        assert _ids_listados(cliente, como("tecnico_qualidade")) == {
            CHAMADOS[n] for n in ("q_atribuido", "q_reatribuido", "ti_com_tecnico_da_q")
        }
        assert cliente.get(f"{API}/auth/me", headers=como("solicitante")).status_code == 200
        r = cliente.post(
            f"{API}/chamados/",
            headers=como("solicitante"),
            json={
                "solicitante_id": cenario_de_leitura["solicitante"],
                "categoria_id": 1,
                "titulo": "Mouse com defeito",
                "descricao": "O mouse parou de funcionar hoje",
                "prioridade": "Baixa",
            },
        )
        assert r.status_code == 201, r.text

    def test_setor_inexistente_na_lista_nao_amplia_nada(self, cliente, como, monkeypatch):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", "1,999")
        assert _ids_listados(cliente, como("tecnico_ti")) == {CHAMADOS[n] for n in DA_TI}
        assert _ids_listados(cliente, como("tecnico_outro_setor")) == set()

    def test_qualidade_na_lista_nao_vira_ti(self, cliente, como, monkeypatch, cenario_de_leitura):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", f"1,{cenario_de_leitura['setor_qualidade_id']}")
        assert _ids_listados(cliente, como("tecnico_qualidade")) == {
            CHAMADOS[n] for n in ("q_atribuido", "q_reatribuido", "ti_com_tecnico_da_q")
        }

    def test_sem_setor_qualidade_o_tecnico_dela_nao_vira_ti(self, cliente, como, monkeypatch):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)
        assert _ids_listados(cliente, como("tecnico_qualidade")) == {CHAMADOS["ti_com_tecnico_da_q"]}

    def test_outro_setor_declarado_vira_ti(self, cliente, como, monkeypatch, cenario_de_leitura):
        """A lista é o que manda: incluir o Comercial dá ao técnico de lá o alcance da TI — só a TI (API-13)."""
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", "1,4")
        assert _ids_listados(cliente, como("tecnico_outro_setor")) == {CHAMADOS[n] for n in DA_TI}


class TestDiagnostico:
    CAMINHO = f"{API}/diagnostico/"

    def test_confere_a_lista_contra_o_cadastro(self, cliente, como, monkeypatch, cenario_de_leitura):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", f"1,999,{cenario_de_leitura['setor_inativo_id']},2")
        equipes = cliente.get(self.CAMINHO, headers=como("admin")).json()["equipes"]
        assert equipes["setores_ti_ids"] == {
            "estado": "valida",
            "configurados": [1, 2, 3, 999],
            "validos_como_ti": [1, 3, 999],
            "inexistentes": [999],
            "inativos": [3],
        }
        # Técnicos ativos sem alcance: o sem setor e o do Comercial.
        assert equipes["tecnicos_ativos_sem_alcance"] == 2
        assert len(equipes["alertas"]) == 4

    def test_sem_configuracao_alerta(self, cliente, como, monkeypatch):
        monkeypatch.setattr(main.settings, "SETORES_TI_IDS", None)
        equipes = cliente.get(self.CAMINHO, headers=como("admin")).json()["equipes"]
        assert equipes["setores_ti_ids"]["estado"] == "ausente"
        assert any("ausente" in a for a in equipes["alertas"])

    def test_tecnico_nao_ve(self, cliente, como):
        assert cliente.get(self.CAMINHO, headers=como("tecnico_ti")).status_code == 403
