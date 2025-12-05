import requests
from typing import Optional
from sqlalchemy.orm import Session
from app.models.usuario import Usuario


WEBHOOK_URL = "https://n8n.healthsafetytech.com/webhook/b7c8e523-a185-4308-9d43-58d30a1b4251"


def enviar_webhook_tecnico(
    db: Session,
    protocolo: str,
    titulo: str,
    tecnico_id: Optional[int] = None,
    acao: str = "criado"
):
    """
    Envia webhook para n8n com informações do técnico atribuído

    Args:
        db: Sessão do banco de dados
        protocolo: Protocolo do chamado
        titulo: Título do chamado
        tecnico_id: ID do técnico responsável (None = Sem atribuição)
        acao: Tipo de ação ("criado" ou "atribuido")
    """
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
            WEBHOOK_URL,
            json=payload,
            timeout=5  # Timeout de 5 segundos
        )

        # Log do resultado (opcional)
        if response.status_code == 200:
            print(f"✅ Webhook enviado com sucesso para chamado {protocolo}")
        else:
            print(f"⚠️ Webhook retornou status {response.status_code} para chamado {protocolo}")

    except requests.exceptions.Timeout:
        print(f"⚠️ Timeout ao enviar webhook para chamado {protocolo}")
    except Exception as e:
        # Não quebrar a aplicação se o webhook falhar
        print(f"❌ Erro ao enviar webhook para chamado {protocolo}: {str(e)}")
