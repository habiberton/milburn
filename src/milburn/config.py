from pathlib import Path
from typing import Optional

from langchain_protocol import Literal
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Settings for the Milburn agent.
    """
    model_config = SettingsConfigDict(
        env_prefix="MILBURN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # Agent configuration
    agent_name: str = "Milburn"
    agent_role: str = "An AI assistant that helps users with various tasks."

    # API configurations
    tiingo_api_secret: SecretStr | None

    def get_tiingo_api_key(self) -> Optional[str]:
        if self.tiingo_api_secret is not None:
            return self.tiingo_api_secret.get_secret_value()
        return None

    # Data
    data_dir: Path = Path("data")
    cache_dir: Path = Path("data/cache")
    fixtures_dir: Path = Path("data/fixtures")
    runs_dir: Path = Path("runs")

    # LLM
    ollama_base_url: str = "http://localhost:11434"
    default_model_profile: str = "default"

    # Logging configuration
    log_level: str = "INFO"
    log_file: Optional[str] = None
    log_format: Literal["console", "json"] = "console"

    # OpenTelemetry configuration
    enable_otel: bool = False
    otel_service_name: str = "milburn"
    otel_exporter_otlp_endpoint: str | None = None

    # Other configurations
    max_response_length: int = 2048