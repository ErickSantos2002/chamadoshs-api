"""
Quem pode ler um chamado (API-5, correção do O-1).

Até aqui a leitura só exigia token: qualquer conta ativa lia o detalhe, a
listagem, o histórico e os comentários públicos de qualquer chamado, e o
escopo "os meus chamados" era o filtro que o frontend escolhia mandar. A
regra agora mora aqui, em duas formas que precisam dizer a mesma coisa:

- `pode_ler_chamado`, para um chamado já carregado (detalhe, histórico,
  comentários);
- `escopo_de_leitura`, para a listagem: a mesma regra como filtro SQL, para
  que a paginação conte só o que a pessoa pode ver, em vez de buscar tudo e
  filtrar em Python.

Os testes comparam as duas formas chamado a chamado.

A regra (decisões D1–D5, aprovadas em 29/10/2026):

1. Administrador lê todos.
2. Quem abriu o chamado (solicitante) ou o atende hoje (responsável atual)
   lê o chamado — qualquer perfil. Só o responsável ATUAL: quem deixou de
   atender perde a leitura que vinha só da atribuição (D4). Ser do mesmo
   setor do solicitante não conta (D5).
3. Técnico da Qualidade — perfil Técnico no setor de `SETOR_QUALIDADE_ID` —
   lê os chamados da Qualidade (D2), e da TI só os do item 2.
4. Técnico da TI — perfil Técnico em qualquer outro setor — lê os dois
   setores de destino (D1).
5. Técnico sem setor não tem leitura por perfil, só a do item 2: sem setor
   não dá para dizer de qual equipe ele é, e o padrão aqui é fechar.

Só leitura. As escritas seguem com as regras de sempre (`require_staff`, o
atendimento pelo responsável, a avaliação pelo solicitante): ler um chamado
da Qualidade não dá ao técnico da TI o atendimento dela.

O setor de destino é comparado com os valores do CHECK `chk_setor_destino`
("TI", "QUALIDADE"). Valor fora deles não entra em nenhum alcance de perfil:
só administrador e o vínculo direto o leem.
"""

from typing import FrozenSet

from sqlalchemy import or_
from sqlalchemy.orm import Query

from app.api.deps import is_admin, is_staff
from app.core.config import settings
from app.models.chamado import Chamado
from app.models.usuario import Usuario

SETOR_DESTINO_TI = "TI"
SETOR_DESTINO_QUALIDADE = "QUALIDADE"

_NENHUM: FrozenSet[str] = frozenset()
_SO_QUALIDADE = frozenset({SETOR_DESTINO_QUALIDADE})
_OS_DOIS = frozenset({SETOR_DESTINO_TI, SETOR_DESTINO_QUALIDADE})


def setores_lidos_pelo_perfil(usuario: Usuario) -> FrozenSet[str]:
    """
    Os setores de destino que o perfil do técnico lê inteiros (itens 3 a 5).

    Fora do técnico, vazio: o administrador lê tudo por outro caminho, e o
    usuário comum não lê nada só pelo perfil. `settings` é lido a cada
    chamada, como em `qualidade_service`. Sem `SETOR_QUALIDADE_ID`, ninguém é
    da Qualidade, e todo técnico com setor é da TI — o comportamento de hoje.
    """
    if is_admin(usuario) or not is_staff(usuario):
        return _NENHUM
    if usuario.setor_id is None:
        return _NENHUM
    setor_qualidade = settings.SETOR_QUALIDADE_ID
    if setor_qualidade is not None and usuario.setor_id == setor_qualidade:
        return _SO_QUALIDADE
    return _OS_DOIS


def pode_ler_chamado(usuario: Usuario, chamado: Chamado) -> bool:
    """Se `usuario` pode ler `chamado`. Ver a regra no topo do módulo."""
    if is_admin(usuario):
        return True
    if chamado.solicitante_id == usuario.id or chamado.tecnico_responsavel_id == usuario.id:
        return True
    return chamado.setor_destino in setores_lidos_pelo_perfil(usuario)


def escopo_de_leitura(query: Query, usuario: Usuario) -> Query:
    """
    `query` sobre `Chamado` restrita ao que `usuario` pode ler.

    Aplicar ANTES dos filtros do cliente, do offset e do limit: os filtros só
    estreitam o que já é permitido, e a página é cortada do conjunto
    permitido.
    """
    if is_admin(usuario):
        return query
    condicoes = [
        Chamado.solicitante_id == usuario.id,
        Chamado.tecnico_responsavel_id == usuario.id,
    ]
    setores = setores_lidos_pelo_perfil(usuario)
    if setores:
        condicoes.append(Chamado.setor_destino.in_(sorted(setores)))
    return query.filter(or_(*condicoes))
