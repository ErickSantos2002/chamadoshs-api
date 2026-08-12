from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class EventoResponse(BaseModel):
    """
    Uma linha da trilha de auditoria, no mesmo formato para conta e setor.

    As duas tabelas têm colunas diferentes de propósito (o alvo de
    `eventos_de_setor` não tem FK, porque setor vira apagável), mas a pergunta
    que a tela faz é uma só — "quem fez o quê, com o quê, e quando". Um formato
    por tabela obrigaria o frontend a manter duas renderizações do mesmo painel.

    `alvo_tipo` + `alvo_id` dizem sobre o que é o evento; `alvo_nome` é o nome
    legível daquele momento — congelado na linha, no caso de setor, e resolvido
    por join, no caso de conta.
    """

    # Chave única na trilha inteira. Os ids são de tabelas diferentes e colidem
    # entre si (existe evento de conta 1 e evento de setor 1); o par com o tipo
    # é o que a lista do frontend pode usar como chave sem duplicar.
    chave: str
    id: int
    alvo_tipo: str
    alvo_id: int
    alvo_nome: Optional[str] = None
    ator_id: int
    ator_nome: Optional[str] = None
    acao: str
    valor_anterior: Optional[str] = None
    valor_novo: Optional[str] = None
    origem: Optional[str] = None
    created_at: Optional[datetime] = None
