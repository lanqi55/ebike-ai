"""使用真实 Repository 和假连接验证业务规则与事务行为。"""

import traceback
from datetime import datetime
from unittest.mock import MagicMock

import pymysql
import pytest

from ebike_ai.database import DatabaseConfigError, DatabaseConnectionError
from ebike_ai.services import work_order as service_module
from ebike_ai.services.work_order import (
    BatteryNotFoundError, BatteryVehicleMismatchError, VehicleNotFoundError,
    DuplicateWorkOrderError, WorkOrderNotFoundError,
    WorkOrderCleanupError, WorkOrderCommitUnknownError, WorkOrderPersistenceError,
    WorkOrderService,
)


pytestmark = pytest.mark.unit
SENSITIVE = "fake-credential-must-not-appear"


def fake_connection(rows):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = rows
    cursor.lastrowid = 51
    return connection, cursor


def create_order(service, **fields):
    return service.create_work_order("D13-test", 10, "灯不亮", "CUSTOMER_STATEMENT", **fields)


def statements(cursor):
    return [call.args[0] for call in cursor.execute.call_args_list]


def assert_sanitized(error):
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert SENSITIVE not in rendered


@pytest.mark.parametrize("battery_id", [None, 7])
def test_success_checks_then_inserts_commits_and_closes_on_one_connection(battery_id):
    rows = [{"id": 10}, {"id": 7, "vehicle_id": 10}]
    connection, cursor = fake_connection(rows)
    factory = MagicMock(return_value=connection)
    when = datetime(2026, 10, 18, 8, 0)
    assert create_order(
        WorkOrderService(factory), battery_id=battery_id,
        report_source_note="客户描述", received_at=when, notes="固定测试",
    ) == 51
    factory.assert_called_once_with()
    sql = statements(cursor)
    assert "FROM vehicle" in sql[0]
    if battery_id is None:
        assert len(sql) == 2
        assert not any("FROM battery" in query for query in sql)
    else:
        assert len(sql) == 3
        assert "FROM battery" in sql[1] and sql[1].endswith("FOR UPDATE")
    assert sql[-1].startswith("INSERT INTO work_order")
    assert cursor.execute.call_args.args[1] == (
        "D13-test", 10, battery_id, "灯不亮", "CUSTOMER_STATEMENT",
        "客户描述", "RECEIVED", when, "固定测试",
    )
    # 使用真实 Repository，可发现其意外创建其他连接或提前提交的问题。
    names = [call[0] for call in connection.mock_calls]
    assert names[-2:] == ["commit", "close"]
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("rows,battery_id,error_type", [
    ([None], 7, VehicleNotFoundError),
    ([None], None, VehicleNotFoundError),
    ([{"id": 10}, None], 7, BatteryNotFoundError),
    ([{"id": 10}, None], 0, BatteryNotFoundError),
    ([{"id": 10}, {"id": 7, "vehicle_id": 20}], 7, BatteryVehicleMismatchError),
])
def test_invalid_association_never_inserts_or_commits(rows, battery_id, error_type):
    connection, cursor = fake_connection(rows)
    with pytest.raises(error_type) as caught:
        create_order(WorkOrderService(lambda: connection), battery_id=battery_id)
    assert not any(sql.startswith("INSERT") for sql in statements(cursor))
    if rows[0] is None:
        assert len(statements(cursor)) == 1
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()
    assert [call[0] for call in connection.mock_calls][-2:] == ["rollback", "close"]
    assert not caught.value.rollback_failed and not caught.value.close_failed


@pytest.mark.parametrize("stage", ["query", "insert", "commit"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_database_failure_is_sanitized_and_cleanup_is_always_attempted(stage, cleanup_fails):
    connection, cursor = fake_connection([{"id": 10}])
    error = pymysql.OperationalError(2013, SENSITIVE)
    if stage == "commit":
        connection.commit.side_effect = error
    else:
        cursor.execute.side_effect = [error] if stage == "query" else [None, error]
    if cleanup_fails:
        connection.rollback.side_effect = OSError(SENSITIVE)
        connection.close.side_effect = OSError(SENSITIVE)
    factory = MagicMock(return_value=connection)
    expected = WorkOrderCommitUnknownError if stage == "commit" else WorkOrderPersistenceError
    with pytest.raises(expected) as caught:
        create_order(WorkOrderService(factory))
    factory.assert_called_once_with()  # 不自动重试。
    assert type(caught.value) is expected
    assert_sanitized(caught.value)
    assert caught.value.rollback_failed is cleanup_fails
    assert caught.value.close_failed is cleanup_fails
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()
    if stage == "commit":
        connection.commit.assert_called_once_with()
        assert "unknown" in str(caught.value)
    else:
        connection.commit.assert_not_called()


def test_cleanup_failure_preserves_business_error():
    connection, cursor = fake_connection([None])
    connection.rollback.side_effect = OSError(SENSITIVE)
    connection.close.side_effect = OSError(SENSITIVE)
    with pytest.raises(VehicleNotFoundError) as caught:
        create_order(WorkOrderService(lambda: connection))
    assert caught.value.rollback_failed and caught.value.close_failed
    assert_sanitized(caught.value)
    connection.close.assert_called_once_with()
    connection.commit.assert_not_called()
    assert not any(sql.startswith("INSERT") for sql in statements(cursor))


def test_close_failure_after_commit_reports_saved_id_without_rollback_or_retry():
    connection, _ = fake_connection([{"id": 10}])
    connection.close.side_effect = OSError(SENSITIVE)
    factory = MagicMock(return_value=connection)
    with pytest.raises(WorkOrderCleanupError) as caught:
        create_order(WorkOrderService(factory))
    assert caught.value.work_order_id == 51
    assert caught.value.close_failed and not caught.value.rollback_failed
    assert "committed" in str(caught.value)
    assert_sanitized(caught.value)
    factory.assert_called_once_with()
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("factory_error", [
    DatabaseConfigError("Missing database configuration: EBIKE_DB_NAME"),
    DatabaseConnectionError("Database connection failed"),
    OSError(SENSITIVE),
])
def test_factory_failure_does_not_retry_and_hides_untrusted_details(factory_error):
    factory = MagicMock(side_effect=factory_error)
    expected = type(factory_error) if isinstance(
        factory_error, (DatabaseConfigError, DatabaseConnectionError)
    ) else WorkOrderPersistenceError
    with pytest.raises(expected) as caught:
        create_order(WorkOrderService(factory))
    factory.assert_called_once_with()
    assert_sanitized(caught.value)


def test_each_call_gets_a_fresh_connection():
    first, _ = fake_connection([{"id": 10}])
    second, _ = fake_connection([{"id": 10}])
    service = WorkOrderService(MagicMock(side_effect=[first, second]))
    create_order(service)
    create_order(service)
    assert service.connection_factory.call_count == 2
    for connection in (first, second):
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()


def test_default_factory_reads_configuration_only_when_called(monkeypatch):
    settings = object()
    config = MagicMock(return_value=settings)
    connection, _ = fake_connection([{"id": 10}])
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(service_module.DatabaseConfig, "from_env", config)
    monkeypatch.setattr(service_module, "connect_database", connect)
    service = WorkOrderService()
    config.assert_not_called()
    connect.assert_not_called()
    create_order(service)
    config.assert_called_once_with()
    connect.assert_called_once_with(settings)


def test_interruption_still_rolls_back_and_closes():
    connection, cursor = fake_connection([])
    cursor.execute.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        create_order(WorkOrderService(lambda: connection))
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()
    connection.commit.assert_not_called()


@pytest.mark.parametrize("stage,code,expected", [
    ("insert", 1062, DuplicateWorkOrderError),
    ("insert", 1452, WorkOrderPersistenceError),
    ("query", 1062, WorkOrderPersistenceError),
    ("commit", 1062, WorkOrderCommitUnknownError),
])
def test_only_insert_duplicate_maps_to_business_conflict(stage, code, expected):
    connection, cursor = fake_connection([{"id": 10}])
    failure = pymysql.IntegrityError(code, SENSITIVE)
    if stage == "commit":
        connection.commit.side_effect = failure
    else:
        cursor.execute.side_effect = [failure] if stage == "query" else [None, failure]
    with pytest.raises(expected) as caught:
        create_order(WorkOrderService(lambda: connection))
    assert type(caught.value) is expected
    assert_sanitized(caught.value)
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("method,value", [("get_by_id", 51), ("get_by_number", "O'Brien')--")])
def test_reads_use_fresh_connections_and_finish_transactions(method, value):
    row = {"id": 51}
    first, first_cursor = fake_connection([row])
    second, _ = fake_connection([None])
    service = WorkOrderService(MagicMock(side_effect=[first, second]))
    assert getattr(service, method)(value) == row
    with pytest.raises(WorkOrderNotFoundError):
        getattr(service, method)(value)
    assert first_cursor.execute.call_args.args[1] == (value,)
    for connection in (first, second):
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()


@pytest.mark.parametrize("stage", ["query", "rollback", "close"])
def test_read_failures_are_sanitized_and_always_close(stage):
    connection, cursor = fake_connection([{"id": 51}])
    target = cursor.execute if stage == "query" else getattr(connection, stage)
    target.side_effect = RuntimeError(SENSITIVE)
    with pytest.raises(WorkOrderPersistenceError) as caught:
        WorkOrderService(lambda: connection).get_by_id(51)
    assert_sanitized(caught.value)
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()
    connection.commit.assert_not_called()


def test_read_not_found_survives_cleanup_failure():
    connection, _ = fake_connection([None])
    connection.close.side_effect = RuntimeError(SENSITIVE)
    with pytest.raises(WorkOrderNotFoundError) as caught:
        WorkOrderService(lambda: connection).get_by_id(51)
    assert caught.value.close_failed
    assert_sanitized(caught.value)


def test_read_interruption_still_releases_connection():
    connection, cursor = fake_connection([])
    cursor.execute.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        WorkOrderService(lambda: connection).get_by_id(51)
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()
