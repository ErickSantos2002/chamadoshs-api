from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.evento import EventoResponse
from app.services import trilha_service

router = APIRouter()


@router.get("/", response_model=List[EventoResponse])
def listar_eventos(
    alvo: Optional[str] = Query(
        None,
        description="usuario | setor. Omitido, devolve os dois mesclados por data.",
    ),
    ator_id: Optional[int] = Query(None, description="Quem praticou a ação"),
    de: Optional[date] = Query(None, description="Primeiro dia do período (inclusivo)"),
    ate: Optional[date] = Query(None, description="Último dia do período (inclusivo)"),
    # ge=0 e ge=1 não são zelo: a mescla das duas tabelas termina num
    # `juntos[skip : skip + limit]`, e slice de Python aceita índice negativo
    # contando do fim. Um `skip=-5` devolveria silenciosamente o rabo da lista
    # — as linhas mais ANTIGAS — numa consulta que promete as mais recentes.
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Trilha de auditoria dos cadastros, do mais recente para o mais antigo.
    Restrito a administrador (aplicado no router, em main.py).

    Junta usuários e setores num formato só: a pergunta da auditoria é "quem
    fez o quê, com o quê, e quando", e ela não muda conforme a tabela. O campo
    `alvo_tipo` diz de onde a linha veio, e `chave` é única na trilha inteira —
    os ids das duas tabelas colidem entre si.

    O período é em dias e os dois extremos entram. `ate=2026-08-12` inclui o dia
    12 até o fim, não até a meia-noite dele — que é o que devolveria uma lista
    vazia para quem filtra o dia corrente.
    """
    try:
        return trilha_service.consultar(
            db, alvo=alvo, ator_id=ator_id, de=de, ate=ate, skip=skip, limit=limit
        )
    except ValueError as erro:
        # Alvo fora do vocabulário é dado inválido do cliente, não defeito do
        # servidor. Sem isto o ValueError sobe como 500.
        raise HTTPException(status_code=400, detail=str(erro))
