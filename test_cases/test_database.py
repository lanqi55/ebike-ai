"""Offline configuration, connection policy and transaction ownership checks."""

import traceback
from unittest.mock import MagicMock

import pymysql
import pytest

from ebike_ai.database import (
    DatabaseConfig, DatabaseConfigError, DatabaseConnectionError, SQL_MODE, connect_database,
)
from ebike_ai.repositories.vehicle import VehicleRepository


pytestmark = pytest.mark.unit


@pytest.fixture
def configured_env(monkeypatch):
    for name in ("HOST", "PORT", "USER", "PASSWORD", "NAME"):
        monkeypatch.delenv("EBIKE_DB_" + name, raising=False)
    monkeypatch.setenv("EBIKE_DB_USER", "test-user")
    monkeypatch.setenv("EBIKE_DB_PASSWORD", "fake-password-do-not-log")
    monkeypatch.setenv("EBIKE_DB_NAME", "ebike_ai_day11")


def test_config_is_read_at_call_time_and_hides_password(configured_env, monkeypatch):
    config = DatabaseConfig.from_env()
    assert (config.host, config.port, config.database) == ("127.0.0.1", 3306, "ebike_ai_day11")
    assert config.password not in repr(config)
    monkeypatch.setenv("EBIKE_DB_PORT", "3307")
    assert DatabaseConfig.from_env().port == 3307


@pytest.mark.parametrize("name", ["USER", "PASSWORD", "NAME"])
def test_missing_config_names_the_variable_only(configured_env, monkeypatch, name):
    monkeypatch.delenv("EBIKE_DB_" + name)
    with pytest.raises(DatabaseConfigError, match="EBIKE_DB_" + name) as error:
        DatabaseConfig.from_env()
    assert "fake-password-do-not-log" not in str(error.value)


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_invalid_port_does_not_echo_value(configured_env, monkeypatch, port):
    monkeypatch.setenv("EBIKE_DB_PORT", port)
    with pytest.raises(DatabaseConfigError, match="EBIKE_DB_PORT"):
        DatabaseConfig.from_env()


def test_empty_host_fails_before_connect(configured_env, monkeypatch):
    monkeypatch.setenv("EBIKE_DB_HOST", " ")
    with pytest.raises(DatabaseConfigError, match="EBIKE_DB_HOST"):
        DatabaseConfig.from_env()


def test_connection_has_explicit_transaction_and_session_policy(configured_env, monkeypatch):
    driver = MagicMock()
    monkeypatch.setattr(pymysql, "connect", driver)
    connection = connect_database(DatabaseConfig.from_env())
    options = driver.call_args.kwargs
    assert connection is driver.return_value
    assert options["autocommit"] is False
    assert options["charset"] == "utf8mb4"
    assert options["init_command"] == "SET SESSION time_zone = '+00:00'"
    assert options["sql_mode"] == SQL_MODE
    assert options["cursorclass"] is pymysql.cursors.DictCursor
    assert options["connect_timeout"] == options["read_timeout"] == options["write_timeout"] == 5
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()


@pytest.mark.parametrize("driver_error", [
    pymysql.OperationalError(1045, "fake-password-do-not-log"),
    OSError("fake-password-do-not-log"),
    RuntimeError("fake-password-do-not-log"),
])
def test_connection_failure_hides_driver_message(configured_env, monkeypatch, driver_error):
    monkeypatch.setattr(pymysql, "connect", MagicMock(side_effect=driver_error))
    with pytest.raises(DatabaseConnectionError) as error:
        connect_database(DatabaseConfig.from_env())
    rendered = "".join(traceback.format_exception(type(error.value), error.value, error.tb))
    assert "fake-password-do-not-log" not in rendered
    if isinstance(driver_error, pymysql.OperationalError):
        assert "1045" in str(error.value)


def test_repository_binds_text_and_leaves_transaction_to_caller():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.lastrowid = 42
    text = "O'Brien'); DROP TABLE vehicle; --"
    assert VehicleRepository(connection).create("D12-test", brand=text, notes="中文备注") == 42
    sql, params = cursor.execute.call_args.args
    assert text not in sql
    assert params == ("D12-test", text, None, "中文备注")
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()
    connection.close.assert_not_called()


@pytest.mark.parametrize("row", [None, {"id": 42, "vehicle_code": "D12-test"}])
def test_repository_returns_row_or_none(row):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    assert VehicleRepository(connection).get_by_id(42) == row
    assert cursor.execute.call_args.args[1] == (42,)
    connection.commit.assert_not_called()
    connection.close.assert_not_called()


def test_repository_preserves_constraint_error_without_rolling_back():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = pymysql.IntegrityError(1062, "test duplicate")
    with pytest.raises(pymysql.IntegrityError) as error:
        VehicleRepository(connection).create("D12-duplicate")
    assert error.value.args[0] == 1062
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()
    connection.close.assert_not_called()
