"""
Trava de paginação: nenhuma rota pode entregar `skip`/`limit` crus ao banco.

Esta é a generalização de um defeito que apareceu três vezes seguidas, sempre
do mesmo jeito, e que a suíte não tinha como acusar sozinha.

O QUE ACONTECE SEM ELA
----------------------

`skip` e `limit` chegam ao SQLAlchemy como `OFFSET` e `LIMIT`. No PostgreSQL,
os dois recusam valor negativo:

    ERROR: LIMIT must not be negative
    ERROR: OFFSET must not be negative

o que vira **500 a partir de query string** — resposta errada por definição,
porque a entrada é do cliente. No SQLite, que é o banco desta suíte, `LIMIT -1`
significa **sem limite**: a mesma requisição devolve 200 com a tabela inteira.
Então o teste de comportamento não só deixa passar como *confirma* o caminho
errado, e nenhuma asserção sobre a resposta jamais acusaria isso.

Foi assim que aconteceu: o `GET /eventos` ganhou `ge` numa revisão, o
`GET /usuarios/{id}/eventos` ficou para trás e só foi pego no dia seguinte, e
outras seis rotas de listagem — anteriores a toda essa história — nunca tiveram
validação nenhuma.

POR QUE UMA TRAVA E NÃO SÓ A CORREÇÃO
-------------------------------------

Corrigir rota por rota resolve o presente. O defeito, porém, não vem de
desatenção pontual: `skip: int = 0` é o jeito natural de escrever paginação em
FastAPI, está no tutorial oficial, e não parece errado em lugar nenhum. A
próxima rota paginada vai nascer assim de novo.

A trava percorre as rotas de fato registradas na aplicação, então uma rota nova
já entra coberta, sem ninguém precisar lembrar de acrescentá-la aqui.

O QUE ELA NÃO EXIGE
-------------------

Teto (`le`). Ele protege de outra coisa — pedido absurdo varrendo a tabela — e
impor um teto retroativo mudaria o contrato de rotas que já estão em uso: um
frontend que hoje pede `limit=1000` passaria a receber 422. As rotas onde o teto
existe (`/eventos`, `/chamados`) o ganharam por decisão específica. Se o teto
virar regra geral, é mudança de contrato e merece uma conversa, não um teste
novo em silêncio.
"""

import pytest
from fastapi.routing import APIRoute

import main

# Nome do parâmetro -> mínimo que ele precisa declarar. `skip` vira OFFSET e
# pode ser zero; `limit` vira LIMIT e zero devolveria nada, o que é pedido
# inútil e não uma paginação.
MINIMO_EXIGIDO = {"skip": 0, "limit": 1}


def _parametros_de_paginacao():
    """
    (rota, nome do parâmetro, campo do Pydantic) para cada `skip`/`limit` que a
    aplicação expõe de fato.

    Sai das rotas registradas, e não de uma lista escrita à mão, para que rota
    nova entre coberta sozinha.
    """
    encontrados = []
    for rota in main.app.routes:
        if not isinstance(rota, APIRoute):
            continue
        for parametro in rota.dependant.query_params:
            if parametro.name in MINIMO_EXIGIDO:
                encontrados.append(
                    pytest.param(
                        rota, parametro, id=f"{rota.path}::{parametro.name}"
                    )
                )
    return encontrados


PARAMETROS = _parametros_de_paginacao()


def _minimo_declarado(field_info):
    """
    O `ge` de um parâmetro, onde quer que o Pydantic o guarde.

    No Pydantic v2 as restrições de `Query(0, ge=0)` não viram atributo do
    `FieldInfo`: ficam em `metadata`, como objetos de `annotated_types`. Ler só
    `field_info.ge` devolve `None` mesmo para parâmetro corretamente declarado
    — foi o que a primeira versão desta trava fez, acusando rota que estava
    certa. A leitura tenta os dois lugares para não depender dessa escolha
    interna continuar a mesma.
    """
    direto = getattr(field_info, "ge", None)
    if direto is not None:
        return direto

    for restricao in getattr(field_info, "metadata", []):
        valor = getattr(restricao, "ge", None)
        if valor is not None:
            return valor

    return None


def test_a_varredura_encontrou_rotas_paginadas():
    """
    Guarda da própria trava. Se a introspecção deixar de casar — FastAPI muda a
    estrutura interna, o atributo é renomeado — a lista viria vazia e todos os
    testes parametrizados sumiriam sem falhar: uma trava que silenciosamente
    parou de travar.
    """
    assert len(PARAMETROS) >= 10, (
        f"a varredura encontrou só {len(PARAMETROS)} parâmetros de paginação; "
        "a introspecção provavelmente quebrou e esta trava parou de verificar"
    )


@pytest.mark.parametrize("rota,parametro", [(p.values[0], p.values[1]) for p in PARAMETROS],
                         ids=[p.id for p in PARAMETROS])
def test_parametro_de_paginacao_tem_minimo(rota, parametro):
    """
    Um teste por parâmetro, para a falha dizer qual rota precisa de conserto.
    """
    minimo = MINIMO_EXIGIDO[parametro.name]
    declarado = _minimo_declarado(parametro.field_info)

    assert declarado is not None, (
        f"{rota.path} expõe `{parametro.name}` sem mínimo declarado. Em "
        f"PostgreSQL, valor negativo aqui é erro de SQL e vira 500 a partir de "
        f"query string; no SQLite desta suíte o mesmo pedido devolve a tabela "
        f"inteira e nada falha. Use "
        f"`{parametro.name}: int = Query({minimo if minimo else 0}, ge={minimo})`."
    )
    assert declarado >= minimo, (
        f"{rota.path} declara `{parametro.name}` com ge={declarado}, e o mínimo "
        f"seguro é {minimo}."
    )


class TestOsCasosQueMotivaramATrava:
    """
    O comportamento externo do que a trava garante estruturalmente.

    Estes exercitam as respostas; a trava acima é que impede uma rota nova de
    escapar sem ser exercitada por ninguém.
    """

    def _admin(self, autenticar, dados):
        return autenticar(dados["admin_id"], "admin.teste", "Administrador")

    @pytest.mark.parametrize(
        "caminho",
        [
            "/api/v1/usuarios/",
            "/api/v1/setores/",
            "/api/v1/categorias/",
            "/api/v1/chamados/",
            "/api/v1/eventos/",
        ],
    )
    def test_limite_negativo_e_recusado(self, cliente, dados, autenticar, caminho):
        resposta = cliente.get(f"{caminho}?limit=-1", headers=self._admin(autenticar, dados))

        assert resposta.status_code == 422

    @pytest.mark.parametrize(
        "caminho",
        ["/api/v1/usuarios/", "/api/v1/setores/", "/api/v1/chamados/", "/api/v1/eventos/"],
    )
    def test_offset_negativo_e_recusado(self, cliente, dados, autenticar, caminho):
        resposta = cliente.get(f"{caminho}?skip=-1", headers=self._admin(autenticar, dados))

        assert resposta.status_code == 422

    @pytest.mark.parametrize(
        "caminho",
        ["/api/v1/usuarios/", "/api/v1/setores/", "/api/v1/categorias/", "/api/v1/eventos/"],
    )
    def test_paginacao_valida_continua_passando(self, cliente, dados, autenticar, caminho):
        """
        O par obrigatório: uma validação que recusasse tudo faria os testes de
        recusa passarem e quebraria todas as listagens do sistema.
        """
        resposta = cliente.get(
            f"{caminho}?skip=0&limit=10", headers=self._admin(autenticar, dados)
        )

        assert resposta.status_code == 200
