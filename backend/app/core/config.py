from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All the env vars live here. pydantic-settings reads them from .env."""

    database_url: str = "postgresql+asyncpg://pushtalk:pushtalk@db:5432/pushtalk"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    media_root: str = "/media"
    max_audio_mb: int = 10
    min_audio_seconds: float = 0.5
    max_audio_seconds: float = 60
    cors_origins: str = "http://localhost:5173"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()