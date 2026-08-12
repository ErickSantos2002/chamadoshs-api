from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.utils.timezone import agora_brasilia


class EventoDeConta(Base):
    """
    Trilha de auditoria do cadastro de usuários: quem fez o quê com qual
    conta, e quando.

    Por que não cabe em `historico_chamados`: lá `chamado_id` é NOT NULL e a FK
    é `ON DELETE CASCADE`. A tabela é escopada por chamado — evento de usuário
    não tem chamado, e o pouco que coubesse desapareceria junto com o chamado.
    `usuarios.updated_at` também não resolve: é sobrescrito por qualquer edição
    e não guarda autor.

    ATOR e ALVO são colunas separadas porque "o usuário X foi desativado" sem
    dizer por quem não serve de evidência. As duas apontam para `usuarios` e
    **nenhuma declara ON DELETE**: no PostgreSQL isso é NO ACTION, então apagar
    uma conta que aparece na trilha é recusado pelo banco. É o comportamento
    desejado — a trilha não pode sumir justamente no caso em que ela importa.

    Cada linha é UMA mudança, com o valor anterior e o novo em texto legível
    (nome do perfil, nome do setor, `true`/`false`). Guardar o de/para é o que
    permite reconstruir a história depois: um evento que dissesse apenas
    "perfil alterado" viraria ruído na segunda alteração. A leitura é do
    presente para trás — estado atual da conta, e os eventos desfazendo passo a
    passo.

    `valor_anterior`/`valor_novo` nunca recebem senha nem hash: a alteração de
    senha é registrada como evento sem valores. Ver
    `app/services/evento_conta_service.py`, que é o único lugar que escreve
    aqui e onde mora o vocabulário de `acao`.
    """

    __tablename__ = "eventos_de_conta"

    id = Column(Integer, primary_key=True, index=True)
    # Alvo: a conta que sofreu a mudança.
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Ator: quem estava autenticado e fez a mudança. NOT NULL porque hoje todo
    # caminho que altera cadastro exige token. Automação futura age por uma
    # conta de serviço (`usuarios.conta_de_servico`), que também é uma linha em
    # `usuarios` — não há caso legítimo de evento sem autor.
    ator_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    acao = Column(String(50), nullable=False)
    valor_anterior = Column(String(255))
    valor_novo = Column(String(255))
    # Rota que gravou o evento, como template ("PUT /api/v1/usuarios/{id}").
    # Enquanto o DELETE e os PATCH do passo seguinte convivem, é por aqui que
    # se mede o que o frontend ainda usa.
    origem = Column(String(60))
    created_at = Column(TIMESTAMP, default=agora_brasilia)

    # foreign_keys explícito nos dois lados: com duas FKs para a mesma tabela,
    # o SQLAlchemy não tem como adivinhar qual relacionamento usa qual coluna.
    usuario = relationship(
        "Usuario", foreign_keys=[usuario_id], back_populates="eventos_de_conta"
    )
    ator = relationship(
        "Usuario", foreign_keys=[ator_id], back_populates="eventos_praticados"
    )
