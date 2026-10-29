"""
A política de leitura de chamado (API-5, correção do O-1), no serviço.

Aqui só o predicado e o escopo SQL, sem HTTP: a matriz de quem lê o quê, e a
prova de que as duas formas da regra dizem a mesma coisa para cada par
usuário × chamado do cenário. As rotas estão em `test_leitura_por_chamado.py`.

O cenário é `cenario_de_leitura` (ver `leitura_cenario.py`), o mesmo das rotas.
"""

import pytest

from app.models import Chamado, Role, Usuario
from app.services.leitura_service import (
    escopo_de_leitura,
    pode_ler_chamado,
    setores_lidos_pelo_perfil,
)
from leitura_cenario import CHAMADOS, LEITURA_ESPERADA, cenario_de_leitura  # noqa: F401


def _usuario(sessao, usuario_id) -> Usuario:
    return sessao.get(Usuario, usuario_id)


def _todos_os_chamados(sessao):
    return sessao.query(Chamado).order_by(Chamado.id).all()


@pytest.mark.parametrize("quem", sorted(LEITURA_ESPERADA))
def test_matriz_do_predicado(cenario_de_leitura, sessao, quem):
    usuario = _usuario(sessao, cenario_de_leitura[quem])
    lidos = {c.id for c in _todos_os_chamados(sessao) if pode_ler_chamado(usuario, c)}
    assert lidos == {CHAMADOS[n] for n in LEITURA_ESPERADA[quem]}


@pytest.mark.parametrize("quem", sorted(LEITURA_ESPERADA))
def test_escopo_sql_e_predicado_dizem_o_mesmo(cenario_de_leitura, sessao, quem):
    """Chamado a chamado, o filtro SQL devolve exatamente o que o predicado aceita."""
    usuario = _usuario(sessao, cenario_de_leitura[quem])
    pelo_sql = {c.id for c in escopo_de_leitura(sessao.query(Chamado), usuario).all()}
    pelo_predicado = {c.id for c in _todos_os_chamados(sessao) if pode_ler_chamado(usuario, c)}
    assert pelo_sql == pelo_predicado


class TestCasosDeBorda:
    def test_sem_setor_qualidade_configurado_tecnico_com_setor_le_os_dois(
        self, cenario_de_leitura, sessao, monkeypatch
    ):
        """
        Produção hoje: sem `SETOR_QUALIDADE_ID`, ninguém é da Qualidade, e o
        técnico com setor continua lendo tudo, como sempre leu.
        """
        import main

        monkeypatch.setattr(main.settings, "SETOR_QUALIDADE_ID", None)
        tecnico_q = _usuario(sessao, cenario_de_leitura["tecnico_qualidade"])
        assert setores_lidos_pelo_perfil(tecnico_q) == {"TI", "QUALIDADE"}

    def test_tecnico_sem_setor_nao_le_por_perfil(self, cenario_de_leitura, sessao):
        tecnico = _usuario(sessao, cenario_de_leitura["tecnico_sem_setor"])
        assert setores_lidos_pelo_perfil(tecnico) == frozenset()

    def test_perfil_desconhecido_fica_so_com_o_vinculo(self, cenario_de_leitura, sessao):
        """
        Um nome de perfil fora dos três não vira equipe por padrão. A role é
        montada só em memória: o banco não ganha perfil nenhum.
        """
        visitante = Usuario(id=999, nome="visitante", role_id=99, setor_id=1, ativo=True)
        visitante.role = Role(id=99, nome="Visitante")
        chamados = _todos_os_chamados(sessao)
        assert setores_lidos_pelo_perfil(visitante) == frozenset()
        assert not any(pode_ler_chamado(visitante, c) for c in chamados)

    def test_sem_role_carregada_nao_le(self, cenario_de_leitura, sessao):
        sem_role = Usuario(id=998, nome="sem.role", role_id=0, setor_id=1, ativo=True)
        sem_role.role = None
        assert not any(pode_ler_chamado(sem_role, c) for c in _todos_os_chamados(sessao))

    def test_setor_de_destino_desconhecido_so_admin_e_vinculo(self, cenario_de_leitura, sessao):
        """Valor fora do CHECK não entra em alcance de perfil nenhum."""
        estranho = Chamado(id=1, setor_destino="OUTRO", solicitante_id=cenario_de_leitura["solicitante"])
        tecnico_ti = _usuario(sessao, cenario_de_leitura["tecnico_ti"])
        admin = _usuario(sessao, cenario_de_leitura["admin"])
        solicitante = _usuario(sessao, cenario_de_leitura["solicitante"])
        assert not pode_ler_chamado(tecnico_ti, estranho)
        assert pode_ler_chamado(admin, estranho)
        assert pode_ler_chamado(solicitante, estranho)
