from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    descricao = Column(Text)
    ativo = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # Relationships
    chamados = relationship("Chamado", back_populates="categoria")
