from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, Literal
from datetime import date, datetime

TipoRecorrencia = Literal["diaria", "semanal", "mensal"]
Prioridade = Literal["Baixa", "Média", "Alta", "Crítica"]


class TarefaRecorrenteBase(BaseModel):
    titulo: str
    descricao: Optional[str] = None
    instrucoes: Optional[str] = None
    categoria_id: Optional[int] = None
    responsavel_id: Optional[int] = None
    prioridade: Prioridade = "Média"
    tipo_recorrencia: TipoRecorrencia
    intervalo: int = 1
    dia_semana: Optional[int] = None  # 0=Dom..6=Sáb
    dia_mes: Optional[int] = None     # 1..31

    @field_validator("intervalo")
    @classmethod
    def intervalo_min(cls, v: int) -> int:
        return max(1, v)


class TarefaRecorrenteCreate(TarefaRecorrenteBase):
    # Opcional: se ausente, o backend calcula a 1ª data a partir de hoje.
    proxima_data: Optional[date] = None


class TarefaRecorrenteUpdate(BaseModel):
    titulo: Optional[str] = None
    descricao: Optional[str] = None
    instrucoes: Optional[str] = None
    categoria_id: Optional[int] = None
    responsavel_id: Optional[int] = None
    prioridade: Optional[Prioridade] = None
    tipo_recorrencia: Optional[TipoRecorrencia] = None
    intervalo: Optional[int] = None
    dia_semana: Optional[int] = None
    dia_mes: Optional[int] = None
    proxima_data: Optional[date] = None
    ativo: Optional[bool] = None


class ExecucaoResponse(BaseModel):
    id: int
    tarefa_id: int
    usuario_id: int
    usuario_nome: Optional[str] = None
    data_prevista: Optional[date] = None
    realizada_em: datetime
    observacao: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TarefaRecorrenteResponse(TarefaRecorrenteBase):
    id: int
    proxima_data: date
    ativo: bool
    total_execucoes: int = 0
    categoria_nome: Optional[str] = None
    responsavel_nome: Optional[str] = None
    ultima_execucao: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RealizarTarefaRequest(BaseModel):
    usuario_id: int
    observacao: Optional[str] = None
