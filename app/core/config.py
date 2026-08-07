from pydantic_settings import BaseSettings
from typing import List


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
