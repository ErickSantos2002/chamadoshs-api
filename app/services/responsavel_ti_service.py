"""
Quem pode ser escolhido como NOVO responsável de chamado da TI.

Fonte única da regra, como `qualidade_service` é para a Qualidade: a
validação da mudança de responsável no PUT e a lista do seletor
(`GET /chamados/responsaveis-ti`, API-9) passam por `pode_ser_novo_responsavel`.
Uma segunda cópia da regra seria o caminho para a tela oferecer alguém que a
gravação recusa.

A regra é da conta a atribuir, e não de quem atribui: nem o administrador põe
um chamado da TI com quem não é da equipe. Ser da equipe é `integra_equipe_ti`
(API-6, D9) — perfil de equipe num setor de `SETORES_TI_IDS`; o administrador
fora desses setores não é elegível. Conta de serviço nunca é, e conta
inativa também não (API-9): até a API-8 o técnico desativado num setor da TI
ainda recebia chamado novo, que ninguém atenderia — ele nem consegue entrar.

Vale para a MUDANÇA de responsável (ver `_validar_tecnico_responsavel`): o
chamado antigo com responsável que hoje não passaria continua com ele, e
editável.

Sem HTTP aqui, como nos outros serviços: o motivo sai como texto, e o
endpoint decide o código de resposta.
"""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.usuario import Usuario
from app.services.leitura_service import integra_equipe_ti

logger = logging.getLogger(__name__)

CONTA_DE_SERVICO = "Não é possível atribuir um chamado a uma conta de serviço"
FORA_DA_EQUIPE = "Técnico responsável não é da equipe da TI"
INATIVO = "Técnico responsável está inativo"


def motivo_de_recusa(usuario: Usuario) -> Optional[str]:
    """
    Por que `usuario` não pode ser o novo responsável, ou `None` se pode.

    A ordem decide só a mensagem, não o resultado: quem falha em qualquer
    condição é recusado. O inativo vem por último para que nenhuma recusa
    que já existia mude de texto: o inativo de fora da TI continua "não é
    da equipe".

    `ativo` NULL conta como inativo: a coluna aceita, e a dúvida não atribui.
    """
    if usuario.conta_de_servico:
        return CONTA_DE_SERVICO
    if not integra_equipe_ti(usuario):
        return FORA_DA_EQUIPE
    if usuario.ativo is not True:
        return INATIVO
    return None


def pode_ser_novo_responsavel(usuario: Usuario) -> bool:
    """A regra de elegibilidade, num lugar só."""
    return motivo_de_recusa(usuario) is None


def listar_responsaveis(db: Session) -> List[Usuario]:
    """
    Quem pode ser escolhido agora como novo responsável, por nome e id.

    O SQL só estreita aos setores da TI, para não carregar a tabela inteira;
    quem decide é `pode_ser_novo_responsavel`, a mesma função da validação,
    como `listar_atendentes` faz na Qualidade. A role vem no mesmo SELECT:
    sem o `joinedload`, `integra_equipe_ti` faria uma consulta por conta.

    O id desempata o nome, que não precisa ser único para a ordem ser a
    mesma a cada pedido. Sem `SETORES_TI_IDS` válida nenhum setor é da TI, e
    a lista sai vazia sem consultar: nada de cair em "todos os técnicos".
    """
    setores = settings.setores_ti_ids
    if not setores:
        # Só o administrador chega aqui assim: o técnico precisa da lista
        # para passar por `require_equipe_ti`.
        logger.warning("Lista de responsáveis da TI vazia: SETORES_TI_IDS sem setor válido da TI")
        return []
    contas = (
        db.query(Usuario)
        .options(joinedload(Usuario.role))
        .filter(Usuario.setor_id.in_(sorted(setores)))
        .order_by(Usuario.nome, Usuario.id)
        .all()
    )
    return [conta for conta in contas if pode_ser_novo_responsavel(conta)]
