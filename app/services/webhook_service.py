import logging

import requests
from typing import Iterable, Optional
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)


def enviar_webhook_tecnico(
    db: Session,
    protocolo: str,
    titulo: str,
    tecnico_id: Optional[int] = None,
    acao: str = "criado"
):
    """
    Envia webhook para n8n com informações do técnico atribuído

    A URL vem de WEBHOOK_TECNICO_URL. Se estiver vazia, o envio é ignorado —
    é o padrão, para que desenvolvimento e testes não disparem notificação no
    fluxo de produção por descuido.

    Quando WEBHOOK_TECNICO_TOKEN está definida, o valor vai no header de
    autenticação esperado pelo nó Webhook do n8n (Header Auth). Sem ela, o
    header não é enviado — ver a nota em `config.py` sobre a ordem de subida.

    Args:
        db: Sessão do banco de dados
        protocolo: Protocolo do chamado
        titulo: Título do chamado
        tecnico_id: ID do técnico responsável (None = Sem atribuição)
        acao: Tipo de ação ("criado" ou "atribuido")
    """
    if not settings.WEBHOOK_TECNICO_URL:
        logger.debug(
            "WEBHOOK_TECNICO_URL não configurada; envio ignorado para o chamado %s",
            protocolo,
        )
        return

    try:
        # Buscar nome do técnico
        nome_tecnico = "Sem atribuição"
        if tecnico_id:
            tecnico = db.query(Usuario).filter(Usuario.id == tecnico_id).first()
            if tecnico:
                nome_tecnico = tecnico.nome

        # Preparar payload
        payload = {
            "protocolo": protocolo,
            "titulo": titulo,
            "tecnico": nome_tecnico,
            "acao": acao
        }

        # Header de autenticação, quando configurado. Montado aqui e não em
        # nível de módulo para que uma troca do segredo valha na reinicialização
        # do container, sem depender da ordem de import.
        headers = {}
        if settings.WEBHOOK_TECNICO_TOKEN:
            headers[settings.WEBHOOK_TECNICO_HEADER] = settings.WEBHOOK_TECNICO_TOKEN

        # Enviar webhook
        response = requests.post(
            settings.WEBHOOK_TECNICO_URL,
            json=payload,
            timeout=settings.WEBHOOK_TIMEOUT_SEGUNDOS,
            headers=headers,
        )

        # Log do resultado. Nem a URL nem o token são registrados: os dois
        # valem como credencial do fluxo no n8n.
        if response.status_code == 200:
            logger.info("Webhook enviado com sucesso para o chamado %s", protocolo)
        elif response.status_code in (401, 403):
            # Caso típico de configuração torta: o n8n já exige Header Auth e o
            # backend ainda não tem o segredo (ou tem o segredo errado). Vale
            # uma mensagem própria porque o sintoma — chamado criado, técnico
            # não notificado — é silencioso do lado de quem usa o sistema.
            logger.error(
                "Webhook recusado com status %s para o chamado %s: "
                "verifique se WEBHOOK_TECNICO_TOKEN confere com o Header Auth do n8n",
                response.status_code,
                protocolo,
            )
        else:
            logger.warning(
                "Webhook retornou status %s para o chamado %s",
                response.status_code,
                protocolo,
            )

    except requests.exceptions.Timeout:
        logger.warning("Timeout ao enviar webhook para o chamado %s", protocolo)
    except Exception as e:
        # Não quebrar a aplicação se o webhook falhar
        logger.error("Erro ao enviar webhook para o chamado %s: %s", protocolo, e)


# ---------------------------------------------------------------------------
# Notificação da Qualidade (API-15)
#
# Fluxo próprio no n8n, sem relação com o da TI acima: outra URL, outro
# segredo, outro contrato. A API diz O QUE aconteceu e QUEM deve ser avisado,
# por id; o telefone de cada um mora no n8n, e nunca passa por aqui. O payload
# não leva título, descrição nem nome de ninguém.
# ---------------------------------------------------------------------------

EVENTO_CHAMADO_ABERTO = "chamado_aberto"
EVENTO_RESPONSAVEL_ATRIBUIDO = "responsavel_atribuido"


def webhook_qualidade_ligado() -> bool:
    """A URL configurada. Sem ela, quem chama nem monta o evento."""
    return bool(settings.WEBHOOK_QUALIDADE_URL)


def montar_evento_qualidade(
    evento: str,
    chamado_id: int,
    protocolo: str,
    versao: int,
    autor_id: int,
    destinatarios_ids: Iterable[int],
    responsavel_id: Optional[int] = None,
    responsavel_anterior_id: Optional[int] = None,
) -> Optional[dict]:
    """
    O corpo do evento, ou `None` quando não há a quem avisar.

    O autor da ação nunca é destinatário: quem abriu ou assumiu o chamado já
    sabe. Sem destinatário não há evento — assumir o próprio chamado não
    dispara nada.

    `id_evento` é estável e único por escrita: a versão do chamado sobe uma
    vez a cada mudança gravada, então chamado + versão + evento não se repete
    e é o mesmo se este corpo for entregue duas vezes. É a chave que o n8n usa
    para não avisar de novo; por destinatário, a chave é
    `<id_evento>:<destinatario_id>`.
    """
    destinatarios = sorted({d for d in destinatarios_ids if d is not None and d != autor_id})
    if not destinatarios:
        return None

    return {
        "evento": evento,
        "id_evento": f"{chamado_id}:{versao}:{evento}",
        "setor": "QUALIDADE",
        "chamado": {"id": chamado_id, "protocolo": protocolo, "versao": versao},
        "responsavel_id": responsavel_id,
        "responsavel_anterior_id": responsavel_anterior_id,
        "autor_id": autor_id,
        "destinatarios_ids": destinatarios,
    }


def enviar_webhook_qualidade(payload: dict) -> None:
    """
    Entrega um evento da Qualidade ao n8n. Uma tentativa, sem repetição.

    Não repete de propósito: um POST que o n8n recebeu e cuja resposta se
    perdeu, repetido, vira a mesma mensagem duas vezes no telefone de alguém.
    A falha fica no log, com o `id_evento`, para quem for reenviar à mão.

    Roda depois do commit e fora da requisição (tarefa de fundo): nada aqui
    desfaz a abertura ou a atribuição, e nenhuma exceção sai daqui.
    """
    id_evento = payload.get("id_evento")

    if not settings.WEBHOOK_QUALIDADE_URL:
        logger.debug("WEBHOOK_QUALIDADE_URL não configurada; evento %s ignorado", id_evento)
        return

    if not settings.WEBHOOK_QUALIDADE_TOKEN:
        logger.error(
            "WEBHOOK_QUALIDADE_URL configurada sem WEBHOOK_QUALIDADE_TOKEN; evento %s não enviado",
            id_evento,
        )
        return

    try:
        # Nem a URL nem o token são registrados: os dois valem como
        # credencial do fluxo no n8n.
        response = requests.post(
            settings.WEBHOOK_QUALIDADE_URL,
            json=payload,
            timeout=settings.WEBHOOK_TIMEOUT_SEGUNDOS,
            headers={settings.WEBHOOK_QUALIDADE_HEADER: settings.WEBHOOK_QUALIDADE_TOKEN},
        )

        if 200 <= response.status_code < 300:
            logger.info("Webhook da Qualidade entregue: evento %s", id_evento)
        elif response.status_code in (401, 403):
            logger.error(
                "Webhook da Qualidade recusado com status %s para o evento %s: "
                "verifique se WEBHOOK_QUALIDADE_TOKEN confere com o Header Auth do n8n",
                response.status_code,
                id_evento,
            )
        else:
            logger.warning(
                "Webhook da Qualidade retornou status %s para o evento %s",
                response.status_code,
                id_evento,
            )

    except requests.exceptions.Timeout:
        # Entrega incerta: o n8n pode ter recebido. Não repetir.
        logger.warning("Timeout no webhook da Qualidade para o evento %s (entrega incerta)", id_evento)
    except Exception as e:
        logger.error("Erro no webhook da Qualidade para o evento %s: %s", id_evento, type(e).__name__)
