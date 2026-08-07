"""
Limitador de tentativas por janela deslizante.

Usado para conter força bruta no login. Guarda estado **em memória e por
processo**: não sobrevive a restart do container e não é compartilhado entre
workers. Com o `CMD` atual do Dockerfile (uvicorn sem `--workers`) há um único
processo, então a contagem é exata. Se um dia forem N workers, cada um passa a
ter sua própria contagem e o limite efetivo vira N vezes o configurado — nesse
caso troque o armazenamento por Redis.
"""

import threading
import time
from collections import OrderedDict, deque
from typing import Deque, Hashable, Optional

# Teto de chaves distintas mantidas simultaneamente. Sem isso, um ataque que
# varia o usuário a cada tentativa faria o próprio limitador consumir memória
# sem limite — a proteção viraria o problema.
MAX_CHAVES = 10_000


class JanelaDeslizante:
    """
    Conta eventos por chave dentro de uma janela de tempo que anda junto com o
    relógio. Diferente de um contador que zera de tempos em tempos, aqui não
    existe a virada em que o atacante recupera todo o orçamento de uma vez.
    """

    def __init__(self, max_eventos: int, janela_segundos: int, max_chaves: int = MAX_CHAVES):
        if max_eventos < 1:
            raise ValueError("max_eventos deve ser >= 1")
        if janela_segundos < 1:
            raise ValueError("janela_segundos deve ser >= 1")

        self.max_eventos = max_eventos
        self.janela_segundos = janela_segundos
        self.max_chaves = max_chaves

        # OrderedDict para poder descartar a chave usada há mais tempo quando
        # o teto é atingido.
        self._eventos: "OrderedDict[Hashable, Deque[float]]" = OrderedDict()
        # O endpoint de login é `def`, não `async def`: o FastAPI o executa num
        # threadpool, então há concorrência real sobre esta estrutura.
        self._lock = threading.Lock()

    def _expirar(self, marcas: Deque[float], agora: float) -> None:
        limite = agora - self.janela_segundos
        while marcas and marcas[0] <= limite:
            marcas.popleft()

    def segundos_ate_liberar(self, chave: Hashable, agora: Optional[float] = None) -> int:
        """
        Zero se a chave ainda pode tentar. Caso contrário, quantos segundos
        faltam para a tentativa mais antiga sair da janela.
        """
        agora = time.monotonic() if agora is None else agora

        with self._lock:
            marcas = self._eventos.get(chave)
            if marcas is None:
                return 0

            self._expirar(marcas, agora)
            if not marcas:
                del self._eventos[chave]
                return 0

            if len(marcas) < self.max_eventos:
                return 0

            restante = self.janela_segundos - (agora - marcas[0])
            return max(1, int(restante) + 1)

    def registrar(self, chave: Hashable, agora: Optional[float] = None) -> None:
        """Contabiliza uma tentativa falha."""
        agora = time.monotonic() if agora is None else agora

        with self._lock:
            marcas = self._eventos.get(chave)
            if marcas is None:
                marcas = deque()
                self._eventos[chave] = marcas

            self._expirar(marcas, agora)
            marcas.append(agora)
            self._eventos.move_to_end(chave)

            while len(self._eventos) > self.max_chaves:
                self._eventos.popitem(last=False)

    def limpar(self, chave: Hashable) -> None:
        """Zera a contagem da chave. Chamado quando o login dá certo."""
        with self._lock:
            self._eventos.pop(chave, None)

    def reset(self) -> None:
        """Descarta todo o estado. Existe para os testes."""
        with self._lock:
            self._eventos.clear()
