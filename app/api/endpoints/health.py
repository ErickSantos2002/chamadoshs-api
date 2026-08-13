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

--------------------------------------------------------------------------
O QUE É INTERFACE AQUI: O CÓDIGO DE STATUS
--------------------------------------------------------------------------

A faixa de status do frontend (1.4.1 em diante) lê **só o código**, nunca o
corpo, e o traduz assim:

    200          -> "sistema ativo"
    503          -> "banco fora"
    outro / erro -> "sem resposta"

A terceira linha existe porque num 500, 502 ou 504 quem respondeu pode nem ter
sido esta aplicação: afirmar "o banco caiu" a partir de um 502 do proxy seria
inventar diagnóstico. É a leitura certa, e ela tem uma consequência para quem
edita este arquivo.

**Trocar 503 por outro 5xx não é detalhe de implementação — muda o que a tela
diz.** "Banco fora" viraria "sem resposta", sem nada falhar deste lado. O
mesmo vale para o 200: um 204 apagaria a faixa. Mexer em qualquer um dos dois
exige avisar quem cuida do frontend, que é outra sessão de trabalho.

Os dois códigos têm teste dedicado em `tests/test_health.py`
(`test_e_503_exato_e_nao_um_5xx_qualquer` e `test_saudavel_e_200_exato`),
justamente para a mudança falhar antes de chegar à tela.

O contrato do CORPO é outra coisa, e protege outro risco: não vazar nada num
endpoint público. Os dois convivem — corpo fechado por segurança, código de
status fechado por compatibilidade.

--------------------------------------------------------------------------

**Carga esperada:** uma consulta por minuto, por aba aberta, por pessoa — o
front pausa com a aba oculta e refaz ao voltar — com timeout de 5s do lado
dele. É o que "barato o suficiente" precisa suportar aqui, e por isso a
verificação é um `SELECT 1` e não uma agregação.
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
