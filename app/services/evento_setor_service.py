"""
Gravação da trilha de auditoria do cadastro de setores.

Único lugar do código que escreve em `eventos_de_setor`, pelo mesmo motivo do
irmão `evento_conta_service`: `acao` não tem CHECK no banco, então dois
handlers escrevendo "desativacao" e "desativado" fragmentariam a trilha em
silêncio — falha que não aparece na suíte, e sim na auditoria.

**A gravação não faz commit.** As funções só acrescentam o evento à sessão;
quem comita é o handler, junto com a mudança que o originou. As duas coisas
vivem na mesma transação: não existe setor desativado sem evento, nem evento de
algo que acabou não sendo gravado.

**O nome do setor é copiado para dentro do evento, não referenciado.** É a
diferença de desenho em relação a `eventos_de_conta`, e a razão de as duas
tabelas serem separadas: `eventos_de_setor.setor_id` não tem FK, porque setor
vai virar apagável de verdade. Sem o nome congelado aqui, a trilha de um setor
excluído viraria uma lista de ids órfãos.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.evento_setor import EventoDeSetor
from app.models.setor import Setor
from app.models.usuario import Usuario

# Vocabulário de `acao`. Mesmo formato do de contas: substantivo, sem acento.
ACAO_CRIACAO = "criacao"
ACAO_DESATIVACAO = "desativacao"
ACAO_REATIVACAO = "reativacao"
ACAO_ALTERACAO_DE_NOME = "alteracao_de_nome"
ACAO_ALTERACAO_DE_DESCRICAO = "alteracao_de_descricao"

# Campos acompanhados: exatamente os que o `SetorUpdate` aceita. A regra é "todo
# campo que a edição pode mudar gera evento" — uma lista do que parece
# importante obriga a explicar depois por que uma alteração feita pela tela não
# aparece em lugar nenhum.
CAMPOS_ACOMPANHADOS = ("nome", "descricao", "ativo")

# Usado quando o campo estava (ou ficou) vazio — `descricao` é anulável.
SEM_VALOR = "(nenhum)"

_ACAO_POR_CAMPO = {
    "nome": ACAO_ALTERACAO_DE_NOME,
    "descricao": ACAO_ALTERACAO_DE_DESCRICAO,
}


def instantaneo(setor: Setor) -> dict:
    """
    Cópia dos campos acompanhados, para comparar depois da edição.

    Precisa ser chamado ANTES de aplicar as mudanças: depois do `setattr` o
    valor antigo já não existe em lugar nenhum.
    """
    return {campo: getattr(setor, campo) for campo in CAMPOS_ACOMPANHADOS}


def _texto(valor) -> str:
    """
    Valor em texto legível por gente.

    Não precisa de resolução de id, ao contrário do irmão de contas: setor não
    tem campo que aponte para outra tabela. Descrição longa é truncada no
    limite da coluna — um evento pela metade vale mais do que uma gravação que
    estoura e derruba a edição inteira.
    """
    if valor is None:
        return SEM_VALOR
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)[:255]


def _novo_evento(
    *,
    setor: Setor,
    ator: Usuario,
    acao: str,
    origem: Optional[str],
    valor_anterior: Optional[str] = None,
    valor_novo: Optional[str] = None,
) -> EventoDeSetor:
    return EventoDeSetor(
        setor_id=setor.id,
        # Congelado aqui, e não resolvido na leitura: é o que mantém a trilha
        # legível depois de o setor ser renomeado ou apagado.
        setor_nome=setor.nome,
        ator_id=ator.id,
        acao=acao,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
        origem=origem,
    )


def registrar_criacao(
    db: Session, *, setor: Setor, ator: Usuario, origem: Optional[str] = None
) -> EventoDeSetor:
    """
    Evento de setor criado. Exige `setor.id`, então roda depois do `flush`.

    `valor_novo` guarda o nome com que o setor nasceu: é o começo da corrente
    que as renomeações continuam. Sem ele, a primeira renomeação apareceria
    vindo do nada.
    """
    evento = _novo_evento(
        setor=setor,
        ator=ator,
        acao=ACAO_CRIACAO,
        origem=origem,
        valor_novo=setor.nome,
    )
    db.add(evento)
    return evento


def registrar_alteracoes(
    db: Session,
    *,
    setor: Setor,
    antes: dict,
    ator: Usuario,
    origem: Optional[str] = None,
) -> list:
    """
    Compara o `instantaneo` de antes com o estado atual e grava uma linha por
    campo alterado. Campo reenviado com o mesmo valor não gera evento — a
    trilha registra mudança, não requisição.

    O `setor_nome` do evento sai do estado ATUAL, inclusive quando é o próprio
    nome que mudou. Numa renomeação, portanto, o evento fica sob o nome novo,
    com o de/para nos valores: é assim que a busca por um setor pelo nome atual
    encontra também o momento em que ele passou a se chamar assim.
    """
    eventos = []

    for campo in CAMPOS_ACOMPANHADOS:
        anterior = antes.get(campo)
        atual = getattr(setor, campo)
        if anterior == atual:
            continue

        if campo == "ativo":
            acao = ACAO_REATIVACAO if atual else ACAO_DESATIVACAO
        else:
            acao = _ACAO_POR_CAMPO[campo]

        eventos.append(
            _novo_evento(
                setor=setor,
                ator=ator,
                acao=acao,
                origem=origem,
                valor_anterior=_texto(anterior),
                valor_novo=_texto(atual),
            )
        )

    for evento in eventos:
        db.add(evento)

    return eventos
