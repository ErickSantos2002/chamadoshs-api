from sqlalchemy import Column, Integer, String, TIMESTAMP, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(50), unique=True, nullable=False)
    descricao = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

    # Relationships
    usuarios = relationship("Usuario", back_populates="role")
