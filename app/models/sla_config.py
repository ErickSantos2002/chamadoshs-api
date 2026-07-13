from sqlalchemy import Column, Integer, String

from app.core.database import Base


class SLAConfig(Base):
    """Prazos de SLA por prioridade, em minutos úteis."""
    __tablename__ = "sla_configs"

    prioridade = Column(String(20), primary_key=True)
    minutos_resposta = Column(Integer, nullable=False)
    minutos_resolucao = Column(Integer, nullable=False)
