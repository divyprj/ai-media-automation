"""Application configuration management using Pydantic Settings."""

from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration settings loaded from environment or .env file."""

    owner_name: str = "Divyansh Prajapati"
    owner_handle: str = "@divyprjai"
    database_url: str = "data/ai_media.db"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "r1:latest"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    x_api_key: Optional[str] = None
    x_api_secret: Optional[str] = None
    x_access_token: Optional[str] = None
    x_access_secret: Optional[str] = None
    log_level: str = "INFO"
    enable_emergency_shutoff: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached instance of application settings."""
    return Settings()
