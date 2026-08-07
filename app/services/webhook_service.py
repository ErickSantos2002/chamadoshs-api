import logging

import requests
from typing import Optional
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

        # Enviar webhook
        response = requests.post(
            settings.WEBHOOK_TECNICO_URL,
            json=payload,
            timeout=settings.WEBHOOK_TIMEOUT_SEGUNDOS,
        )

        # Log do resultado. A URL nunca é registrada: ela contém o
        # identificador do fluxo no n8n e vale como credencial.
        if response.status_code == 200:
            logger.info("Webhook enviado com sucesso para o chamado %s", protocolo)
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
