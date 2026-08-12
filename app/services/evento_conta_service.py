"""
Gravação da trilha de auditoria do cadastro de usuários.

Único lugar do código que escreve em `eventos_de_conta`. Concentrar aqui não é
organização: o vocabulário de `acao` não tem CHECK no banco — como em
`historico_chamados` — então dois handlers escrevendo "desativacao" e
"desativado" fragmentariam a trilha em silêncio, e ninguém descobre isso pela
suíte, e sim na auditoria.

**A gravação não faz commit.** As funções apenas acrescentam o evento à sessão;
quem comita é o handler, junto com a mudança que originou o evento. Assim as
duas coisas vivem na mesma transação: não existe conta desativada sem evento,
nem evento de algo que acabou não sendo gravado.

**Cobre todos os caminhos que alteram cadastro, não só os novos.** O
`PUT /usuarios/{id}` muda `ativo` e `role_id` e é por onde o frontend edita
usuário hoje; se só os `PATCH` da entrega seguinte gravassem, a trilha nasceria
com um buraco do tamanho do uso real. Os `PATCH` novos chamarão estas mesmas
funções.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.evento_conta import EventoDeConta
from app.models.role import Role
from app.models.setor import Setor
from app.models.usuario import Usuario

# Vocabulário de `acao`. Verbo no substantivo, sem acento, como o resto das
# colunas de texto técnico do projeto.
ACAO_CRIACAO = "criacao"
ACAO_DESATIVACAO = "desativacao"
ACAO_REATIVACAO = "reativacao"
ACAO_ALTERACAO_DE_NOME = "alteracao_de_nome"
ACAO_ALTERACAO_DE_PERFIL = "alteracao_de_perfil"
ACAO_ALTERACAO_DE_SETOR = "alteracao_de_setor"
ACAO_ALTERACAO_DE_SENHA = "alteracao_de_senha"
ACAO_ALTERACAO_DE_CONTA_DE_SERVICO = "alteracao_de_conta_de_servico"

# Campos do cadastro acompanhados pela trilha: exatamente os que o
# `UsuarioUpdate` aceita, menos a senha (tratada à parte, sem valores).
#
# A regra é "todo campo que a edição pode mudar gera evento", e não uma lista
# do que parece relevante para segurança. Uma lista curta obriga a explicar,
# depois, por que uma alteração feita pela tela não aparece em lugar nenhum.
CAMPOS_ACOMPANHADOS = ("nome", "ativo", "role_id", "setor_id", "conta_de_servico")

# Usado quando o campo estava (ou ficou) vazio — `setor_id` é anulável. Um NULL
# aqui seria ambíguo: não se distinguiria "o setor era nenhum" de "este evento
# não tem valores", que é o caso da senha.
SEM_VALOR = "(nenhum)"

_ACAO_POR_CAMPO = {
    "nome": ACAO_ALTERACAO_DE_NOME,
    "role_id": ACAO_ALTERACAO_DE_PERFIL,
    "setor_id": ACAO_ALTERACAO_DE_SETOR,
    "conta_de_servico": ACAO_ALTERACAO_DE_CONTA_DE_SERVICO,
}


def instantaneo(usuario: Usuario) -> dict:
    """
    Cópia dos campos acompanhados, para comparar depois da edição.

    Precisa ser chamado ANTES de aplicar as mudanças: depois do `setattr` o
    valor antigo já não existe em lugar nenhum — é justamente o que
    `usuarios.updated_at` não guarda.
    """
    return {campo: getattr(usuario, campo) for campo in CAMPOS_ACOMPANHADOS}


def _nome_da_role(db: Session, role_id: Optional[int]) -> str:
    if role_id is None:
        return SEM_VALOR
    role = db.query(Role).filter(Role.id == role_id).first()
    # Perfil apagado depois do evento não pode derrubar a gravação; o id cru
    # ainda diz mais do que nada.
    return role.nome if role else str(role_id)


def _nome_do_setor(db: Session, setor_id: Optional[int]) -> str:
    if setor_id is None:
        return SEM_VALOR
    setor = db.query(Setor).filter(Setor.id == setor_id).first()
    return setor.nome if setor else str(setor_id)


def _texto(db: Session, campo: str, valor) -> str:
    """
    Valor em texto legível por gente.

    Perfil e setor viram NOME, não id: o nome é o que a pessoa lê na tela, e
    guardá-lo congela o que o valor significava naquele momento — renomear o
    setor depois não reescreve a história. O id sozinho envelhece pior, porque
    depende de uma consulta que devolve o presente.
    """
    if campo == "role_id":
        return _nome_da_role(db, valor)
    if campo == "setor_id":
        return _nome_do_setor(db, valor)
    if valor is None:
        return SEM_VALOR
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def _novo_evento(
    *,
    usuario: Usuario,
    ator: Usuario,
    acao: str,
    origem: Optional[str],
    valor_anterior: Optional[str] = None,
    valor_novo: Optional[str] = None,
) -> EventoDeConta:
    return EventoDeConta(
        usuario_id=usuario.id,
        ator_id=ator.id,
        acao=acao,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
        origem=origem,
    )


def registrar_criacao(
    db: Session, *, usuario: Usuario, ator: Usuario, origem: Optional[str] = None
) -> EventoDeConta:
    """
    Evento de conta criada. Exige `usuario.id`, então roda depois do `flush`.

    `valor_novo` guarda o nome de login com que a conta nasceu: é o começo da
    corrente que as renomeações continuam. Sem ele, a primeira renomeação
    apareceria vindo do nada.
    """
    evento = _novo_evento(
        usuario=usuario,
        ator=ator,
        acao=ACAO_CRIACAO,
        origem=origem,
        valor_novo=usuario.nome,
    )
    db.add(evento)
    return evento


def registrar_alteracoes(
    db: Session,
    *,
    usuario: Usuario,
    antes: dict,
    ator: Usuario,
    origem: Optional[str] = None,
    senha_alterada: bool = False,
) -> list:
    """
    Compara o `instantaneo` de antes com o estado atual e grava uma linha por
    campo alterado. Uma requisição que muda perfil e setor gera dois eventos.

    Campo reenviado com o mesmo valor não gera evento. O modal de usuário do
    frontend envia o cadastro inteiro em toda gravação — registrar presença de
    campo, em vez de mudança de valor, encheria a trilha de linhas dizendo que
    nada aconteceu, e é isso que faz uma trilha deixar de ser lida.

    A senha entra por fora da comparação, e de propósito: o que existe em
    memória é o hash, e hash — antigo ou novo — não entra na trilha. O evento
    registra que a senha mudou, quem mudou e quando, sem valores.
    """
    eventos = []

    for campo in CAMPOS_ACOMPANHADOS:
        anterior = antes.get(campo)
        atual = getattr(usuario, campo)
        if anterior == atual:
            continue

        if campo == "ativo":
            acao = ACAO_REATIVACAO if atual else ACAO_DESATIVACAO
        else:
            acao = _ACAO_POR_CAMPO[campo]

        eventos.append(
            _novo_evento(
                usuario=usuario,
                ator=ator,
                acao=acao,
                origem=origem,
                valor_anterior=_texto(db, campo, anterior),
                valor_novo=_texto(db, campo, atual),
            )
        )

    if senha_alterada:
        eventos.append(
            _novo_evento(
                usuario=usuario,
                ator=ator,
                acao=ACAO_ALTERACAO_DE_SENHA,
                origem=origem,
            )
        )

    for evento in eventos:
        db.add(evento)

    return eventos
