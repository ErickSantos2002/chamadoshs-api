"""
`versao` na resposta do chamado (API-4a): o contrato, em SQLite.

O SQLite não tem o trigger que conta as escritas, então aqui a versão é
sempre 1 — e é só isso que se afirma. Que ela SOBE, e por quais rotas, está
provado em PostgreSQL real em `test_versao_api_postgres.py`.

O que estes testes travam é que o campo novo não mudou mais nada:

- toda resposta de chamado traz `versao`, um inteiro;
- os campos de antes continuam todos lá, com os mesmos nomes;
- `versao` não é campo de escrita: o PUT a ignora como qualquer campo
  desconhecido, e o atendimento a recusa como campo a mais (422).

A pré-condição `versao_esperada` (API-4b) está em `test_precondicao_de_versao.py`.
"""

import pytest

from app.models import Chamado
from app.schemas.chamado import ChamadoResponse

# As chaves de ChamadoResponse antes da API-4a, mais `versao`.
CHAVES = {
    "id", "protocolo", "solicitante_id", "titulo", "descricao", "categoria_id",
    "prioridade", "status", "setor_destino", "urgencia", "tecnico_responsavel_id",
    "solucao", "tempo_resolucao_minutos", "observacoes", "avaliacao", "cancelado",
    "arquivado", "data_abertura", "data_atualizacao", "data_resolucao", "created_at",
    "updated_at", "sla", "versao",
}


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _tecnico_da_qualidade(autenticar, d):
    """Desde a API-13 só o Técnico da Qualidade atende; até a API-12 era a ana, de perfil comum."""
    return autenticar(d["tecnico_da_qualidade_id"], "bruno.qualidade", "Tecnico")


def _confere(resposta, status=200):
    assert resposta.status_code == status, resposta.text
    corpo = resposta.json()
    assert set(corpo) == CHAVES
    assert corpo["versao"] == 1 and isinstance(corpo["versao"], int)
    return corpo


def test_o_schema_de_resposta_exige_versao_inteira():
    campo = ChamadoResponse.model_fields["versao"]
    assert campo.is_required()
    assert campo.annotation is int


class TestTodaRespostaDeChamadoTrazVersao:
    def test_criacao(self, cliente, dados, autenticar):
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
        _confere(resposta, 201)

    def test_detalhe(self, cliente, dados, autenticar):
        _confere(cliente.get(f"/api/v1/chamados/{dados['chamado_id']}", headers=_admin(autenticar, dados)))

    def test_listagem(self, cliente, dados, autenticar):
        resposta = cliente.get("/api/v1/chamados/", headers=_admin(autenticar, dados))
        assert resposta.status_code == 200
        assert resposta.json() and all(set(c) == CHAVES and c["versao"] == 1 for c in resposta.json())

    def test_put(self, cliente, dados, autenticar):
        _confere(
            cliente.put(
                f"/api/v1/chamados/{dados['chamado_id']}",
                json={"status": "Em Andamento"},
                headers=_admin(autenticar, dados),
            )
        )

    def test_atendimento(self, cliente, chamado_qualidade_do_tecnico, autenticar):
        d = chamado_qualidade_do_tecnico
        _confere(
            cliente.patch(
                f"/api/v1/chamados/{d['chamado_qualidade_id']}/atendimento",
                json={"status": "Em Andamento", "versao_esperada": 1},
                headers=_tecnico_da_qualidade(autenticar, d),
            )
        )

    @pytest.mark.parametrize("rota", ["cancelar", "arquivar"])
    def test_marcas(self, cliente, dados, autenticar, rota):
        _confere(cliente.patch(f"/api/v1/chamados/{dados['chamado_id']}/{rota}", headers=_admin(autenticar, dados)))

    def test_desarquivar(self, cliente, dados, autenticar):
        cliente.patch(f"/api/v1/chamados/{dados['chamado_id']}/arquivar", headers=_admin(autenticar, dados))
        _confere(cliente.patch(f"/api/v1/chamados/{dados['chamado_id']}/desarquivar", headers=_admin(autenticar, dados)))

    def test_avaliar(self, cliente, dados, sessao, autenticar):
        chamado = sessao.get(Chamado, dados["chamado_id"])
        chamado.status = "Resolvido"
        sessao.commit()
        _confere(
            cliente.patch(
                f"/api/v1/chamados/{dados['chamado_id']}/avaliar",
                json={"avaliacao": 5},
                headers=autenticar(dados["comum_id"], "usuario.teste", "Usuario"),
            )
        )


class TestOsCorposDeEscritaNaoMudaram:
    def test_put_sem_versao_continua_valendo(self, cliente, dados, autenticar):
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"prioridade": "Alta"},
            headers=_admin(autenticar, dados),
        )
        assert resposta.status_code == 200
        assert resposta.json()["prioridade"] == "Alta"

    def test_put_ignora_versao_no_corpo_como_qualquer_campo_desconhecido(self, cliente, dados, sessao, autenticar):
        resposta = cliente.put(
            f"/api/v1/chamados/{dados['chamado_id']}",
            json={"status": "Em Andamento", "versao": 99},
            headers=_admin(autenticar, dados),
        )
        assert resposta.status_code == 200
        assert resposta.json()["versao"] == 1
        sessao.expire_all()
        assert sessao.get(Chamado, dados["chamado_id"]).versao == 1

    def test_atendimento_recusa_versao_como_campo_a_mais(self, cliente, chamado_qualidade_do_tecnico, autenticar):
        """`extra="forbid"` no ChamadoAtendimento: o campo de escrita é `versao_esperada`."""
        d = chamado_qualidade_do_tecnico
        resposta = cliente.patch(
            f"/api/v1/chamados/{d['chamado_qualidade_id']}/atendimento",
            json={"status": "Em Andamento", "versao_esperada": 1, "versao": 1},
            headers=_tecnico_da_qualidade(autenticar, d),
        )
        assert resposta.status_code == 422
        assert resposta.json()["detail"][0]["loc"] == ["body", "versao"]
