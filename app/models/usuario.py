from sqlalchemy import Column, Integer, String, Boolean, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.utils.timezone import agora_brasilia


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(255), nullable=False, unique=True)  # Username para login
    senha_hash = Column(String(255))
    setor_id = Column(Integer, ForeignKey("setores.id"))
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    ativo = Column(Boolean, default=True)
    # Conta que não representa uma pessoa: painel de parede, integração, login
    # compartilhado. Distinta de `ativo` — estas contas precisam autenticar, e
    # `get_current_user` recusa usuário inativo.
    #
    # server_default além do default: o default do Python só vale para linhas
    # criadas pelo ORM. Sem o server_default, um INSERT por SQL direto (o
    # criar_usuario_inicial.sql, por exemplo) violaria o NOT NULL.
    conta_de_servico = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at = Column(TIMESTAMP, default=agora_brasilia)
    updated_at = Column(TIMESTAMP, default=agora_brasilia, onupdate=agora_brasilia)

    # Relationships
    setor = relationship("Setor", back_populates="usuarios")
    role = relationship("Role", back_populates="usuarios")
    chamados_abertos = relationship("Chamado", foreign_keys="Chamado.solicitante_id", back_populates="solicitante")
    chamados_atribuidos = relationship("Chamado", foreign_keys="Chamado.tecnico_responsavel_id", back_populates="tecnico_responsavel")
    comentarios = relationship("ComentarioChamado", back_populates="usuario")
    historicos = relationship("HistoricoChamado", back_populates="usuario")
    anexos = relationship("Anexo", back_populates="usuario")
