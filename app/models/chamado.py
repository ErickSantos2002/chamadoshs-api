from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, Text, CheckConstraint, Boolean, FetchedValue, text
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

    # Setor que atende o chamado: TI ou QUALIDADE. NÃO é o setor de quem abre
    # — esse vem de `usuarios.setor_id`, e um não substitui o outro.
    #
    # server_default além do default, como em `usuarios.conta_de_servico`: o
    # default do Python só vale para linhas criadas pelo ORM, e a API antiga
    # (num rollback de imagem) ou um INSERT por SQL direto não mandam a coluna.
    setor_destino = Column(String(20), nullable=False, default="TI", server_default="TI")

    # Flags de controle
    cancelado = Column(Boolean, default=False, nullable=False)
    arquivado = Column(Boolean, default=False, nullable=False)

    created_at = Column(TIMESTAMP, default=agora_brasilia)
    updated_at = Column(TIMESTAMP, default=agora_brasilia, onupdate=agora_brasilia)

    # Versão do chamado, base do controle otimista (API-4a). Quem a mantém é o
    # trigger_chamados_versao do PostgreSQL — 1 no INSERT, +1 a cada UPDATE que
    # muda algum dado persistido (ver migrations/2026-10-28-add-versao-chamados.sql).
    # O ORM não a incrementa: sem `onupdate` e sem `version_id_col`.
    #
    # `server_onupdate=FetchedValue()` não gera valor nenhum: só avisa o ORM de
    # que o banco muda a coluna no UPDATE, e ela expira depois de cada flush.
    # Sem isso, o objeto em memória seguiria com a versão de antes do UPDATE
    # até alguém relê-lo. No SQLite dos testes não há trigger, e a versão fica
    # em 1 — o que lá se prova é o contrato, não a contagem.
    versao = Column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
        server_onupdate=FetchedValue(),
    )

    # Constraints
    __table_args__ = (
        CheckConstraint("prioridade IN ('Baixa', 'Média', 'Alta', 'Crítica')", name='chk_prioridade'),
        CheckConstraint("urgencia IS NULL OR urgencia IN ('Não Urgente', 'Normal', 'Urgente', 'Muito Urgente')", name='chk_urgencia'),
        CheckConstraint("status IN ('Aberto', 'Em Andamento', 'Aguardando', 'Resolvido', 'Fechado')", name='chk_status'),
        CheckConstraint("setor_destino IN ('TI', 'QUALIDADE')", name='chk_setor_destino'),
        CheckConstraint("versao >= 1", name='chk_chamados_versao'),
    )

    # Relationships
    solicitante = relationship("Usuario", foreign_keys=[solicitante_id], back_populates="chamados_abertos")
    tecnico_responsavel = relationship("Usuario", foreign_keys=[tecnico_responsavel_id], back_populates="chamados_atribuidos")
    categoria = relationship("Categoria", back_populates="chamados")
    comentarios = relationship("ComentarioChamado", back_populates="chamado", cascade="all, delete-orphan")
    historicos = relationship("HistoricoChamado", back_populates="chamado", cascade="all, delete-orphan")
    anexos = relationship("Anexo", back_populates="chamado", cascade="all, delete-orphan")
