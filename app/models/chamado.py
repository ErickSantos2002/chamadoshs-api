from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, Text, CheckConstraint, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.utils.timezone import agora_brasilia


class Chamado(Base):
    __tablename__ = "chamados"

    id = Column(Integer, primary_key=True, index=True)
    protocolo = Column(String(50), unique=True, nullable=False)

    # Quem e quando
    solicitante_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    data_abertura = Column(TIMESTAMP, default=agora_brasilia)
    data_atualizacao = Column(TIMESTAMP, default=agora_brasilia, onupdate=agora_brasilia)
    data_resolucao = Column(TIMESTAMP, nullable=True)

    # O que
    categoria_id = Column(Integer, ForeignKey("categorias.id"))
    titulo = Column(String(255), nullable=False)
    descricao = Column(Text, nullable=False)

    # Prioridade, Urgência e Status
    prioridade = Column(String(20), default='Média')
    urgencia = Column(String(20), nullable=True)  # Definido por técnicos
    status = Column(String(50), default='Aberto')

    # Atendimento
    tecnico_responsavel_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    solucao = Column(Text)
    tempo_resolucao_minutos = Column(Integer)

    # Observações e Avaliação
    observacoes = Column(Text)
    avaliacao = Column(Integer, CheckConstraint('avaliacao >= 1 AND avaliacao <= 5'))

    # Flags de controle
    cancelado = Column(Boolean, default=False, nullable=False)
    arquivado = Column(Boolean, default=False, nullable=False)

    created_at = Column(TIMESTAMP, default=agora_brasilia)
    updated_at = Column(TIMESTAMP, default=agora_brasilia, onupdate=agora_brasilia)

    # Constraints
    __table_args__ = (
        CheckConstraint("prioridade IN ('Baixa', 'Média', 'Alta', 'Crítica')", name='chk_prioridade'),
        CheckConstraint("urgencia IS NULL OR urgencia IN ('Não Urgente', 'Normal', 'Urgente', 'Muito Urgente')", name='chk_urgencia'),
        CheckConstraint("status IN ('Aberto', 'Em Andamento', 'Aguardando', 'Resolvido', 'Fechado')", name='chk_status'),
    )

    # Relationships
    solicitante = relationship("Usuario", foreign_keys=[solicitante_id], back_populates="chamados_abertos")
    tecnico_responsavel = relationship("Usuario", foreign_keys=[tecnico_responsavel_id], back_populates="chamados_atribuidos")
    categoria = relationship("Categoria", back_populates="chamados")
    comentarios = relationship("ComentarioChamado", back_populates="chamado", cascade="all, delete-orphan")
    historicos = relationship("HistoricoChamado", back_populates="chamado", cascade="all, delete-orphan")
    anexos = relationship("Anexo", back_populates="chamado", cascade="all, delete-orphan")
