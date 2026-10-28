"""
Pré-condição de versão nas escritas de chamado (API-4b).

O cliente manda em `versao_esperada` a versão do chamado em que baseou a
escrita — a que ele leu na última resposta. Se o chamado mudou desde então, a
escrita é recusada inteira, em vez de sobrescrever o que outra pessoa gravou.

A versão em si é do banco: o `trigger_chamados_versao` (API-4a) a incrementa,
e nada aqui a escreve. `versao_esperada` é só pré-condição.

As duas recusas são `HTTPException`, e não exceções de domínio como as de
`qualidade_service`, para não repetir a tradução em cada rota. O 409 de versão
tem handler próprio em `main.py`, que põe `codigo` e `versao_atual` ao lado do
`detail`; os outros 409 da API seguem com o formato de sempre.
"""

from typing import Optional

from fastapi import HTTPException, status

from app.models.chamado import Chamado

VERSAO_AUSENTE = "Informe a versão do chamado"
VERSAO_DESATUALIZADA = "Este chamado foi alterado por outra pessoa. Atualize e tente de novo."
CODIGO_VERSAO_DESATUALIZADA = "versao_desatualizada"


class VersaoAusente(HTTPException):
    """428: a escrita exige `versao_esperada`, e ela não veio."""

    def __init__(self):
        super().__init__(status_code=status.HTTP_428_PRECONDITION_REQUIRED, detail=VERSAO_AUSENTE)


class VersaoDesatualizada(HTTPException):
    """
    409: o chamado mudou desde a leitura do cliente.

    Sem o handler de `main.py` cairia no handler padrão e sairia só com o
    `detail` — ainda 409, ainda sem gravar nada, mas sem `versao_atual`.
    """

    def __init__(self, versao_atual: int):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=VERSAO_DESATUALIZADA)
        self.versao_atual = versao_atual

    def corpo(self) -> dict:
        return {
            "detail": self.detail,
            "codigo": CODIGO_VERSAO_DESATUALIZADA,
            "versao_atual": self.versao_atual,
        }


def conferir_versao(chamado: Chamado, esperada: Optional[int], obrigatoria: bool) -> None:
    """
    Recusa a escrita se a versão não veio (quando obrigatória) ou não bate.

    Só vale como controle de concorrência se `chamado` foi lido com a linha
    travada (`FOR UPDATE`) e a escrita sai na mesma transação: sem o lock, outra
    escrita pode entrar entre esta conferência e o UPDATE. Chamar depois da
    autorização — o 409 diz a versão atual, e quem não pode escrever no chamado
    não tem por que sabê-la.

    Não grava, não faz commit e não toca em `chamado.versao`.
    """
    if esperada is None:
        if obrigatoria:
            raise VersaoAusente()
        return
    if esperada != chamado.versao:
        raise VersaoDesatualizada(chamado.versao)
