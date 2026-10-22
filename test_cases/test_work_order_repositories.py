"""Offline SQL contracts; these tests do not prove MySQL accepts the SQL."""

from datetime import datetime
from unittest.mock import MagicMock

import pymysql
import pytest

from ebike_ai.repositories.battery import BatteryRepository
from ebike_ai.repositories.work_order import WorkOrderRepository


pytestmark = pytest.mark.unit


def assert_caller_owns_transaction(connection):
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()
    connection.close.assert_not_called()


@pytest.mark.parametrize("row", [None, {"id": 7, "vehicle_id": 10}])
def test_battery_lookup_binds_id_and_requests_row_lock(row):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    assert BatteryRepository(connection).get_by_id_for_update(7) == row
    sql, params = cursor.execute.call_args.args
    assert sql == "SELECT id, vehicle_id FROM battery WHERE id = %s FOR UPDATE"
    assert params == (7,)
    assert_caller_owns_transaction(connection)


@pytest.mark.parametrize("with_optional_fields", [False, True])
def test_work_order_insert_binds_fields_and_preserves_unknowns(with_optional_fields):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.lastrowid = 51
    text = "O'Brien'); DROP TABLE work_order; --"
    fields = ({"battery_id": 7, "report_source_note": "维修师现场观察",
               "received_at": datetime(2026, 10, 18, 8, 0), "notes": "中文备注"}
              if with_optional_fields else {})
    result = WorkOrderRepository(connection).create(
        "D13-test", 10, text, "TECHNICIAN_OBSERVATION", **fields,
    )
    assert result == 51
    sql, params = cursor.execute.call_args.args
    assert text not in sql
    assert params == (
        "D13-test", 10, fields.get("battery_id"), text, "TECHNICIAN_OBSERVATION",
        fields.get("report_source_note"), "RECEIVED", fields.get("received_at"), fields.get("notes"),
    )
    assert "completion_outcome, completed_at, cancel_reason)" in sql
    assert sql.endswith("%s, NULL, NULL, NULL)")
    assert sql.count("%s") == len(params)
    assert_caller_owns_transaction(connection)


@pytest.mark.parametrize("repository", ["battery", "work_order"])
def test_repository_leaves_driver_errors_and_cleanup_to_caller(repository):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    driver_error = pymysql.OperationalError(1205, "fake lock timeout")
    cursor.execute.side_effect = driver_error
    with pytest.raises(pymysql.OperationalError) as caught:
        if repository == "battery":
            BatteryRepository(connection).get_by_id_for_update(7)
        else:
            WorkOrderRepository(connection).create("D13-test", 10, "灯不亮", "CUSTOMER_STATEMENT")
    assert caught.value is driver_error
    assert_caller_owns_transaction(connection)


@pytest.mark.parametrize("method,column,value", [
    ("get_by_id", "id", 51), ("get_by_number", "work_order_no", "O'Brien');--"),
])
@pytest.mark.parametrize("row", [None, {"id": 51, "battery_id": None}])
def test_work_order_lookup_binds_values_and_preserves_missing(method, column, value, row):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    assert getattr(WorkOrderRepository(connection), method)(value) == row
    sql, params = cursor.execute.call_args.args
    assert sql.endswith(f"FROM work_order WHERE {column} = %s")
    assert params == (value,)
    assert "created_at, updated_at" in sql
    assert_caller_owns_transaction(connection)
