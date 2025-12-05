from sqlalchemy import Column, Integer, String, ForeignKey, TIMESTAMP
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.utils.timezone import agora_brasilia


class Anexo(Base):
    __tablename__ = "anexos"

    id = Column(Integer, primary_key=True, index=True)
    chamado_id = Column(Integer, ForeignKey("chamados.id", ondelete="CASCADE"), nullable=False)
    nome_arquivo = Column(String(255), nullable=False)
    caminho = Column(String(500), nullable=False)
    tamanho_kb = Column(Integer)
    tipo_mime = Column(String(100))
    uploaded_by = Column(Integer, ForeignKey("usuarios.id"))
    created_at = Column(TIMESTAMP, default=agora_brasilia)

    # Relationships
    chamado = relationship("Chamado", back_populates="anexos")
    usuario = relationship("Usuario", back_populates="anexos")
