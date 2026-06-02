from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yml"


def _build_postgres_url() -> str | None:
    """Build PostgreSQL URL from environment variables if provided."""
    postgres_url = os.getenv("POSTGRES_URL")
    if postgres_url:
        return postgres_url

    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT")
    db = os.getenv("POSTGRES_DB")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")

    if all([host, port, db, user, password]):
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    return None


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    if not isinstance(config, dict):
        raise ValueError(f"Expected mapping at {CONFIG_PATH}")

    env_postgres_url = _build_postgres_url()
    if env_postgres_url and "memory" in config:
        config["memory"]["postgres_url"] = env_postgres_url

    redis_url = os.getenv("REDIS_URL")
    if redis_url and "memory" in config:
        config["memory"]["redis_url"] = redis_url

    qdrant_url = os.getenv("QDRANT_URL")
    if qdrant_url and "memory" in config:
        config["memory"]["qdrant_url"] = qdrant_url

    return config
