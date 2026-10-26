from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from pydantic_core import PydanticCustomError
from typing import Annotated, Any, Literal, Optional
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
    """
    Chamado novo para a TI: aqui o mínimo vale, porque não há legado para
    respeitar.

    A Qualidade tem corpo próprio, `ChamadoCreateQualidade`, e o endpoint
    escolhe a classe pelo `setor_destino` recebido. Esta classe ficou como era
    antes da Qualidade existir de propósito: são os erros de validação dela
    que o frontend atual sabe exibir, e eles não podem mudar.
    """

    titulo: TituloChamado
    descricao: DescricaoChamado
    solicitante_id: int
    # Fora de `ChamadoBase` pelo mesmo motivo dos mínimos de texto: a regra de
    # entrada abaixo não pode valer para a resposta. Omitir o campo é o jeito
    # de pedir TI — é o que o frontend atual faz.
    setor_destino: SetorDestinoEnum = Field(
        SetorDestinoEnum.TI,
        description=(
            "Setor que atende o chamado. Omitido = TI. Com QUALIDADE o corpo "
            "segue `ChamadoCreateQualidade`."
        ),
    )

    @field_validator("setor_destino")
    @classmethod
    def _so_ti(cls, valor: SetorDestinoEnum) -> SetorDestinoEnum:
        """
        Trava para quem usar esta classe fora do endpoint de criação.

        Pelo endpoint, QUALIDADE nunca chega aqui. Mas esta classe não valida
        responsável nem gera título: se aceitasse QUALIDADE, nasceria um
        chamado da Qualidade sem as regras dela.
        """
        if valor is SetorDestinoEnum.QUALIDADE:
            raise ValueError("Chamado da Qualidade usa o corpo ChamadoCreateQualidade")
        return valor


class ChamadoCreateQualidade(BaseModel):
    """
    Chamado novo para a Qualidade.

    O formulário da Qualidade não tem título nem categoria: o título é gerado
    da descrição e a categoria fica nula. O responsável é obrigatório e passa
    pela regra de elegibilidade no endpoint (`qualidade_service`).

    `titulo` e `categoria_id` estão declarados só para serem recusados. É a
    presença que conta, não o valor — até `null` é recusado: receber esses
    campos indica um cliente montando o corpo errado, e ignorá-los em silêncio
    esconderia o defeito. O validador só roda quando o campo vem na
    requisição, porque o padrão não é validado.
    """

    setor_destino: Literal[SetorDestinoEnum.QUALIDADE]
    titulo: Optional[Any] = Field(None, description="Não enviar: gerado da descrição.")
    descricao: DescricaoChamado
    categoria_id: Optional[Any] = Field(None, description="Não enviar: a Qualidade não usa categoria.")
    prioridade: PrioridadeEnum = PrioridadeEnum.MEDIA
    solicitante_id: int
    tecnico_responsavel_id: int = Field(
        ...,
        description="Atendente da Qualidade. Opções em GET /chamados/atendentes-qualidade.",
    )

    @field_validator("titulo", "categoria_id", mode="before")
    @classmethod
    def _nao_se_aplica(cls, valor):
        raise PydanticCustomError("nao_se_aplica", "Não se aplica a chamados da Qualidade")


class AtendenteQualidade(BaseModel):
    """Opção do seletor de responsável da Qualidade: só o necessário para escolher."""

    id: int
    nome: str

    model_config = ConfigDict(from_attributes=True)


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
