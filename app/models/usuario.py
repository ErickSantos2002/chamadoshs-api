from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False, unique=True)  # Username para login
    senha_hash = Column(String(255))
    setor_id = Column(Integer, ForeignKey("setores.id"))
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    ativo = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    # Relationships
    setor = relationship("Setor", back_populates="usuarios")
    role = relationship("Role", back_populates="usuarios")
    chamados_abertos = relationship("Chamado", foreign_keys="Chamado.solicitante_id", back_populates="solicitante")
    chamados_atribuidos = relationship("Chamado", foreign_keys="Chamado.tecnico_responsavel_id", back_populates="tecnico_responsavel")
    comentarios = relationship("ComentarioChamado", back_populates="usuario")
    historicos = relationship("HistoricoChamado", back_populates="usuario")
    anexos = relationship("Anexo", back_populates="usuario")
