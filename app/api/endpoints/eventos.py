from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, is_admin, require_staff
from app.models.usuario import Usuario
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
    # `skip` tem as duas pontas limitadas, e cada uma protege de uma coisa.
    #
    # ge=0: a mescla termina num `juntos[skip : skip + limit]`, e slice de
    # Python aceita índice negativo contando do fim. Um `skip=-5` devolveria
    # silenciosamente as linhas mais ANTIGAS numa consulta que promete as mais
    # recentes.
    #
    # le: `skip + limit` vira o `LIMIT` das DUAS tabelas, e tudo que voltar é
    # materializado como dicionário nesta máquina antes do corte. É o preço de
    # mesclar fora do banco, e ele cresce junto com a trilha — que é uma tabela
    # feita para nunca ser podada. Sem teto, `?skip=50000000` manda o banco
    # varrer tudo que existir e o processo montar dicionário de cada linha.
    # 10 mil é fundo de sobra para navegação de tela; auditoria que precise ir
    # além disso pede filtro (`de`/`ate`/`ator_id`), não página 200.
    skip: int = Query(0, ge=0, le=10_000),
    limit: int = Query(100, ge=1, le=500),
    autor: Usuario = Depends(require_staff),
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

    **Técnico vê apenas eventos de SETOR.** Ele passou a administrar setores,
    categorias e SLA, e audita o que administra — mas eventos de conta dizem
    quem redefiniu a senha de quem, quem promoveu quem a administrador e quem
    desativou quem, e isso fica com o administrador.

    A separação é por tipo de alvo, e não por endpoint, porque endpoint não
    separa nada aqui: esta rota devolve exatamente os mesmos eventos de conta
    que `GET /usuarios/{id}/eventos`, só que de todas as contas de uma vez.
    Proteger lá e liberar aqui deixaria a restrição decorativa — a informação
    sairia pela porta ao lado, que é a forma exata do defeito que o passo 0
    fechou entre o `DELETE` e o `PUT`.
    """
    if not is_admin(autor):
        if alvo is None:
            # Sem alvo, o padrão seria "os dois". Para técnico isso vira
            # "só setor" em vez de 403: o pedido é legítimo, e recusá-lo
            # obrigaria a tela a saber o perfil para montar a query.
            alvo = trilha_service.ALVO_SETOR
        elif alvo != trilha_service.ALVO_SETOR:
            raise HTTPException(
                status_code=403,
                detail="Requer perfil: Administrador para ver eventos de conta",
            )

    try:
        return trilha_service.consultar(
            db, alvo=alvo, ator_id=ator_id, de=de, ate=ate, skip=skip, limit=limit
        )
    except ValueError as erro:
        # Alvo fora do vocabulário é dado inválido do cliente, não defeito do
        # servidor. Sem isto o ValueError sobe como 500.
        raise HTTPException(status_code=400, detail=str(erro))
