"""
core/config.py — Application configuration loaded from environment variables.
All services import Settings from here; never read os.environ directly elsewhere.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://minipay:minipay@localhost:5432/minipay"

    # ── API ───────────────────────────────────────────────────────────────────
    api_key: str = "dev-key-change-me"
    api_base_url: str = "http://localhost:8000"

    # ── MQTT ──────────────────────────────────────────────────────────────────
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883

    # ── Ingestion ─────────────────────────────────────────────────────────────
    ingestion_workers: int = 4
    ingestion_queue_size: int = 1000

    # ── Webhook worker ────────────────────────────────────────────────────────
    webhook_workers: int = 8
    webhook_poll_interval_s: float = 1.0
    webhook_max_attempts: int = 6
    webhook_timeout_s: float = 5.0

    # ── Acquirer (mock) ───────────────────────────────────────────────────────
    acquirer: str = "mock"
    mock_acquirer_failure_rate: float = 0.0

    # ── Simulator ─────────────────────────────────────────────────────────────
    sim_terminals: int = 5
    sim_rate_per_terminal: float = 1.0  # events/second per terminal

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"


# Module-level singleton — import `settings` everywhere.
settings = Settings()
