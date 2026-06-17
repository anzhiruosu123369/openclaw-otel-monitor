"""Configuration management."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import tomli


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass
class OpenClawConfig:
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 18789
    openclaw_root: str = "~/.openclaw"


@dataclass
class CollectorConfig:
    session_scan_interval: int = 5
    health_check_interval: int = 10


@dataclass
class StorageConfig:
    metrics_db: str = "~/.local/share/openclaw-otel-monitor/metrics.db"
    retention_days: int = 7


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    openclaw: OpenClawConfig = field(default_factory=OpenClawConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        """Load configuration from file or use defaults."""
        if path is None:
            # Default config path
            path = os.path.expanduser("~/.config/openclaw-otel-monitor/config.toml")

        if not os.path.exists(path):
            return cls()

        with open(path, "rb") as f:
            data = tomli.load(f)

        config = cls()

        if "server" in data:
            config.server = ServerConfig(**data["server"])
        if "openclaw" in data:
            config.openclaw = OpenClawConfig(
                gateway_host=data["openclaw"].get("gateway_host", config.openclaw.gateway_host),
                gateway_port=data["openclaw"].get("gateway_port", config.openclaw.gateway_port),
                openclaw_root=data["openclaw"].get("openclaw_root", config.openclaw.openclaw_root),
            )
        if "collector" in data:
            config.collector = CollectorConfig(**data["collector"])
        if "storage" in data:
            config.storage = StorageConfig(**data["storage"])
        if "logging" in data:
            config.logging = LoggingConfig(**data["logging"])

        return config

    @property
    def gateway_url(self) -> str:
        return f"http://{self.openclaw.gateway_host}:{self.openclaw.gateway_port}"

    @property
    def openclaw_root_path(self) -> Path:
        return Path(self.openclaw.openclaw_root).expanduser()

    @property
    def metrics_db_path(self) -> Path:
        return Path(self.storage.metrics_db).expanduser()
