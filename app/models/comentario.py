from sqlalchemy import Column, Integer, ForeignKey, Text, Boolean, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.utils.timezone import agora_brasilia


class ComentarioChamado(Base):
    __tablename__ = "comentarios_chamados"

    id = Column(Integer, primary_key=True, index=True)
    chamado_id = Column(Integer, ForeignKey("chamados.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    comentario = Column(Text, nullable=False)
    is_interno = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP, default=agora_brasilia)
    updated_at = Column(TIMESTAMP, default=agora_brasilia, onupdate=agora_brasilia)

    # Relationships
    chamado = relationship("Chamado", back_populates="comentarios")
    usuario = relationship("Usuario", back_populates="comentarios")
