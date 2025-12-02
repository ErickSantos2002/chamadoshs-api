from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Setor(Base):
    __tablename__ = "setores"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), unique=True, nullable=False)
    descricao = Column(Text)
    ativo = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # Relationships
    usuarios = relationship("Usuario", back_populates="setor")
