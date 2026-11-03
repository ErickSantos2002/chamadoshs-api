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
4. Técnico da TI — perfil Técnico num setor de `SETORES_TI_IDS` — lê os dois
   setores de destino (D1). (API-6, D10: até a API-5 era técnico de qualquer
   setor que não a Qualidade.)
5. Técnico de outro setor, ou sem setor, não tem leitura por perfil, só a do
   item 2 (H1): sem setor da TI ou da Qualidade não dá para dizer de qual
   equipe ele é, e o padrão aqui é fechar. Sem `SETORES_TI_IDS`, é o caso de
   todo técnico fora da Qualidade.

O alcance do item 3 e 4 é também o que a equipe pode ALTERAR (API-6, D8 —
ver `pode_alterar_como_equipe`). O vínculo do item 2 dá leitura, não poder de
equipe: ser solicitante ou responsável de um chamado da TI não deixa o
técnico da Qualidade mudá-lo pelas rotas da equipe. As rotas que não são da
equipe seguem com as regras de sempre (o atendimento pelo responsável, a
avaliação e o cancelamento pelo solicitante), depois da leitura: ler um
chamado da Qualidade não dá ao técnico da TI o atendimento dela.

O setor de destino é comparado com os valores do CHECK `chk_setor_destino`
("TI", "QUALIDADE"). Valor fora deles não entra em nenhum alcance de perfil:
só administrador e o vínculo direto o leem.
"""

from typing import FrozenSet

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

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
    da Qualidade; sem `SETORES_TI_IDS`, ninguém é da TI. Nenhum dos dois cai
    no outro: setor que não está em nenhuma das listas não tem alcance.
    """
    if is_admin(usuario) or not is_staff(usuario):
        return _NENHUM
    if usuario.setor_id is None:
        return _NENHUM
    setor_qualidade = settings.SETOR_QUALIDADE_ID
    if setor_qualidade is not None and usuario.setor_id == setor_qualidade:
        return _SO_QUALIDADE
    # `setores_ti_ids` já tira o id da Qualidade: a ordem aqui não decide.
    if usuario.setor_id in settings.setores_ti_ids:
        return _OS_DOIS
    return _NENHUM


def pode_ler_chamado(usuario: Usuario, chamado: Chamado) -> bool:
    """Se `usuario` pode ler `chamado`. Ver a regra no topo do módulo."""
    if is_admin(usuario):
        return True
    if chamado.solicitante_id == usuario.id or chamado.tecnico_responsavel_id == usuario.id:
        return True
    return chamado.setor_destino in setores_lidos_pelo_perfil(usuario)


def pode_alterar_como_equipe(usuario: Usuario, chamado: Chamado) -> bool:
    """
    Se `usuario` pode alterar `chamado` pelas rotas da equipe (D8): o PUT, o
    arquivamento, o desarquivamento e o cancelamento de chamado alheio.

    Administrador altera todos; técnico, os do alcance do perfil — o mesmo de
    `setores_lidos_pelo_perfil`, para que a equipe não altere o que não lê.
    O vínculo não entra: o técnico da Qualidade que abriu um chamado da TI o
    lê, e o cancela como solicitante, mas não o edita como equipe.

    Conta de serviço nunca altera como equipe (API-11, S2), qualquer que seja
    o perfil — nem a técnica da TI, nem a administradora. Ela continua lendo
    o que `pode_ler_chamado` deixa (o painel de parede só lê), e o que não
    passa por aqui fica como era: cancelar o que ela mesma abriu, comentar em
    público, avaliar. Só `False` conta como pessoa, como em
    `integra_equipe_ti`.
    """
    if usuario.conta_de_servico is not False:
        return False
    if is_admin(usuario):
        return True
    return chamado.setor_destino in setores_lidos_pelo_perfil(usuario)


def integra_equipe_ti(usuario: Usuario) -> bool:
    """
    Se `usuario` pode ser responsável por chamado da TI (D9): perfil de
    equipe — administrador ou técnico — num setor de `SETORES_TI_IDS`.

    Pela conta a atribuir, e não por quem atribui: nem o administrador põe um
    chamado da TI com quem não é da equipe. Ser técnico não basta, nem estar
    fora da Qualidade: o técnico sem setor, o de outro setor e o da Qualidade
    ficam de fora, e sem `SETORES_TI_IDS` ninguém é elegível. Conta de serviço
    é recusada antes, com a mensagem de sempre (ver `chamados.py`).

    Conta de serviço nunca integra a equipe (API-10, decisão C1), nem com
    perfil Técnico num setor da TI. Até a API-9 integrava, e por esta função
    ganhava tudo o que dela deriva: `require_equipe_ti` (setores, categorias,
    SLA, tarefas, trilha de setor, lista de responsáveis), o comentário
    interno e o `integra_equipe_ti: true` do `/auth/me` — a homologação FE-5
    criou interno com uma delas (201). Só `False` conta como pessoa: `None`,
    que o ORM deixa antes do flush, não prova que a conta é humana.

    O que vem do perfil de administrador não passa por aqui e não muda
    (`is_admin`, nas rotas). A leitura e a escrita de equipe por alcance de
    perfil (`setores_lidos_pelo_perfil`) também não — ver AUTH.md, API-10.
    """
    if usuario.conta_de_servico is not False:
        return False
    return is_staff(usuario) and usuario.setor_id is not None and usuario.setor_id in settings.setores_ti_ids


def pode_acessar_comentario_interno(usuario: Usuario) -> bool:
    """
    Se `usuario` pode ver e escrever comentário interno (API-8): o
    administrador, pelo perfil, e o técnico que `integra_equipe_ti` diz ser
    da TI.

    Até a API-7 bastava o perfil de equipe (`is_staff`): o técnico da
    Qualidade, o de outro setor e o sem setor viam e criavam interno em todo
    chamado que liam pelo vínculo. A pergunta aqui é só a do perfil; ler o
    chamado é outra, e as duas são exigidas — o técnico da TI não vê o
    interno de um chamado que não lê. Sem `SETORES_TI_IDS` válida, só o
    administrador.
    """
    return is_admin(usuario) or integra_equipe_ti(usuario)


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


CHAMADO_NAO_ENCONTRADO = "Chamado não encontrado"


class ChamadoNaoEncontrado(HTTPException):
    """
    404 do chamado que não existe E do que existe mas a pessoa não pode ler
    (D6): mesmo status, mesmo corpo, para que tentar ids não diga quais
    existem. `HTTPException`, e não exceção de domínio, pelo mesmo motivo de
    `versao_service`: não repetir a tradução em cada rota.
    """

    def __init__(self):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=CHAMADO_NAO_ENCONTRADO)


def buscar_chamado_legivel(db: Session, chamado_id: int, usuario: Usuario) -> Chamado:
    """O chamado, se existir e `usuario` puder lê-lo; senão `ChamadoNaoEncontrado`."""
    chamado = db.query(Chamado).filter(Chamado.id == chamado_id).first()
    if chamado is None or not pode_ler_chamado(usuario, chamado):
        raise ChamadoNaoEncontrado()
    return chamado


FORA_DA_EQUIPE = "Este chamado não é da sua equipe"
CONTA_DE_SERVICO_NAO_ALTERA = "Conta de serviço não altera chamado como equipe"


def buscar_chamado_alteravel(db: Session, chamado_id: int, usuario: Usuario) -> Chamado:
    """
    O chamado, para as rotas da equipe (D8 e D12): 404 se `usuario` não o lê,
    403 se o lê só pelo vínculo.

    O 404 vem antes de tudo o que fala do chamado — versão (409), estado
    ("já está arquivado"), responsável —, para que a recusa de quem não lê
    seja a mesma de um id que não existe. O 403 só chega a quem já lê o
    chamado, e por isso não conta nada que a pessoa não saiba.
    """
    chamado = buscar_chamado_legivel(db, chamado_id, usuario)
    if not pode_alterar_como_equipe(usuario, chamado):
        # A conta de serviço recebe o motivo dela (API-11): "não é da sua
        # equipe" seria falso para a técnica da TI, que lê o chamado pelo
        # alcance da equipe. Só chega aqui quem já lê o chamado.
        motivo = CONTA_DE_SERVICO_NAO_ALTERA if usuario.conta_de_servico is not False else FORA_DA_EQUIPE
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=motivo)
    return chamado
