"""
Quem pode atender chamado da Qualidade.

Fonte única da regra de elegibilidade: a lista de atendentes oferecida ao
formulário, a validação do responsável na abertura e na reatribuição, e a
autorização de quem atende passam todas por `eh_elegivel`. Duas cópias da
regra seriam o caminho para o seletor oferecer alguém que a gravação recusa.

Elegível é a conta ativa, que não é conta de serviço e pertence ao setor
configurado em `SETOR_QUALIDADE_ID` — com qualquer perfil. Perfil não entra
na regra: quem atende a Qualidade é quem trabalha nela, e um técnico da TI
não passa a atender a Qualidade por ter perfil de atendimento.

Sem HTTP aqui, como nos outros serviços: as falhas saem como exceções de
domínio, e o endpoint decide o código de resposta.
"""

import logging
from typing import List

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chamado import Chamado
from app.models.setor import Setor
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)


class QualidadeIndisponivel(Exception):
    """Setor da Qualidade sem configuração válida neste ambiente."""


class AtendenteNaoEncontrado(Exception):
    """O id informado como responsável não existe."""


class AtendenteInelegivel(Exception):
    """A conta existe, mas não pode atender a Qualidade."""


class ChamadoForaDaQualidade(Exception):
    """O chamado é de outro setor de destino."""


class NaoEhResponsavel(Exception):
    """Quem pede atende a Qualidade, mas o chamado está com outra pessoa."""


# Valor de `chamados.setor_destino` (CHECK `chk_setor_destino`).
SETOR_DESTINO_QUALIDADE = "QUALIDADE"


def setor_qualidade(db: Session) -> Setor:
    """
    O setor configurado, se existir e estiver ativo.

    Lê `settings` a cada chamada, e não uma cópia guardada no import, para
    que a configuração valha sempre do jeito que está agora.

    Setor ausente ou inativo com o id configurado é configuração quebrada, não
    erro de quem chama: fecha a Qualidade e deixa o motivo no log, onde quem
    administra o ambiente vai procurar.
    """
    setor_id = settings.SETOR_QUALIDADE_ID
    if setor_id is None:
        raise QualidadeIndisponivel()

    setor = db.query(Setor).filter(Setor.id == setor_id).first()
    if setor is None or not setor.ativo:
        logger.error(
            "SETOR_QUALIDADE_ID=%s aponta para setor %s; abertura para a Qualidade fechada",
            setor_id,
            "inexistente" if setor is None else "inativo",
        )
        raise QualidadeIndisponivel()
    return setor


def eh_elegivel(usuario: Usuario, setor: Setor) -> bool:
    """A regra de elegibilidade, num lugar só."""
    return bool(usuario.ativo) and not usuario.conta_de_servico and usuario.setor_id == setor.id


def listar_atendentes(db: Session) -> List[Usuario]:
    """
    Atendentes elegíveis, por nome.

    Carrega as contas do setor e filtra com `eh_elegivel`, em vez de repetir
    a regra em SQL: o setor tem poucas pessoas, e uma segunda versão da regra
    é exatamente o que este módulo existe para evitar.
    """
    setor = setor_qualidade(db)
    contas = db.query(Usuario).filter(Usuario.setor_id == setor.id).order_by(Usuario.nome).all()
    return [conta for conta in contas if eh_elegivel(conta, setor)]


def buscar_atendente(db: Session, usuario_id: int) -> Usuario:
    """
    O responsável escolhido, validado.

    A configuração é conferida antes do atendente: sem Qualidade configurada a
    resposta é a mesma para qualquer id, e não revela quais existem.
    """
    setor = setor_qualidade(db)

    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if usuario is None:
        raise AtendenteNaoEncontrado()
    if not eh_elegivel(usuario, setor):
        raise AtendenteInelegivel()
    return usuario


def verificar_atendimento(db: Session, chamado: Chamado, usuario: Usuario) -> None:
    """
    Se `usuario` pode atender `chamado` pela rota de atendimento.

    Tudo vem do banco, relido na requisição: o chamado carregado pelo
    endpoint e a conta autenticada. Nada do corpo entra na decisão — o
    responsável é o que está gravado, não o que o cliente disser.

    Perfil não dá passe: administrador e técnico só atendem por aqui se forem
    da Qualidade e responsáveis, como qualquer um. Fora disso, usam o PUT.

    A ordem decide a resposta: setor do chamado, configuração, elegibilidade
    de quem pede e, por último, a responsabilidade.
    """
    if chamado.setor_destino != SETOR_DESTINO_QUALIDADE:
        raise ChamadoForaDaQualidade()

    setor = setor_qualidade(db)
    if not eh_elegivel(usuario, setor):
        raise AtendenteInelegivel()
    if chamado.tecnico_responsavel_id != usuario.id:
        raise NaoEhResponsavel()
