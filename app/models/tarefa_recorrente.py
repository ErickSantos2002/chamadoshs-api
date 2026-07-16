from sqlalchemy import (
    Column, Integer, SmallInteger, String, Text, Boolean, TIMESTAMP, Date,
    ForeignKey, CheckConstraint,
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.utils.timezone import agora_brasilia


class TarefaRecorrente(Base):
    __tablename__ = "tarefas_recorrentes"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(255), nullable=False)
    descricao = Column(Text)
    instrucoes = Column(Text)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    responsavel_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    prioridade = Column(String(20), nullable=False, default="Média")
    tipo_recorrencia = Column(String(10), nullable=False)  # diaria | semanal | mensal
    intervalo = Column(Integer, nullable=False, default=1)  # a cada N dias/semanas/meses
    dia_semana = Column(SmallInteger, nullable=True)  # 0=Dom..6=Sáb (semanal)
    dia_mes = Column(SmallInteger, nullable=True)     # 1..31 (mensal)
    proxima_data = Column(Date, nullable=False)
    ativo = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP, default=agora_brasilia)
    updated_at = Column(TIMESTAMP, default=agora_brasilia, onupdate=agora_brasilia)

    __table_args__ = (
        CheckConstraint(
            "prioridade IN ('Baixa','Média','Alta','Crítica')", name="chk_tr_prioridade"
        ),
        CheckConstraint(
            "tipo_recorrencia IN ('diaria','semanal','mensal')", name="chk_tr_tipo"
        ),
    )

    categoria = relationship("Categoria")
    responsavel = relationship("Usuario", foreign_keys=[responsavel_id])
    execucoes = relationship(
        "TarefaRecorrenteExecucao",
        back_populates="tarefa",
        cascade="all, delete-orphan",
        order_by="desc(TarefaRecorrenteExecucao.realizada_em)",
    )


class TarefaRecorrenteExecucao(Base):
    __tablename__ = "tarefas_recorrentes_execucoes"

    id = Column(Integer, primary_key=True, index=True)
    tarefa_id = Column(
        Integer,
        ForeignKey("tarefas_recorrentes.id", ondelete="CASCADE"),
        nullable=False,
    )
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    data_prevista = Column(Date, nullable=True)
    realizada_em = Column(TIMESTAMP, default=agora_brasilia)
    observacao = Column(Text)
    created_at = Column(TIMESTAMP, default=agora_brasilia)

    tarefa = relationship("TarefaRecorrente", back_populates="execucoes")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
