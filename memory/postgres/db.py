from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg

from ..config_loader import get_config
from .exceptions import DatabaseUnavailableError


logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()
_pool_error: Exception | None = None
_schema_initialized = False
_schema_lock = asyncio.Lock()
_schema_path = Path(__file__).with_name("schema.sql")


def _parse_postgres_url(url: str) -> dict[str, Any]:
    """Parse PostgreSQL URL to extract connection details for logging."""
    try:
        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "unknown",
            "port": parsed.port or 5432,
            "database": parsed.path.lstrip("/") if parsed.path else "unknown",
            "user": parsed.username or "unknown",
        }
    except Exception as e:
        logger.warning(f"Failed to parse postgres URL: {e}")
        return {"host": "unknown", "port": "unknown", "database": "unknown", "user": "unknown"}


async def _initialize_schema(pool: asyncpg.Pool) -> None:
    global _schema_initialized

    if _schema_initialized:
        return

    async with _schema_lock:
        if _schema_initialized:
            return

        try:
            schema_sql = _schema_path.read_text(encoding="utf-8")
            async with pool.acquire() as connection:
                await connection.execute(schema_sql)
            _schema_initialized = True
            logger.info("PostgreSQL schema initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL schema: {e}")
            raise


async def get_pool() -> asyncpg.Pool:
    global _pool, _pool_error

    if _pool is not None:
        return _pool

    if _pool_error is not None:
        raise DatabaseUnavailableError("PostgreSQL connection previously failed", _pool_error)

    async with _pool_lock:
        if _pool is not None:
            return _pool

        if _pool_error is not None:
            raise DatabaseUnavailableError("PostgreSQL connection previously failed", _pool_error)

        try:
            config = get_config()
            postgres_url = config["memory"]["postgres_url"]

            conn_details = _parse_postgres_url(postgres_url)
            logger.info(
                f"Attempting PostgreSQL connection: "
                f"host={conn_details['host']}, port={conn_details['port']}, "
                f"database={conn_details['database']}, user={conn_details['user']}"
            )

            _pool = await asyncpg.create_pool(
                postgres_url,
                min_size=2,
                max_size=10,
                command_timeout=5.0,
                timeout=5.0,
            )

            await _initialize_schema(_pool)
            logger.info("PostgreSQL connection pool created successfully")

        except (asyncpg.PostgresError, OSError, ConnectionError, TimeoutError) as e:
            _pool_error = e
            conn_details = _parse_postgres_url(config.get("memory", {}).get("postgres_url", "unknown"))
            logger.error(
                f"PostgreSQL connection failed: host={conn_details['host']}, "
                f"port={conn_details['port']}, database={conn_details['database']}, "
                f"error={type(e).__name__}: {e}"
            )
            raise DatabaseUnavailableError(
                f"Failed to connect to PostgreSQL at {conn_details['host']}:{conn_details['port']}", e
            ) from e
        except Exception as e:
            _pool_error = e
            logger.error(f"Unexpected error creating PostgreSQL pool: {type(e).__name__}: {e}")
            raise DatabaseUnavailableError("Unexpected database connection error", e) from e

    return _pool


async def close_pool() -> None:
    global _pool, _schema_initialized, _pool_error

    if _pool is not None:
        try:
            await _pool.close()
            logger.info("PostgreSQL connection pool closed successfully")
        except Exception as e:
            logger.warning(f"Error closing PostgreSQL pool: {e}")
        finally:
            _pool = None
            _schema_initialized = False
            _pool_error = None


async def execute(query: str, *args: Any) -> str:
    try:
        pool = await get_pool()
        async with pool.acquire() as connection:
            return await connection.execute(query, *args)
    except DatabaseUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Query execution failed: {type(e).__name__}: {e}")
        raise DatabaseUnavailableError("Database operation failed", e) from e


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    try:
        pool = await get_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(query, *args)
        return list(rows)
    except DatabaseUnavailableError:
        raise
    except Exception as e:
        logger.error(f"Query fetch failed: {type(e).__name__}: {e}")
        raise DatabaseUnavailableError("Database operation failed", e) from e


def is_database_available() -> bool:
    """Check if database connection has been established."""
    return _pool is not None and _pool_error is None


def reset_connection_state() -> None:
    """Reset connection error state to allow retry on next connection attempt."""
    global _pool_error
    _pool_error = None
