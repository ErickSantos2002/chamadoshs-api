"""
Estado de saúde da API, para a faixa de status do frontend e para monitoramento.

**Público, e por isso mudo.** É o único endpoint `/api/v1` que responde sem
token, então tudo que ele devolve é legível por qualquer pessoa na internet.
Daí a resposta ser um contrato fechado de três campos: nem versão da API, nem
nome ou host do banco, nem contagem de registros, nem nada vindo do ambiente.
Endpoint de saúde é alvo clássico de reconhecimento — a graça de atacar é que
ele responde sem credencial e costuma ser escrito para "ajudar a depurar".

**A mensagem da exceção também não sai daqui.** Um `OperationalError` do
psycopg2 traz host, porta, usuário e nome do banco no texto. Ele vai para o log
da aplicação, que é onde a informação é útil e onde o acesso já é controlado.

**Barato o suficiente para rodar a cada 60s**, e não é o `diagnostico.py`:
aquele conta usuários, consulta `information_schema` e monta amostra — é
relatório administrativo, restrito a administrador, e cobra caro por resposta.
Aqui é um `SELECT 1`, que é o mínimo capaz de distinguir "o pool devolve
conexão" de "o banco não responde".

**Por que 503 e não 200 com `status: degradado`:** o front precisa separar "API
caiu" (não houve resposta) de "API no ar, banco fora" (503 com corpo). Um 200
carregando a palavra "degradado" faz as duas coisas dependerem de o cliente ler
o corpo — e todo monitoramento que olha só o código de status, incluindo o do
Easypanel, veria saúde onde não há.
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.utils.timezone import agora_brasilia

logger = logging.getLogger(__name__)

router = APIRouter()


# O caminho vem inteiro daqui, e o router é incluído com prefixo "/api/v1":
# declarar "/" sob o prefixo "/api/v1/health" produziria "/api/v1/health/", e
# quem chamasse sem a barra final levaria um 307. Redirecionamento em endpoint
# de saúde é ruído garantido — alguns monitores tratam 3xx como falha.
@router.get("/health")
def health(db: Session = Depends(get_db)):
    """
    Diz se a API está no ar e se o banco responde.

    - **200** `{"status": "ok", "banco": "ok", "hora": "<ISO-8601 com fuso>"}`
    - **503** `{"status": "degradado", "banco": "erro"}`

    Não exige autenticação: a faixa de status do frontend precisa dele antes do
    login, e um monitor externo não tem credencial.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        # exc_info no log, nada no corpo: a mensagem do driver traz host,
        # porta, usuário e nome do banco.
        logger.error("Health check falhou: banco não respondeu", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"status": "degradado", "banco": "erro"},
        )

    return {
        "status": "ok",
        "banco": "ok",
        # Com fuso explícito. Um horário sem fuso obriga quem lê a adivinhar se
        # é UTC ou Brasília — o container roda em UTC e o sistema opera em
        # Brasília, então a diferença é de três horas e passa despercebida.
        "hora": agora_brasilia().isoformat(),
    }
