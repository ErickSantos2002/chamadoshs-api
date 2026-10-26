from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from typing import Annotated, Optional
from datetime import datetime
from enum import Enum

from app.schemas.sla import SLAInfo

# Tamanhos mínimos dos campos de texto do chamado, iguais aos que o frontend
# exige desde 11/08/2026.
#
# `strip_whitespace=True` é o que faz a regra valer: o Pydantic apara antes de
# medir, então uma barra de espaço repetida não satisfaz o mínimo — e o valor
# gravado no banco vai sem os espaços das pontas, em vez de guardar o que o
# formulário mandou.
#
# Estes tipos NÃO entram em `ChamadoBase`. Ver o comentário lá.
TituloChamado = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10)]
DescricaoChamado = Annotated[str, StringConstraints(strip_whitespace=True, min_length=20)]

# `solucao` guarda duas coisas: o texto da solução e o motivo do cancelamento
# — o `PATCH /cancelar` não tem corpo, então o motivo chega por `PUT {solucao}`
# e cai na mesma coluna. O mínimo aqui vale para os dois, e é isso que se
# quer: cancelar com "x" não pode passar por uma porta que resolver com "x"
# não passa.
SolucaoChamado = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10)]


class PrioridadeEnum(str, Enum):
    BAIXA = "Baixa"
    MEDIA = "Média"
    ALTA = "Alta"
    CRITICA = "Crítica"


class UrgenciaEnum(str, Enum):
    NAO_URGENTE = "Não Urgente"
    NORMAL = "Normal"
    URGENTE = "Urgente"
    MUITO_URGENTE = "Muito Urgente"


class StatusEnum(str, Enum):
    ABERTO = "Aberto"
    EM_ANDAMENTO = "Em Andamento"
    AGUARDANDO = "Aguardando"
    RESOLVIDO = "Resolvido"
    FECHADO = "Fechado"


class SetorDestinoEnum(str, Enum):
    """Setor que atende o chamado. Valores iguais aos do CHECK `chk_setor_destino`."""

    TI = "TI"
    QUALIDADE = "QUALIDADE"


class ChamadoBase(BaseModel):
    """
    Campos comuns de entrada e de saída.

    `titulo` e `descricao` ficam SEM tamanho mínimo aqui de propósito, mesmo
    sendo esse o lugar óbvio: `ChamadoResponse` herda desta classe, e o
    FastAPI valida a resposta contra ela. Um mínimo aqui faria todo chamado
    antigo com título curto — que existe, porque a API aceitou qualquer coisa
    até 11/08/2026 — estourar `ResponseValidationError` no `GET`. A regra
    entraria para melhorar o cadastro e derrubaria a leitura do histórico.

    O mínimo mora em `ChamadoCreate`, que é entrada pura.
    """

    titulo: str
    descricao: str
    categoria_id: Optional[int] = None
    prioridade: PrioridadeEnum = PrioridadeEnum.MEDIA


class ChamadoCreate(ChamadoBase):
    """Chamado novo: aqui o mínimo vale, porque não há legado para respeitar."""

    titulo: TituloChamado
    descricao: DescricaoChamado
    solicitante_id: int
    # Fora de `ChamadoBase` pelo mesmo motivo dos mínimos de texto: a regra de
    # entrada abaixo não pode valer para a resposta. Omitir o campo é o jeito
    # de pedir TI — é o que o frontend atual faz.
    setor_destino: SetorDestinoEnum = Field(
        SetorDestinoEnum.TI,
        description=(
            "Setor que atende o chamado. Por enquanto só TI é aceito na "
            "criação: QUALIDADE é recusado com 422."
        ),
    )

    @field_validator("setor_destino")
    @classmethod
    def _qualidade_ainda_indisponivel(cls, valor: SetorDestinoEnum) -> SetorDestinoEnum:
        """
        Recusa QUALIDADE até existirem as regras dela: atendente obrigatório e
        elegível, título derivado da descrição.

        Recusar, e não ignorar. Com o campo fora do schema, o Pydantic
        descartaria QUALIDADE em silêncio e o chamado nasceria como TI — um
        frontend adiantado abriria chamados no setor errado sem nenhum erro.
        """
        if valor is SetorDestinoEnum.QUALIDADE:
            raise ValueError("Chamados para a Qualidade ainda não estão disponíveis")
        return valor


class ChamadoUpdate(BaseModel):
    """
    Edição de chamado. Restrito a administrador ou técnico.

    O mínimo dos três campos de texto vale aqui, e não trava registro legado,
    porque o frontend não reenvia valor intocado: `titulo` e `descricao` ele
    nunca manda (editar descrição não existe na interface), e `solucao` só vai
    quando muda. Um chamado antigo de título curto continua editável — mexer
    no status não carrega o título junto.

    A validação só roda no campo que vem na requisição: o que não é enviado
    não é validado, e o handler grava com `exclude_unset=True`.
    """

    titulo: Optional[TituloChamado] = None
    descricao: Optional[DescricaoChamado] = None
    categoria_id: Optional[int] = None
    prioridade: Optional[PrioridadeEnum] = None
    urgencia: Optional[UrgenciaEnum] = None
    status: Optional[StatusEnum] = None
    tecnico_responsavel_id: Optional[int] = None
    solucao: Optional[SolucaoChamado] = None
    observacoes: Optional[str] = None
    avaliacao: Optional[int] = Field(None, ge=1, le=5)


class ChamadoAvaliacao(BaseModel):
    """
    Corpo do PATCH /chamados/{id}/avaliar.

    Schema próprio, e não `ChamadoUpdate`, porque este é o único corpo que o
    solicitante comum pode enviar: qualquer campo aqui é campo que ele passa a
    poder escrever. Manter só `avaliacao` é o que impede a rota de virar um
    caminho alternativo para mexer em status, prioridade ou técnico.

    `ge`/`le` espelham o CHECK da coluna — sem eles um 0 ou 6 só falharia no
    commit, virando 500 em vez de 422.
    """

    avaliacao: int = Field(..., ge=1, le=5)


class ChamadoResponse(ChamadoBase):
    id: int
    protocolo: str
    solicitante_id: int
    status: StatusEnum
    setor_destino: SetorDestinoEnum
    urgencia: Optional[UrgenciaEnum] = None
    tecnico_responsavel_id: Optional[int] = None
    solucao: Optional[str] = None
    tempo_resolucao_minutos: Optional[int] = None
    observacoes: Optional[str] = None
    avaliacao: Optional[int] = None
    cancelado: bool = False
    arquivado: bool = False
    data_abertura: datetime
    data_atualizacao: datetime
    data_resolucao: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    sla: Optional[SLAInfo] = None

    model_config = ConfigDict(from_attributes=True)
