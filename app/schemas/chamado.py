from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
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

# Versão do chamado em que o cliente baseou a escrita (API-4b): a `versao` da
# última resposta que ele leu. Pré-condição, nunca gravada — ver
# `app/services/versao_service.py`.
#
# `strict=True`: sem ele o Pydantic aceitaria `true` como 1 e "5" como 5.
#
# O campo é declarado `VersaoEsperada = None`, e não `Optional[...]`, de
# propósito. O default não passa pela validação, então AUSENTE vira None e o
# endpoint decide (428 na Qualidade, segue na TI); já um `null` EXPLÍCITO é
# validado contra `int` e vira 422 — corpo errado, não versão faltando.
VersaoEsperada = Annotated[
    int,
    Field(
        strict=True,
        ge=1,
        description=(
            "Versão do chamado na última leitura. Obrigatória em chamado da "
            "Qualidade (sem ela, 428); divergente da atual, 409."
        ),
    ),
]


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


def _documentar_so_ti(schema: dict) -> None:
    """
    No OpenAPI, `setor_destino` da TI aceita só TI.

    O tipo continua sendo o enum inteiro, para o erro de valor inválido ser
    o mesmo de antes. Mas QUALIDADE nunca chega a esta classe — o endpoint
    leva esse valor ao corpo da Qualidade —, e documentá-lo aqui faria um
    corpo valer pelas duas alternativas do `oneOf`.
    """
    schema.pop("allOf", None)
    schema.pop("$ref", None)
    schema.update(type="string", enum=[SetorDestinoEnum.TI.value])


def _documentar_proibido(schema: dict) -> None:
    """
    No OpenAPI, campo que não pode ser enviado: `not: {}` recusa qualquer
    valor, inclusive null — como a validação real.
    """
    descricao = schema.get("description")
    schema.clear()
    schema["not"] = {}
    if descricao:
        schema["description"] = descricao


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
        json_schema_extra=_documentar_so_ti,
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
    da descrição e a categoria fica nula. O responsável é opcional (API-14):
    sem ele, ou com `null`, o chamado nasce aguardando atribuição, e a equipe
    da Qualidade o distribui. Se vier — o cliente de antes da API-14 —, passa
    pela regra de elegibilidade no endpoint (`qualidade_service`), como antes.

    `titulo` e `categoria_id` estão declarados só para serem recusados. É a
    presença que conta, não o valor — até `null` é recusado: receber esses
    campos indica um cliente montando o corpo errado, e ignorá-los em silêncio
    esconderia o defeito. O validador só roda quando o campo vem na
    requisição, porque o padrão não é validado.
    """

    setor_destino: Literal[SetorDestinoEnum.QUALIDADE]
    titulo: Optional[Any] = Field(
        None,
        description="Não enviar, nem como null (422): gerado da descrição.",
        json_schema_extra=_documentar_proibido,
    )
    descricao: DescricaoChamado
    categoria_id: Optional[Any] = Field(
        None,
        description="Não enviar, nem como null (422): a Qualidade não usa categoria.",
        json_schema_extra=_documentar_proibido,
    )
    prioridade: PrioridadeEnum = PrioridadeEnum.MEDIA
    solicitante_id: int
    tecnico_responsavel_id: Optional[int] = Field(
        None,
        description=(
            "Opcional: sem ele o chamado nasce aguardando atribuição pela equipe. "
            "Se enviado, um atendente de GET /chamados/atendentes-qualidade."
        ),
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


class ResponsavelTI(BaseModel):
    """Opção do seletor de responsável da TI (API-9): só o necessário para escolher."""

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

    `versao_esperada` não é campo do chamado: o handler a tira do que grava.
    Obrigatória em chamado da Qualidade; na TI, opcional e conferida se vier.
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
    versao_esperada: VersaoEsperada = None


class ChamadoMarca(BaseModel):
    """
    Corpo opcional de PATCH /cancelar, /arquivar e /desarquivar (API-4b).

    As três rotas não tinham corpo, e na TI continuam não precisando: sem
    corpo, ou sem o campo, seguem como antes. Em chamado da Qualidade a versão
    é obrigatória (428). Campo desconhecido é ignorado, como no PUT — o corpo
    era ignorado inteiro até aqui. O motivo do cancelamento continua indo
    pelo PUT (ver `SolucaoChamado`).
    """

    versao_esperada: VersaoEsperada = None


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


class ChamadoAtendimento(BaseModel):
    """
    Corpo do PATCH /chamados/{id}/atendimento, do responsável da Qualidade.

    Pelo mesmo motivo de `ChamadoAvaliacao`, só o que essa pessoa pode mudar:
    o status e a solução. `extra="forbid"` faz qualquer outro campo virar 422
    em vez de ser ignorado — quem manda responsável ou prioridade por aqui
    está tentando o que a rota não faz, e precisa saber.

    Aberto e Fechado não são destinos: nenhuma ação de atendimento leva a
    eles. A transição a partir do status atual é conferida no endpoint, que
    conhece o chamado.

    `versao_esperada` é obrigatória, mas declarada opcional: a falta dela é
    428, decidida no endpoint depois da autorização, e não o 422 que o
    Pydantic daria antes de saber quem pede.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal[StatusEnum.EM_ANDAMENTO, StatusEnum.AGUARDANDO, StatusEnum.RESOLVIDO]
    solucao: Optional[SolucaoChamado] = Field(
        None, description="Obrigatória ao resolver; não enviar nos outros status."
    )
    versao_esperada: VersaoEsperada = None

    @model_validator(mode="after")
    def _solucao_so_ao_resolver(self) -> "ChamadoAtendimento":
        if self.status is StatusEnum.RESOLVIDO:
            if self.solucao is None:
                raise PydanticCustomError("solucao_obrigatoria", "Informe a solução para resolver o chamado")
        elif "solucao" in self.model_fields_set:
            # Até null é recusado: solução fora da resolução é corpo errado.
            raise PydanticCustomError("solucao_nao_se_aplica", "Solução só é enviada ao resolver o chamado")
        return self


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
    # Versão do chamado (API-4a): sobe a cada mudança gravada. É o valor que o
    # cliente devolve em `versao_esperada` na próxima escrita (API-4b).
    versao: int
    sla: Optional[SLAInfo] = None

    model_config = ConfigDict(from_attributes=True)
