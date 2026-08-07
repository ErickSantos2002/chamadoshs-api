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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

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
