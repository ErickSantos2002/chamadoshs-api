import logging
import re

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings
from typing import FrozenSet, List, NamedTuple, Optional

logger = logging.getLogger(__name__)


class SetoresTI(NamedTuple):
    """
    `SETORES_TI_IDS` interpretada. `estado` é um de:

    - "ausente": variável não definida;
    - "vazia": definida sem nenhum id;
    - "valida": todos os itens são ids;
    - "invalida": algum item não é id — a lista inteira é descartada.

    Fora de "valida", `ids` é vazio: nenhum setor vale como TI.
    """

    estado: str
    ids: FrozenSet[int]
    duplicados: bool = False


# [0-9], e não \d: \d aceita dígitos de outros alfabetos, que int() converte.
_ID_DE_SETOR = re.compile(r"[0-9]+")


def interpretar_setores_ti(valor: Optional[str]) -> SetoresTI:
    """
    Lê `SETORES_TI_IDS`: ids inteiros positivos separados por vírgula.

    Um item inválido descarta a lista inteira, em vez de aproveitar os
    válidos: "1,2O" com a letra no lugar do zero deixaria o setor 20 de fora
    sem ninguém perceber, e quem confere a configuração precisa ver que ela
    está quebrada, não meio aplicada. Repetidos são juntados.
    """
    if valor is None:
        return SetoresTI("ausente", frozenset())
    texto = str(valor).strip()
    if not texto:
        return SetoresTI("vazia", frozenset())
    itens = [item.strip() for item in texto.split(",")]
    if not all(_ID_DE_SETOR.fullmatch(item) and int(item) > 0 for item in itens):
        return SetoresTI("invalida", frozenset())
    numeros = [int(item) for item in itens]
    return SetoresTI("valida", frozenset(numeros), duplicados=len(set(numeros)) != len(numeros))


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # API
    API_VERSION: str = "v1"
    API_TITLE: str = "ChamadosHS API"
    API_DESCRIPTION: str = "API de gerenciamento de chamados de suporte técnico"

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    # 8 horas: cobre um turno de trabalho. Era 30 minutos, o que passava
    # despercebido enquanto quase nenhuma rota validava o token — a partir do
    # momento em que toda a API exige token, 30 minutos desconectaria o
    # usuário no meio do expediente.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # Rate limiting do login
    # Contam apenas tentativas FALHAS; um login bem-sucedido zera as duas
    # contagens. O limite por usuário é o que resiste a ataque distribuído,
    # já que o IP pode ser trocado; o limite por IP contém varredura de
    # vários usuários a partir de uma origem só.
    #
    # O limite por IP é folgado de propósito: num escritório atrás de um único
    # IP público (NAT), todas as pessoas compartilham a mesma contagem, e um
    # valor apertado derrubaria o time inteiro numa manhã de segunda. Se o
    # acesso for só de dentro da rede da empresa, considere aumentar mais.
    LOGIN_MAX_FALHAS_POR_USUARIO: int = 10
    LOGIN_MAX_FALHAS_POR_IP: int = 50
    LOGIN_JANELA_SEGUNDOS: int = 900  # 15 minutos

    # Quantos proxies confiáveis existem na frente da aplicação.
    #
    # Cada proxy acrescenta o IP que enxergou ao fim de X-Forwarded-For, então
    # o IP real do cliente é o N-ésimo a contar do fim, com N = número de
    # proxies. Ler o PRIMEIRO elemento seria um erro: aquele valor vem do
    # cliente e é falsificável, o que permitiria furar o limite por IP à
    # vontade. Com 0, o header é ignorado e vale o IP da conexão.
    PROXY_HOPS_CONFIAVEIS: int = 1

    # Webhook de notificação de técnico (n8n).
    # Vazio desliga o envio: é o padrão para que desenvolvimento e testes não
    # disparem notificação no fluxo de produção por descuido.
    WEBHOOK_TECNICO_URL: str = ""
    WEBHOOK_TIMEOUT_SEGUNDOS: int = 5

    # Segredo compartilhado com o nó Webhook do n8n (Header Auth).
    #
    # Sem ele, a URL é a única credencial: quem descobre o endereço dispara o
    # fluxo. Com ele, o n8n recusa qualquer requisição que não traga o header.
    #
    # Vazio = header não é enviado. Isso é proposital e é o que permite subir
    # o backend ANTES de ligar o Header Auth no n8n, sem janela de falha:
    # enquanto o n8n estiver em Authentication None, um header a mais é
    # simplesmente ignorado. Ligue o n8n só depois que a variável estiver
    # configurada e o container reiniciado.
    WEBHOOK_TECNICO_TOKEN: str = ""
    WEBHOOK_TECNICO_HEADER: str = "X-Webhook-Token"

    # Setor que atende os chamados de destino QUALIDADE (id em `setores`).
    #
    # Por ambiente, e nunca fixo no código: o id da Qualidade em produção não é
    # o mesmo da homologação, e nome não serve — setor é renomeável.
    #
    # Sem valor, a abertura para a Qualidade fica fechada (503) e a TI segue
    # normal. Valor vazio ou inválido vale como sem valor, em vez de impedir a
    # API de subir: um erro de digitação aqui não pode tirar do ar a abertura
    # de chamados da TI. O aviso vai para o log.
    SETOR_QUALIDADE_ID: Optional[int] = None

    @field_validator("SETOR_QUALIDADE_ID", mode="before")
    @classmethod
    def _setor_qualidade_id(cls, valor):
        if valor is None:
            return None
        texto = str(valor).strip()
        if not texto:
            return None
        try:
            numero = int(texto)
        except ValueError:
            numero = 0
        if numero <= 0:
            logger.warning(
                "SETOR_QUALIDADE_ID=%r não é um id válido; abertura para a Qualidade desligada",
                valor,
            )
            return None
        return numero

    # Setores da equipe de TI (ids em `setores`), separados por vírgula: "1"
    # ou "1,7". É o que faz um técnico ser da TI (API-6, D10): ler os chamados
    # da TI e da Qualidade, alterá-los e ser responsável por chamado da TI.
    #
    # Sem valor padrão, e sem exemplo: os ids mudam por ambiente e só quem
    # confere o cadastro real pode dizê-los (ver os SELECTs do CHANGELOG).
    # Nome de setor não serve, pelo mesmo motivo de SETOR_QUALIDADE_ID.
    #
    # Ausente, vazia ou inválida, nenhum setor é da TI: técnico nenhum tem
    # alcance de TI, e cada um fica só com o vínculo direto (o que abriu e o
    # que atende). A API sobe assim mesmo — login, abertura de chamado e a
    # Qualidade não dependem disto — e o aviso vai para o log. O id da
    # Qualidade nunca vale como TI, mesmo que esteja na lista.
    #
    # Texto cru, e não lista: o pydantic-settings desta versão lê lista do
    # ambiente como JSON, e "1,7" derrubaria a API na subida.
    SETORES_TI_IDS: Optional[str] = None

    @property
    def setores_ti(self) -> SetoresTI:
        return interpretar_setores_ti(self.SETORES_TI_IDS)

    @property
    def setores_ti_ids(self) -> FrozenSet[int]:
        """Os setores que valem como TI agora, já sem o da Qualidade."""
        ids = self.setores_ti.ids
        if self.SETOR_QUALIDADE_ID is not None:
            ids = ids - {self.SETOR_QUALIDADE_ID}
        return ids

    @model_validator(mode="after")
    def _avisar_setores_ti(self):
        # Só avisa: a regra é aplicada em `setores_ti_ids`, a cada leitura.
        # Lido uma vez, na subida, que é quando quem configura olha o log.
        lidos = self.setores_ti
        if lidos.estado == "ausente":
            logger.warning(
                "SETORES_TI_IDS não definida: nenhum técnico tem alcance de TI "
                "(leitura e alteração só pelo vínculo direto)"
            )
        elif lidos.estado == "vazia":
            logger.warning("SETORES_TI_IDS vazia: nenhum técnico tem alcance de TI")
        elif lidos.estado == "invalida":
            logger.warning(
                "SETORES_TI_IDS=%r não é uma lista de ids; nenhum técnico tem alcance de TI",
                self.SETORES_TI_IDS,
            )
        else:
            if lidos.duplicados:
                logger.warning("SETORES_TI_IDS tem ids repetidos; cada um vale uma vez")
            if self.SETOR_QUALIDADE_ID is not None and self.SETOR_QUALIDADE_ID in lidos.ids:
                logger.warning(
                    "SETORES_TI_IDS inclui o setor da Qualidade (%s); ele não vale como TI",
                    self.SETOR_QUALIDADE_ID,
                )
        return self

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    # Environment
    # Padrão "production" de propósito: se a variável não for definida no
    # EasyPanel, o comportamento seguro é o que vale. O .env.example já traz
    # ENVIRONMENT=development para o ambiente local.
    ENVIRONMENT: str = "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.strip().casefold() == "development"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
