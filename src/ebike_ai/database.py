"""显式读取数据库配置并创建连接；导入本模块不会连接数据库。"""

import os
from dataclasses import dataclass, field

import pymysql


SQL_MODE = (
    "STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,"
    "ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION"
)


class DatabaseConfigError(ValueError):
    """数据库配置缺失或无效；错误信息不包含配置值。"""


class DatabaseConnectionError(RuntimeError):
    """连接或初始化失败；错误信息不包含凭据。"""


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
    """由调用方负责提交、回滚和关闭；不共享连接，也不自动提交。"""
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
        # 驱动原始错误可能包含连接信息，因此不能将其放入对外错误消息。
        code = exc.args[0] if exc.args and type(exc.args[0]) is int else None
        suffix = f" (MySQL error {code})" if code is not None else ""
        raise DatabaseConnectionError(
            "Database connection failed; check service, credentials, database and authentication"
            + suffix
        ) from None
