from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "KOLAPSE API"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api/v1"

    # Database
    database_url: str = (
        "postgresql+psycopg://kolapse:kolapse@localhost:5432/kolapse"
    )

    # JWT Authentication
    jwt_secret: str = "CHANGE_ME_BEFORE_DEPLOYMENT"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 1440

    # Google Authentication
    google_client_id: str | None = None

    # Frontend / CORS
    frontend_url: str = "https://kolapse-web-mdp9.vercel.app"
    extra_cors_origins: str = "http://localhost:5173"

    # AI
    ai_api_key: str = "CHANGE_ME_AI_KEY"
    fall_confidence_threshold: float = 0.80
    fall_alert_cooldown_seconds: int = 20

    # Telegram
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        origins = [self.frontend_url]

        origins.extend(
            origin.strip()
            for origin in self.extra_cors_origins.split(",")
            if origin.strip()
        )

        return list(dict.fromkeys(origins))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()