from sqlalchemy import Column, Integer, String, ForeignKey, Text, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class HistoricoChamado(Base):
    __tablename__ = "historico_chamados"

    id = Column(Integer, primary_key=True, index=True)
    chamado_id = Column(Integer, ForeignKey("chamados.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    acao = Column(String(100), nullable=False)
    descricao = Column(Text)
    status_anterior = Column(String(50))
    status_novo = Column(String(50))
    created_at = Column(TIMESTAMP, server_default=func.now())

    # Relationships
    chamado = relationship("Chamado", back_populates="historicos")
    usuario = relationship("Usuario", back_populates="historicos")
