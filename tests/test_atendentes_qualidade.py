"""
Quem pode atender chamado da Qualidade, e como a API descobre qual setor é ela.

Elegível é a conta ativa, que não é conta de serviço e pertence ao setor
configurado em `SETOR_QUALIDADE_ID` — com qualquer perfil. Não há política de
perfis nova aqui: um técnico lotado na Qualidade é elegível, um técnico da TI
não é.

A regra mora em `qualidade_service`, e é a mesma função que filtra a lista de
atendentes e que valida o responsável na abertura. Duas cópias da regra — uma
no seletor, outra na gravação — seriam o caminho para o seletor oferecer
alguém que a gravação recusa, ou o contrário.

O setor é identificado por id configurado por ambiente, nunca por nome nem por
id fixo no código: nome muda, e o id da Qualidade em produção não é o mesmo da
homologação. Sem configuração válida, a Qualidade fica fechada (503) — e a API
continua subindo normalmente.
"""

import pytest

import main
from app.core.config import Settings
from app.services import qualidade_service

ROTA = "/api/v1/chamados/atendentes-qualidade"


def _comum(autenticar, dados):
    return autenticar(dados["comum_id"], "usuario.teste", "Usuario")


class TestConfiguracao:
    """`SETOR_QUALIDADE_ID` lido do ambiente, sem nunca impedir a API de subir."""

    @pytest.fixture
    def ler(self, monkeypatch):
        def _ler(valor):
            if valor is None:
                monkeypatch.delenv("SETOR_QUALIDADE_ID", raising=False)
            else:
                monkeypatch.setenv("SETOR_QUALIDADE_ID", valor)
            # _env_file=None: um .env local da máquina não pode decidir o teste.
            return Settings(_env_file=None).SETOR_QUALIDADE_ID

        return _ler

    def test_ausente_e_nao_configurado(self, ler):
        assert ler(None) is None

    @pytest.mark.parametrize("valor", ["", "   "])
    def test_vazio_e_nao_configurado(self, ler, valor):
        """Variável criada vazia no painel é o caso comum de "ainda não ligar"."""
        assert ler(valor) is None

    def test_numero_e_lido(self, ler):
        assert ler("7") == 7
        assert ler(" 7 ") == 7

    @pytest.mark.parametrize("valor", ["abc", "7.5", "0", "-3", "Qualidade"])
    def test_invalido_vira_nao_configurado_sem_derrubar_a_api(self, ler, valor):
        """
        Fail-closed: a Qualidade fecha e a API sobe. Um erro de digitação nesta
        variável não pode tirar do ar a abertura de chamados da TI.
        """
        assert ler(valor) is None


class TestSetorDaQualidade:
    def test_configurado_ativo_e_devolvido(self, qualidade, sessao):
        assert qualidade_service.setor_qualidade(sessao).id == qualidade["setor_qualidade_id"]

    def test_sem_configuracao_fecha(self, qualidade, sessao, monkeypatch):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)

        with pytest.raises(qualidade_service.QualidadeIndisponivel):
            qualidade_service.setor_qualidade(sessao)

    def test_setor_inexistente_fecha(self, qualidade, sessao, monkeypatch):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", 999)

        with pytest.raises(qualidade_service.QualidadeIndisponivel):
            qualidade_service.setor_qualidade(sessao)

    def test_setor_inativo_fecha(self, qualidade, sessao, monkeypatch):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", qualidade["setor_inativo_id"])

        with pytest.raises(qualidade_service.QualidadeIndisponivel):
            qualidade_service.setor_qualidade(sessao)


class TestElegibilidade:
    @pytest.mark.parametrize(
        "chave", ["atendente_id", "tecnico_da_qualidade_id", "admin_da_qualidade_id"]
    )
    def test_elegivel_com_qualquer_perfil(self, qualidade, sessao, chave):
        atendente = qualidade_service.buscar_atendente(sessao, qualidade[chave])

        assert atendente.id == qualidade[chave]

    def test_inexistente(self, qualidade, sessao):
        with pytest.raises(qualidade_service.AtendenteNaoEncontrado):
            qualidade_service.buscar_atendente(sessao, 9999)

    @pytest.mark.parametrize(
        "chave",
        [
            "inativo_id",
            "conta_de_servico_id",
            "sem_setor_id",
            # Técnico da TI: perfil de atendimento, setor errado.
            "tecnico_id",
            "comum_id",
        ],
    )
    def test_inelegivel(self, qualidade, sessao, chave):
        with pytest.raises(qualidade_service.AtendenteInelegivel):
            qualidade_service.buscar_atendente(sessao, qualidade[chave])

    def test_sem_configuracao_fecha_antes_de_olhar_o_atendente(
        self, qualidade, sessao, monkeypatch
    ):
        """Configuração ausente é 503 mesmo para um id que nem existe."""
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)

        with pytest.raises(qualidade_service.QualidadeIndisponivel):
            qualidade_service.buscar_atendente(sessao, 9999)


class TestRotaDeAtendentes:
    def test_lista_so_os_elegiveis_ordenados_por_nome(self, cliente, qualidade, autenticar):
        resposta = cliente.get(ROTA, headers=_comum(autenticar, qualidade))

        assert resposta.status_code == 200
        assert resposta.json() == [
            {"id": qualidade["admin_da_qualidade_id"], "nome": "aaron.qualidade"},
            {"id": qualidade["atendente_id"], "nome": "ana.qualidade"},
            {"id": qualidade["tecnico_da_qualidade_id"], "nome": "bruno.qualidade"},
        ]

    def test_devolve_so_id_e_nome(self, cliente, qualidade, autenticar):
        """Nada de perfil, setor, ativo ou conta_de_servico: o seletor só precisa disto."""
        resposta = cliente.get(ROTA, headers=_comum(autenticar, qualidade))

        assert all(set(item) == {"id", "nome"} for item in resposta.json())

    @pytest.mark.parametrize(
        "perfil,chave",
        [("Usuario", "comum_id"), ("Tecnico", "tecnico_id"), ("Administrador", "admin_id")],
    )
    def test_qualquer_perfil_que_abre_chamado_consulta(
        self, cliente, qualidade, autenticar, perfil, chave
    ):
        resposta = cliente.get(ROTA, headers=autenticar(qualidade[chave], "x", perfil))

        assert resposta.status_code == 200

    def test_sem_token_e_401(self, cliente, qualidade):
        assert cliente.get(ROTA).status_code == 401

    def test_sem_configuracao_e_503(self, cliente, qualidade, autenticar, monkeypatch):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)

        resposta = cliente.get(ROTA, headers=_comum(autenticar, qualidade))

        assert resposta.status_code == 503

    def test_setor_inativo_e_503(self, cliente, qualidade, autenticar, monkeypatch):
        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", qualidade["setor_inativo_id"])

        resposta = cliente.get(ROTA, headers=_comum(autenticar, qualidade))

        assert resposta.status_code == 503

    def test_nao_e_confundida_com_detalhe_de_chamado(self, cliente, qualidade, autenticar):
        """
        Declarada depois de `/{chamado_id}`, "atendentes-qualidade" seria lido
        como id e a resposta seria 422 de inteiro inválido.
        """
        resposta = cliente.get(ROTA, headers=_comum(autenticar, qualidade))

        assert resposta.status_code == 200
        assert isinstance(resposta.json(), list)
