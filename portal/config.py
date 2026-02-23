"""
Portal configuration settings.

All configuration is loaded from environment variables for security.
Use .env file for local development.
"""

import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        # Load the portal-local .env regardless of cwd
        env_file=str(Path(__file__).resolve().parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql://localhost:5432/benchmark",
        description="PostgreSQL connection URL",
    )

    # ClickHouse - Lazer cluster (publisher data)
    clickhouse_lazer_host: str = Field(default="")
    clickhouse_lazer_user: str = Field(default="")
    clickhouse_lazer_password: str = Field(default="")

    # ClickHouse - Analytics cluster (benchmark data)
    clickhouse_analytics_host: str = Field(default="")
    clickhouse_analytics_user: str = Field(default="")
    clickhouse_analytics_password: str = Field(default="")

    # API settings
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    cors_origins: list[str] = Field(default=["*"])
    debug: bool = Field(default=False)

    # Batch processing
    batch_workers: int = Field(
        default=4, description="Parallel workers for batch processing"
    )
    batch_timeout_minutes: int = Field(default=60, description="Max time for batch job")

    # Uptime calculation
    use_uptime_mv: bool = Field(
        default=True,
        description="Use materialized view for uptime calculation (faster)",
    )

    # API authentication (optional)
    require_api_key: bool = Field(
        default=False,
        description="Require API key for authentication",
    )
    api_keys: dict[str, int] = Field(
        default_factory=dict,
        description="API key to publisher_id mapping",
    )
    enforce_api_key_scope: bool = Field(
        default=False,
        description="Enforce that API keys can only access their own publisher data",
    )

    # Paths
    project_root: Path = Field(
        default_factory=lambda: Path(__file__).parent.parent,
        description="Project root directory",
    )

    def get_clickhouse_lazer_config(self) -> dict:
        """Get ClickHouse Lazer config dict for clickhouse_connect."""
        return {
            "host": self.clickhouse_lazer_host,
            "username": self.clickhouse_lazer_user,
            "password": self.clickhouse_lazer_password,
            "secure": True,
            "connect_timeout": 60,
            "send_receive_timeout": 300,
        }

    def get_clickhouse_analytics_config(self) -> dict:
        """Get ClickHouse Analytics config dict for clickhouse_connect."""
        return {
            "host": self.clickhouse_analytics_host,
            "username": self.clickhouse_analytics_user,
            "password": self.clickhouse_analytics_password,
            "secure": True,
            "connect_timeout": 60,
            "send_receive_timeout": 300,
        }


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get settings instance (for dependency injection)."""
    return settings
