"""离线验证已提交测试数据的清理边界。"""

from unittest.mock import MagicMock

import pytest

from ebike_ai.database import DatabaseConfig
from test_cases.mysql_work_orders import WorkOrderLab, preflight, verify_owned


pytestmark = pytest.mark.unit


def test_lab_rejects_other_database_before_connecting(tmp_path):
    with pytest.raises(ValueError, match="Only ebike_ai_day11"):
        WorkOrderLab(DatabaseConfig("user", "fake-password", "business"), tmp_path)


def test_preflight_wrong_actual_database_stops_before_any_write():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"name": "business", "tz": "+00:00", "mode": "STRICT_TRANS_TABLES"}
    with pytest.raises(AssertionError, match="Wrong practice database"):
        preflight(connection)
    assert cursor.execute.call_count == 1
    assert cursor.execute.call_args.args[0].startswith("SELECT")


@pytest.mark.parametrize("changed", [{"id": 9}, {"vehicle_id": 8}, {"notes": "unrelated"}])
def test_cleanup_refuses_changed_identity_or_content(changed):
    expected = {"id": 1, "vehicle_id": 2, "notes": "run-token"}
    with pytest.raises(AssertionError, match="mismatch"):
        verify_owned({**expected, **changed}, expected)


def test_cleanup_accepts_expected_content_when_commit_response_lost():
    verify_owned({"id": 51, "work_order_no": "exact-number", "notes": "run-token"},
                 {"work_order_no": "exact-number", "notes": "run-token"})


def test_manifest_contains_identifiers_but_no_credentials(tmp_path):
    lab = WorkOrderLab(DatabaseConfig("user", "fake-password", "ebike_ai_day11"), tmp_path)
    lab.save_manifest("reserved")
    content = lab.manifest_path.read_text(encoding="utf-8")
    assert "fake-password" not in content
    assert lab.records["vehicle"][0]["vehicle_code"] in content
    assert all(len(record[key]) <= 32 for table, key in
               [("vehicle", "vehicle_code"), ("battery", "battery_code"), ("work_order", "work_order_no")]
               for record in lab.records[table])


def test_cleanup_before_ownership_does_not_open_a_connection(tmp_path):
    lab = WorkOrderLab(DatabaseConfig("user", "fake-password", "ebike_ai_day11"), tmp_path)
    lab.connect = MagicMock()
    lab.cleanup()
    lab.connect.assert_not_called()


@pytest.mark.parametrize("mismatch", [False, True])
def test_cleanup_uses_exact_ids_and_rolls_back_on_mismatch(tmp_path, monkeypatch, mismatch):
    lab = WorkOrderLab(DatabaseConfig("user", "fake-password", "ebike_ai_day11"), tmp_path)
    lab.owned = True
    lab.records = {
        "work_order": [{"work_order_no": "order", "notes": "token", "id": 3}],
        "battery": [{"battery_code": "battery", "id": 2}],
        "vehicle": [{"vehicle_code": "vehicle", "id": 1}],
    }
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.rowcount = 1
    cursor.fetchone.side_effect = [
        {"work_order_no": "order", "notes": "token", "id": 3},
        {"battery_code": "battery", "id": 99 if mismatch else 2},
        {"vehicle_code": "vehicle", "id": 1}, None, None, None,
    ]
    monkeypatch.setattr("test_cases.mysql_work_orders.preflight", lambda connection: None)
    lab.connect = MagicMock(return_value=connection)
    if mismatch:
        with pytest.raises(AssertionError, match="mismatch"):
            lab.cleanup()
        connection.commit.assert_not_called()
    else:
        lab.cleanup()
        connection.commit.assert_called_once_with()
    connection.rollback.assert_called()
    connection.close.assert_called()
    deletes = [call.args for call in cursor.execute.call_args_list if call.args[0].startswith("DELETE")]
    assert deletes == [
        ("DELETE FROM work_order WHERE id = %s AND work_order_no = %s", (3, "order")),
    ] + ([] if mismatch else [
        ("DELETE FROM battery WHERE id = %s AND battery_code = %s", (2, "battery")),
        ("DELETE FROM vehicle WHERE id = %s AND vehicle_code = %s", (1, "vehicle")),
    ])


def test_unmarked_lab_user_still_requires_explicit_switch(monkeypatch):
    from test_cases.conftest import work_order_lab

    request = MagicMock()
    request.config.getoption.return_value = False
    read_config = MagicMock(side_effect=AssertionError("must not read credentials"))
    monkeypatch.setattr(DatabaseConfig, "from_env", read_config)
    with pytest.raises(pytest.skip.Exception):
        next(work_order_lab.__wrapped__(request))
    read_config.assert_not_called()
