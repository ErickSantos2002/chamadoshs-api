"""
Leitura da trilha de auditoria: junta `eventos_de_conta` e `eventos_de_setor`
num formato só.

As duas tabelas são separadas por uma razão de escrita (o alvo de setor não
pode ter FK, porque setor vira apagável), e essa razão não interessa a quem
lê. A pergunta da auditoria é uma só — "quem fez o quê, com o quê, e quando" —
então a leitura devolve um formato só, com `alvo_tipo` dizendo de qual das duas
a linha veio.

Nenhuma função daqui escreve. As gravações ficam em `evento_conta_service` e
`evento_setor_service`, que continuam sendo os únicos lugares que conhecem o
vocabulário de `acao`.
"""

from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy.orm import Session, aliased

from app.models.evento_conta import EventoDeConta
from app.models.evento_setor import EventoDeSetor
from app.models.usuario import Usuario

ALVO_USUARIO = "usuario"
ALVO_SETOR = "setor"
ALVOS = (ALVO_USUARIO, ALVO_SETOR)


def _intervalo(de: Optional[date], ate: Optional[date]):
    """
    Converte o período em dias para limites de datetime.

    `ate` vira o começo do dia SEGUINTE, com comparação exclusiva. Um
    `created_at <= ate` com `ate` em data pura significaria meia-noite em ponto,
    e o filtro devolveria zero eventos do último dia do período — o mesmo
    filtro que a pessoa acabou de usar para procurar o que aconteceu hoje.
    """
    inicio = datetime.combine(de, time.min) if de else None
    fim = datetime.combine(ate + timedelta(days=1), time.min) if ate else None
    return inicio, fim


def _aplicar_periodo(consulta, coluna, de: Optional[date], ate: Optional[date]):
    inicio, fim = _intervalo(de, ate)
    if inicio is not None:
        consulta = consulta.filter(coluna >= inicio)
    if fim is not None:
        consulta = consulta.filter(coluna < fim)
    return consulta


def _de_conta(evento: EventoDeConta, alvo_nome: Optional[str], ator_nome: Optional[str]) -> dict:
    return {
        "chave": f"{ALVO_USUARIO}:{evento.id}",
        "id": evento.id,
        "alvo_tipo": ALVO_USUARIO,
        "alvo_id": evento.usuario_id,
        "alvo_nome": alvo_nome,
        "ator_id": evento.ator_id,
        "ator_nome": ator_nome,
        "acao": evento.acao,
        "valor_anterior": evento.valor_anterior,
        "valor_novo": evento.valor_novo,
        "origem": evento.origem,
        "created_at": evento.created_at,
    }


def _de_setor(evento: EventoDeSetor, ator_nome: Optional[str]) -> dict:
    return {
        "chave": f"{ALVO_SETOR}:{evento.id}",
        "id": evento.id,
        "alvo_tipo": ALVO_SETOR,
        "alvo_id": evento.setor_id,
        # Vem da própria linha, não de um join: é o nome congelado no momento
        # do evento, que continua legível depois de o setor ser renomeado ou
        # apagado.
        "alvo_nome": evento.setor_nome,
        "ator_id": evento.ator_id,
        "ator_nome": ator_nome,
        "acao": evento.acao,
        "valor_anterior": evento.valor_anterior,
        "valor_novo": evento.valor_novo,
        "origem": evento.origem,
        "created_at": evento.created_at,
    }


def _ordem(item: dict):
    """
    Mais recente primeiro, com o id desempatando.

    O desempate não é enfeite: uma edição que muda perfil e setor grava dois
    eventos no mesmo instante, e sem critério estável eles trocariam de lugar
    entre duas chamadas iguais — a paginação repetiria uma linha e engoliria a
    outra.

    Entre linhas de tabelas DIFERENTES, comparar ids não quer dizer nada: são
    duas sequências independentes, e um evento de setor com id menor não é mais
    antigo que um evento de conta com id maior. O critério continua servindo
    porque o que se pede dele é ser determinístico, não ser significativo — o
    significado já está em `created_at`, que vem primeiro.

    `created_at` pode ser nulo em linha inserida por SQL direto; ela vai para o
    fim em vez de derrubar a comparação.
    """
    return (item["created_at"] is not None, item["created_at"] or datetime.min, item["id"])


def eventos_de_conta(
    db: Session,
    *,
    usuario_id: Optional[int] = None,
    ator_id: Optional[int] = None,
    de: Optional[date] = None,
    ate: Optional[date] = None,
    limite: int = 100,
) -> list:
    """Eventos de cadastro de usuário, do mais recente para o mais antigo."""
    Alvo = aliased(Usuario)
    Ator = aliased(Usuario)

    consulta = (
        db.query(EventoDeConta, Alvo.nome, Ator.nome)
        # outerjoin, e não join: a FK garante que o alvo existe hoje, mas um
        # join interno transformaria qualquer surpresa futura em evento
        # desaparecido da trilha — falha silenciosa no lugar onde ela é pior.
        .outerjoin(Alvo, Alvo.id == EventoDeConta.usuario_id)
        .outerjoin(Ator, Ator.id == EventoDeConta.ator_id)
    )

    if usuario_id is not None:
        consulta = consulta.filter(EventoDeConta.usuario_id == usuario_id)
    if ator_id is not None:
        consulta = consulta.filter(EventoDeConta.ator_id == ator_id)
    consulta = _aplicar_periodo(consulta, EventoDeConta.created_at, de, ate)

    linhas = (
        consulta.order_by(EventoDeConta.created_at.desc(), EventoDeConta.id.desc())
        .limit(limite)
        .all()
    )
    return [_de_conta(evento, alvo_nome, ator_nome) for evento, alvo_nome, ator_nome in linhas]


def eventos_de_setor(
    db: Session,
    *,
    setor_id: Optional[int] = None,
    ator_id: Optional[int] = None,
    de: Optional[date] = None,
    ate: Optional[date] = None,
    limite: int = 100,
) -> list:
    """Eventos de cadastro de setor, do mais recente para o mais antigo."""
    Ator = aliased(Usuario)

    consulta = db.query(EventoDeSetor, Ator.nome).outerjoin(
        Ator, Ator.id == EventoDeSetor.ator_id
    )

    if setor_id is not None:
        consulta = consulta.filter(EventoDeSetor.setor_id == setor_id)
    if ator_id is not None:
        consulta = consulta.filter(EventoDeSetor.ator_id == ator_id)
    consulta = _aplicar_periodo(consulta, EventoDeSetor.created_at, de, ate)

    linhas = (
        consulta.order_by(EventoDeSetor.created_at.desc(), EventoDeSetor.id.desc())
        .limit(limite)
        .all()
    )
    return [_de_setor(evento, ator_nome) for evento, ator_nome in linhas]


def consultar(
    db: Session,
    *,
    alvo: Optional[str] = None,
    ator_id: Optional[int] = None,
    de: Optional[date] = None,
    ate: Optional[date] = None,
    skip: int = 0,
    limit: int = 100,
) -> list:
    """
    Trilha completa, das duas tabelas, ordenada da mais recente para a mais
    antiga.

    A mescla é feita aqui e não no banco. Um UNION exigiria as duas tabelas com
    colunas compatíveis — que é exatamente o que elas não são, e por um motivo
    que vale mais do que a conveniência da consulta.

    Cada tabela entrega `skip + limit` linhas e a mescla corta o pedaço pedido.
    Isso é suficiente e não aproxima: as `skip + limit` primeiras linhas da
    união só podem sair das `skip + limit` primeiras de cada lado, então o
    corte enxerga tudo que poderia entrar nele.
    """
    if alvo is not None and alvo not in ALVOS:
        raise ValueError(f"alvo deve ser um de {ALVOS}")

    # Teto do que cada lado precisa entregar para a mescla ser exata.
    profundidade = skip + limit

    juntos = []
    if alvo in (None, ALVO_USUARIO):
        juntos += eventos_de_conta(db, ator_id=ator_id, de=de, ate=ate, limite=profundidade)
    if alvo in (None, ALVO_SETOR):
        juntos += eventos_de_setor(db, ator_id=ator_id, de=de, ate=ate, limite=profundidade)

    juntos.sort(key=_ordem, reverse=True)
    return juntos[skip : skip + limit]
