"""
Quem pode ser escolhido como NOVO responsável de chamado da TI.

Fonte única da regra, como `qualidade_service` é para a Qualidade: a
validação da mudança de responsável no PUT passa por `motivo_de_recusa`.
Uma segunda cópia da regra seria o caminho para uma tela oferecer alguém que
a gravação recusa.

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

from typing import Optional

from app.models.usuario import Usuario
from app.services.leitura_service import integra_equipe_ti

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
