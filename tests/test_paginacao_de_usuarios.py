"""
Paginação da listagem de usuários (API-17).

`GET /usuarios/` paginava com `OFFSET`/`LIMIT` sem `ORDER BY`. Sem ordem
declarada o banco devolve as linhas na ordem que quiser, e ela pode mudar
entre uma página e a seguinte: um usuário aparece duas vezes, outro não
aparece. O front busca de 100 em 100 (`listarTodos`), então o defeito só se
manifestaria acima de 100 cadastros — e como nome sumindo da tela, longe da
causa.

A ordem passa a ser por `id` crescente, e o `limit` ganha teto de 500, o
mesmo de `/chamados` e `/eventos`; acima dele, 422. O padrão continua 100.

O QUE O SQLITE NÃO ACUSA
------------------------

No SQLite a chave primária inteira é o próprio rowid, e uma varredura sem
`ORDER BY` já sai por `id`. Os testes de ordem passariam aqui com ou sem a
correção. Por isso há dois reforços:

- `TestAConsultaDeclaraAOrdem` olha o SQL emitido: sem `ORDER BY usuarios.id`
  na consulta paginada, falha em qualquer banco.
- `test_paginacao_de_usuarios_postgres.py` roda estas classes em PostgreSQL,
  com linhas atualizadas depois da carga — o `UPDATE` regrava a linha no fim
  da tabela, e a varredura sem ordem deixa de coincidir com o `id`.

O QUE A ORDEM NÃO GARANTE
-------------------------

Páginas coerentes sobre um conjunto que não muda. Usuário criado ou excluído
entre duas requisições ainda desloca as páginas seguintes; o front continua
conferindo ids repetidos.
"""

import random

import pytest
from sqlalchemy import event, text

from app.models import Setor, Usuario
from app.schemas.usuario import UsuarioResponse

API = "/api/v1/usuarios/"
PRIMEIRO = 1000
QUANTOS = 520  # mais que o teto de 500, para o teto cortar de verdade
TETO = 500
PADRAO = 100


def _admin(autenticar, d):
    return autenticar(d["admin_id"], "admin.teste", "Administrador")


def _tecnico(autenticar, d):
    return autenticar(d["tecnico_id"], "tecnico.teste", "Tecnico")


def _comum(autenticar, d):
    return autenticar(d["comum_id"], "usuario.teste", "Usuario")


def _setor(i):
    return 1 if i % 3 else 2


def _role(i):
    return (i % 3) + 1


def _ativo(i):
    return i % 4 != 0


@pytest.fixture
def muitos(dados, sessao):
    """
    520 contas fictícias além das três de `dados`, gravadas fora da ordem dos
    ids e com um lote regravado depois: a ordem física da tabela não coincide
    com a do `id`.
    """
    sessao.add(Setor(id=2, nome="Qualidade", ativo=True))
    sessao.flush()
    ids = list(range(PRIMEIRO, PRIMEIRO + QUANTOS))
    random.Random(17).shuffle(ids)
    sessao.add_all([
        Usuario(
            id=i, nome=f"ficticio.{i}", role_id=_role(i), setor_id=_setor(i), ativo=_ativo(i)
        )
        for i in ids
    ])
    sessao.commit()
    # Regrava um em cada sete, sem mudar o valor: no PostgreSQL a versão nova
    # da linha vai para o fim da tabela.
    sessao.execute(text("UPDATE usuarios SET nome = nome WHERE id % 7 = 0"))
    sessao.commit()
    todos = sorted([dados["admin_id"], dados["tecnico_id"], dados["comum_id"]] + ids)
    return {**dados, "ids": todos}


def _pedir(cliente, headers, **params):
    return cliente.get(API, params=params, headers=headers)


def _ids(cliente, headers, **params):
    resposta = _pedir(cliente, headers, **params)
    assert resposta.status_code == 200, resposta.text
    return [u["id"] for u in resposta.json()]


def _paginas(cliente, headers, tamanho, **filtros):
    """Todas as páginas, como o `listarTodos` do front faz."""
    paginas = []
    for n in range(200):
        pagina = _ids(cliente, headers, skip=n * tamanho, limit=tamanho, **filtros)
        paginas.append(pagina)
        if len(pagina) < tamanho:
            return paginas
    raise AssertionError("a paginação não terminou")


class TestAConsultaDeclaraAOrdem:
    def test_o_sql_da_listagem_ordena_por_id(self, cliente, muitos, sessao, autenticar):
        emitidos = []

        def _anotar(conn, cursor, statement, parameters, context, executemany):
            emitidos.append(" ".join(statement.split()))

        banco = sessao.get_bind()
        event.listen(banco, "before_cursor_execute", _anotar)
        try:
            _ids(cliente, _admin(autenticar, muitos), skip=100, limit=100)
        finally:
            event.remove(banco, "before_cursor_execute", _anotar)

        # A conta do token também é lida com LIMIT (`.first()`), mas por id:
        # a listagem sem filtro é a única consulta a `usuarios` sem WHERE.
        paginadas = [
            s for s in emitidos
            if "FROM usuarios" in s and "LIMIT" in s and "OFFSET" in s and "WHERE" not in s
        ]
        assert len(paginadas) == 1, paginadas
        (consulta,) = paginadas
        assert "ORDER BY usuarios.id" in consulta
        assert " DESC" not in consulta
        assert consulta.index("ORDER BY") < consulta.index("LIMIT")


class TestOrdem:
    def test_crescente_por_id(self, cliente, muitos, autenticar):
        recebidos = _ids(cliente, _admin(autenticar, muitos), limit=TETO)

        assert recebidos == muitos["ids"][:TETO]

    def test_primeira_pagina_tem_os_cem_menores_ids(self, cliente, muitos, autenticar):
        assert _ids(cliente, _admin(autenticar, muitos), skip=0, limit=100) == muitos["ids"][:100]

    def test_segunda_pagina_tem_os_cem_seguintes(self, cliente, muitos, autenticar):
        assert _ids(cliente, _admin(autenticar, muitos), skip=100, limit=100) == muitos["ids"][100:200]

    def test_a_mesma_pagina_pedida_duas_vezes_e_a_mesma(self, cliente, muitos, autenticar):
        h = _admin(autenticar, muitos)

        assert _ids(cliente, h, skip=200, limit=100) == _ids(cliente, h, skip=200, limit=100)


class TestPaginasCompletas:
    def test_mais_de_cem_usuarios_em_varias_paginas(self, cliente, muitos, autenticar):
        paginas = _paginas(cliente, _admin(autenticar, muitos), 100)

        assert [len(p) for p in paginas] == [100, 100, 100, 100, 100, 23]

    def test_sem_sobreposicao(self, cliente, muitos, autenticar):
        juntos = [i for p in _paginas(cliente, _admin(autenticar, muitos), 100) for i in p]

        assert len(juntos) == len(set(juntos))

    def test_sem_lacuna(self, cliente, muitos, autenticar):
        juntos = [i for p in _paginas(cliente, _admin(autenticar, muitos), 100) for i in p]

        assert juntos == muitos["ids"]

    @pytest.mark.parametrize("tamanho", [1, 7, 250, TETO])
    def test_outros_tamanhos_de_pagina(self, cliente, muitos, autenticar, tamanho):
        if tamanho == 1:
            # Uma requisição por usuário seria lenta à toa: bastam as primeiras.
            h = _admin(autenticar, muitos)
            juntos = [_ids(cliente, h, skip=n, limit=1)[0] for n in range(12)]
            assert juntos == muitos["ids"][:12]
            return
        juntos = [i for p in _paginas(cliente, _admin(autenticar, muitos), tamanho) for i in p]

        assert juntos == muitos["ids"]


class TestFiltrosMantemAOrdem:
    def _esperados(self, muitos, condicao):
        # As três contas de `dados` são do setor 1, ativas, uma de cada perfil.
        fixas = {muitos["admin_id"]: 1, muitos["tecnico_id"]: 2, muitos["comum_id"]: 3}
        saida = []
        for i in muitos["ids"]:
            if i in fixas:
                conta = {"setor": 1, "role": fixas[i], "ativo": True}
            else:
                conta = {"setor": _setor(i), "role": _role(i), "ativo": _ativo(i)}
            if condicao(conta):
                saida.append(i)
        return saida

    def _tudo(self, cliente, headers, **filtros):
        return [i for p in _paginas(cliente, headers, 100, **filtros) for i in p]

    def test_por_setor(self, cliente, muitos, autenticar):
        recebidos = self._tudo(cliente, _admin(autenticar, muitos), setor_id=2)

        assert recebidos == self._esperados(muitos, lambda c: c["setor"] == 2)
        assert len(recebidos) > 100

    def test_por_perfil(self, cliente, muitos, autenticar):
        recebidos = self._tudo(cliente, _admin(autenticar, muitos), role_id=3)

        assert recebidos == self._esperados(muitos, lambda c: c["role"] == 3)
        assert len(recebidos) > 100

    def test_por_ativo(self, cliente, muitos, autenticar):
        recebidos = self._tudo(cliente, _admin(autenticar, muitos), ativo=True)

        assert recebidos == self._esperados(muitos, lambda c: c["ativo"])
        assert len(recebidos) > 100

    def test_por_inativo(self, cliente, muitos, autenticar):
        recebidos = self._tudo(cliente, _admin(autenticar, muitos), ativo=False)

        assert recebidos == self._esperados(muitos, lambda c: not c["ativo"])
        assert len(recebidos) > 100

    def test_filtros_combinados(self, cliente, muitos, autenticar):
        recebidos = self._tudo(
            cliente, _admin(autenticar, muitos), setor_id=1, role_id=2, ativo=True
        )

        assert recebidos == self._esperados(
            muitos, lambda c: c["setor"] == 1 and c["role"] == 2 and c["ativo"]
        )
        assert recebidos

    def test_filtro_sem_resultado_devolve_lista_vazia(self, cliente, muitos, autenticar):
        assert self._tudo(cliente, _admin(autenticar, muitos), setor_id=999) == []


class TestLimite:
    def test_ausente_vale_o_padrao_de_cem(self, cliente, muitos, autenticar):
        assert _ids(cliente, _admin(autenticar, muitos)) == muitos["ids"][:PADRAO]

    def test_um_e_aceito(self, cliente, muitos, autenticar):
        assert _ids(cliente, _admin(autenticar, muitos), limit=1) == muitos["ids"][:1]

    def test_o_teto_e_aceito_e_devolve_quinhentos(self, cliente, muitos, autenticar):
        assert len(_ids(cliente, _admin(autenticar, muitos), limit=TETO)) == TETO

    def test_acima_do_teto_e_recusado(self, cliente, muitos, autenticar):
        resposta = _pedir(cliente, _admin(autenticar, muitos), limit=TETO + 1)

        assert resposta.status_code == 422
        (erro,) = resposta.json()["detail"]
        assert erro["loc"] == ["query", "limit"]
        assert erro["type"] == "less_than_equal"

    @pytest.mark.parametrize("limite", [1000, 10**9])
    def test_muito_acima_do_teto_tambem(self, cliente, muitos, autenticar, limite):
        assert _pedir(cliente, _admin(autenticar, muitos), limit=limite).status_code == 422

    def test_zero_e_recusado(self, cliente, muitos, autenticar):
        assert _pedir(cliente, _admin(autenticar, muitos), limit=0).status_code == 422

    def test_negativo_e_recusado(self, cliente, muitos, autenticar):
        assert _pedir(cliente, _admin(autenticar, muitos), limit=-1).status_code == 422

    def test_recusa_nao_depende_dos_filtros(self, cliente, muitos, autenticar):
        resposta = _pedir(cliente, _admin(autenticar, muitos), limit=TETO + 1, ativo=True)

        assert resposta.status_code == 422


class TestSkip:
    def test_negativo_e_recusado(self, cliente, muitos, autenticar):
        assert _pedir(cliente, _admin(autenticar, muitos), skip=-1).status_code == 422

    def test_alem_do_fim_devolve_lista_vazia(self, cliente, muitos, autenticar):
        assert _ids(cliente, _admin(autenticar, muitos), skip=len(muitos["ids"]) + 50) == []

    def test_exatamente_no_fim_devolve_lista_vazia(self, cliente, muitos, autenticar):
        assert _ids(cliente, _admin(autenticar, muitos), skip=len(muitos["ids"])) == []

    def test_ultimo_registro(self, cliente, muitos, autenticar):
        assert _ids(cliente, _admin(autenticar, muitos), skip=len(muitos["ids"]) - 1) == muitos["ids"][-1:]


class TestPermissoesNaoMudam:
    """A listagem é de qualquer conta autenticada, como antes."""

    def test_sem_token_e_401(self, cliente, muitos):
        assert cliente.get(API).status_code == 401

    @pytest.mark.parametrize("quem", [_admin, _tecnico, _comum])
    def test_todo_perfil_autenticado_lista(self, cliente, muitos, autenticar, quem):
        assert _ids(cliente, quem(autenticar, muitos)) == muitos["ids"][:PADRAO]

    @pytest.mark.parametrize("quem", [_admin, _tecnico, _comum])
    def test_o_teto_vale_para_todo_perfil(self, cliente, muitos, autenticar, quem):
        assert _pedir(cliente, quem(autenticar, muitos), limit=TETO + 1).status_code == 422


class TestFormatoDaResposta:
    def test_e_uma_lista_com_os_campos_de_sempre(self, cliente, muitos, autenticar):
        resposta = _pedir(cliente, _admin(autenticar, muitos), limit=3)

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert isinstance(corpo, list) and len(corpo) == 3
        for usuario in corpo:
            assert set(usuario) == set(UsuarioResponse.model_fields)
            assert set(usuario) == {
                "id", "nome", "setor_id", "role_id", "ativo", "conta_de_servico",
                "created_at", "updated_at",
            }

    def test_nao_devolve_o_hash_da_senha(self, cliente, muitos, autenticar):
        for usuario in _pedir(cliente, _admin(autenticar, muitos), limit=5).json():
            assert "senha_hash" not in usuario and "senha" not in usuario

    def test_os_valores_sao_os_do_cadastro(self, cliente, muitos, autenticar):
        (usuario,) = _pedir(cliente, _admin(autenticar, muitos), skip=3, limit=1).json()

        i = muitos["ids"][3]
        assert usuario["id"] == i
        assert usuario["nome"] == f"ficticio.{i}"
        assert usuario["setor_id"] == _setor(i)
        assert usuario["role_id"] == _role(i)
        assert usuario["ativo"] is _ativo(i)
        assert usuario["conta_de_servico"] is False
