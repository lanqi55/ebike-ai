"""Explicit database configuration and connections; importing this opens nothing."""

import os
from dataclasses import dataclass, field

import pymysql


SQL_MODE = (
    "STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
    "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"
)


class DatabaseConfigError(ValueError):
    """Missing or invalid database configuration (never includes its values)."""


class DatabaseConnectionError(RuntimeError):
    """Connection/setup failure with a credential-free message."""


@dataclass(frozen=True)
class DatabaseConfig:
    user: str
    password: str = field(repr=False)
    database: str
    host: str = "127.0.0.1"
    port: int = 3306

    @classmethod
    def from_env(cls):
        required = ("EBIKE_DB_USER", "EBIKE_DB_PASSWORD", "EBIKE_DB_NAME")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise DatabaseConfigError("Missing database configuration: " + ", ".join(missing))
        try:
            port = int(os.environ.get("EBIKE_DB_PORT", "3306"))
        except ValueError:
            raise DatabaseConfigError("EBIKE_DB_PORT must be an integer from 1 to 65535") from None
        if not 1 <= port <= 65535:
            raise DatabaseConfigError("EBIKE_DB_PORT must be an integer from 1 to 65535")
        host = os.environ.get("EBIKE_DB_HOST", "127.0.0.1")
        if not host.strip():
            raise DatabaseConfigError("EBIKE_DB_HOST must not be blank")
        return cls(
            user=os.environ["EBIKE_DB_USER"],
            password=os.environ["EBIKE_DB_PASSWORD"],
            database=os.environ["EBIKE_DB_NAME"],
            host=host,
            port=port,
        )


def connect_database(config: DatabaseConfig):
    """Caller owns commit/rollback/close; no shared connection or auto-commit."""
    try:
        return pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            connect_timeout=5,
            read_timeout=5,
            write_timeout=5,
            sql_mode=SQL_MODE,
            init_command="SET SESSION time_zone = '+00:00'",
            local_infile=False,
        )
    except (pymysql.MySQLError, OSError, RuntimeError) as exc:
        # Never include the driver's message: it can contain connection details.
        code = exc.args[0] if exc.args and type(exc.args[0]) is int else None
        suffix = f" (MySQL error {code})" if code is not None else ""
        raise DatabaseConnectionError(
            "Database connection failed; check service, credentials, database and authentication"
            + suffix
        ) from None
