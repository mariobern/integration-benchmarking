"""Configuration loading, ClickHouse client creation, and asset class constants.

Centralizes config patterns previously duplicated across benchmark scripts.
"""

from pathlib import Path

import clickhouse_connect
import yaml

# Asset class normalization mapping (CSV value -> canonical value)
ASSET_CLASS_ALIASES = {
    "metal": "metals",
    "metals": "metals",
    "equity-us": "us-equities",
    "us-equities": "us-equities",
    "fx": "fx",
    "commodity": "commodity",
    "crypto": "crypto",
    "crypto-redemption-rate": "crypto-redemption-rate",
    "funding-rate": "funding-rate",
    "rates": "us-treasuries",
    "nav": "nav",
    "us-treasuries": "us-treasuries",
    "treasuries": "us-treasuries",
}

# Asset classes that have benchmark data available
BENCHMARKABLE_ASSET_CLASSES = {
    "fx",
    "metals",
    "us-equities",
    "commodity",
    "us-treasuries",
}

# Default ClickHouse connection timeouts (seconds)
_CONNECT_TIMEOUT = 60
_SEND_RECEIVE_TIMEOUT = 300


def normalize_asset_class(asset_class: str) -> str:
    """Normalize asset class name to canonical form."""
    return ASSET_CLASS_ALIASES.get(asset_class.lower(), asset_class.lower())


def load_config() -> dict:
    """Load database configuration from config.yaml."""
    config_path = Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(
            "config.yaml not found. Copy config.yaml.sample to config.yaml "
            "and fill in credentials."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_clients(config: dict) -> tuple:
    """Create ClickHouse clients for Lazer and Analytics databases."""
    client_lazer = get_lazer_client(config)
    client_analytics = get_analytics_client(config)
    return client_lazer, client_analytics


def get_lazer_client(config: dict):
    """Create ClickHouse client for Lazer database."""
    lazer_cfg = config["lazer_clickhouse_prod"]
    return clickhouse_connect.get_client(
        host=lazer_cfg["host"],
        username=lazer_cfg["user"],
        password=lazer_cfg["password"],
        secure=True,
        connect_timeout=_CONNECT_TIMEOUT,
        send_receive_timeout=_SEND_RECEIVE_TIMEOUT,
    )


def get_analytics_client(config: dict):
    """Create ClickHouse client for Analytics database."""
    analytics_cfg = config["analytics_clickhouse"]
    return clickhouse_connect.get_client(
        host=analytics_cfg["host"],
        username=analytics_cfg["user"],
        password=analytics_cfg["password"],
        secure=True,
        connect_timeout=_CONNECT_TIMEOUT,
        send_receive_timeout=_SEND_RECEIVE_TIMEOUT,
    )
