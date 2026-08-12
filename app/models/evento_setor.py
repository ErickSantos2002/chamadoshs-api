from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.utils.timezone import agora_brasilia


class EventoDeSetor(Base):
    """
    Trilha de auditoria do cadastro de setores: irmã de `eventos_de_conta`, com
    uma diferença que é a razão de ela existir separada.

    Em `eventos_de_conta` o alvo é uma FK sem ON DELETE, e isso é proposital:
    apagar uma conta que aparece na trilha passa a ser recusado pelo banco. Para
    setor esse mesmo desenho seria uma armadilha — setor vai virar apagável de
    verdade (hard delete com checagem, como categorias), e uma FK aqui
    bloquearia justamente a exclusão que o produto quer permitir. O evento
    sobreviveria ao setor apenas para impedi-lo de sumir.

    Então o alvo aqui é `setor_id` SEM FK, acompanhado de `setor_nome`
    congelado no momento do evento. O par resolve as duas pontas: o id continua
    ligando os eventos do mesmo setor entre si (mesmo depois de a linha em
    `setores` não existir mais), e o nome diz que setor era aquele sem depender
    de uma consulta que devolveria o presente — ou nada.

    O ator continua com FK para `usuarios`, e sem ON DELETE, pelo mesmo motivo
    de `eventos_de_conta`: quem agiu não pode evaporar da trilha. Não há
    conflito com o hard delete, porque quem se apaga aqui é o setor, não a
    conta.

    O vocabulário de `acao` mora em `app/services/evento_setor_service.py`,
    único lugar do código que escreve nesta tabela.
    """

    __tablename__ = "eventos_de_setor"

    id = Column(Integer, primary_key=True, index=True)
    # Alvo. Sem ForeignKey de propósito — ver a docstring da classe. Continua
    # NOT NULL: evento de setor nenhum não é evento de coisa alguma.
    setor_id = Column(Integer, nullable=False)
    # Nome do setor quando o evento aconteceu. Renomear o setor depois não
    # reescreve a história, e apagá-lo não apaga o que ele era.
    setor_nome = Column(String(100), nullable=False)
    ator_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    acao = Column(String(50), nullable=False)
    valor_anterior = Column(String(255))
    valor_novo = Column(String(255))
    # Rota que gravou o evento, como template ("PATCH /api/v1/setores/{id}/desativar").
    # Enquanto o DELETE e os PATCH convivem, é por aqui que se mede o que o
    # frontend ainda usa.
    origem = Column(String(60))
    created_at = Column(TIMESTAMP, default=agora_brasilia)

    ator = relationship("Usuario", foreign_keys=[ator_id])
