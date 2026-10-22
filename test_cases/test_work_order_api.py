"""使用假 Service 验证 HTTP 契约，不调用 MySQL 或模型。"""

from datetime import datetime
from unittest.mock import MagicMock
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from ebike_ai.api import app
from ebike_ai.database import DatabaseConfigError, DatabaseConnectionError
from ebike_ai.services.work_order import (
    BatteryNotFoundError, BatteryVehicleMismatchError, DuplicateWorkOrderError,
    VehicleNotFoundError, WorkOrderCleanupError, WorkOrderCommitUnknownError,
    WorkOrderNotFoundError, WorkOrderPersistenceError, WorkOrderService,
)
from ebike_ai.work_order_api import get_work_order_service


pytestmark = pytest.mark.integration
SENSITIVE = "fake-internal-password-do-not-expose"


def payload(**overrides):
    return {"work_order_no": "W3-demo", "vehicle_id": 10, "reported_symptom": "灯不亮",
            "report_source": "CUSTOMER_STATEMENT", **overrides}


def stored_row(**overrides):
    return {**payload(), "id": 51, "battery_id": None, "report_source_note": None,
            "status": "RECEIVED", "completion_outcome": None, "received_at": None,
            "completed_at": None, "cancel_reason": None, "notes": None,
            "created_at": datetime(2026, 10, 22, 8), "updated_at": datetime(2026, 10, 22, 8), **overrides}


@pytest.fixture
def api_client(monkeypatch):
    service = MagicMock(spec=WorkOrderService)
    service.create_work_order.return_value = 51
    service.get_by_id.return_value = stored_row()
    service.get_by_number.return_value = stored_row()
    monkeypatch.setitem(app.dependency_overrides, get_work_order_service, lambda: service)
    with TestClient(app) as client:
        yield client, service


def test_create_preserves_unknowns_and_normalizes_aware_time(api_client):
    client, service = api_client
    response = client.post("/work-orders", json=payload(received_at="2026-10-22T16:30:00+08:00"))
    assert response.status_code == 201
    assert response.json() == {"id": 51, "work_order_no": "W3-demo", "status": "RECEIVED", "warning": None}
    fields = service.create_work_order.call_args.kwargs
    assert fields["received_at"] == datetime(2026, 10, 22, 8, 30)
    assert fields["battery_id"] is fields["notes"] is fields["report_source_note"] is None
    service.create_work_order.assert_called_once()


def test_create_without_time_does_not_invent_received_time(api_client):
    client, service = api_client
    assert client.post("/work-orders", json=payload()).status_code == 201
    assert service.create_work_order.call_args.kwargs["received_at"] is None


@pytest.mark.parametrize("fields", [
    {"work_order_no": " "}, {"work_order_no": "a" * 33}, {"reported_symptom": "\t \n"},
    {"reported_symptom": 1}, {"vehicle_id": 0}, {"vehicle_id": -1}, {"vehicle_id": True},
    {"vehicle_id": "10"}, {"vehicle_id": 2**64}, {"battery_id": False}, {"battery_id": -1},
    {"report_source": "AI"}, {"received_at": "2026-10-22T08:00:00"},
    {"received_at": "2026-10-22"}, {"received_at": 1792656000},
    {"received_at": "0999-12-31T08:00:00Z"}, {"received_at": "9999-12-31T23:00:00-12:00"},
    {"status": "COMPLETED"}, {"completed_at": None}, {"completion_outcome": "REPAIRED"},
    {"cancel_reason": "x"}, {"notes": "中" * 21846},
], ids=["blank-number", "long-number", "blank-symptom", "bad-symptom-type", "zero-id", "negative-id",
        "boolean-id", "string-id", "overflow-id", "boolean-battery", "negative-battery", "source",
        "naive-time", "date-only", "numeric-time", "early-time", "late-time", "status",
        "completed-at", "outcome", "cancel-reason", "text-bytes"])
def test_invalid_request_never_calls_service(api_client, fields):
    client, service = api_client
    assert client.post("/work-orders", json=payload(**fields)).status_code == 422
    service.create_work_order.assert_not_called()


@pytest.mark.parametrize("name", ["work_order_no", "vehicle_id", "reported_symptom", "report_source"])
def test_missing_required_field(api_client, name):
    client, service = api_client
    fields = payload()
    del fields[name]
    assert client.post("/work-orders", json=fields).status_code == 422
    service.create_work_order.assert_not_called()


@pytest.mark.parametrize("error,status,code", [
    (VehicleNotFoundError, 404, "VEHICLE_NOT_FOUND"),
    (BatteryNotFoundError, 404, "BATTERY_NOT_FOUND"),
    (BatteryVehicleMismatchError, 409, "BATTERY_VEHICLE_MISMATCH"),
    (DuplicateWorkOrderError, 409, "DUPLICATE_WORK_ORDER"),
    (WorkOrderCommitUnknownError, 503, "COMMIT_OUTCOME_UNKNOWN"),
    (DatabaseConfigError, 503, "DATABASE_NOT_CONFIGURED"),
    (DatabaseConnectionError, 503, "DATABASE_UNAVAILABLE"),
    (WorkOrderPersistenceError, 503, "DATABASE_OPERATION_FAILED"),
    (RuntimeError, 500, "INTERNAL_ERROR"),
])
def test_creation_errors_are_distinct_sanitized_and_not_retried(api_client, error, status, code, caplog):
    client, service = api_client
    service.create_work_order.side_effect = error(SENSITIVE)
    response = client.post("/work-orders", json=payload())
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert SENSITIVE not in response.text + caplog.text
    service.create_work_order.assert_called_once()


def test_committed_close_failure_returns_saved_id_and_warning(api_client, caplog):
    client, service = api_client
    service.create_work_order.side_effect = WorkOrderCleanupError(51)
    response = client.post("/work-orders", json=payload())
    assert response.status_code == 201
    assert response.json()["id"] == 51
    assert "已保存" in response.json()["warning"]
    assert "不要重复创建" in response.json()["warning"]
    service.create_work_order.assert_called_once()


@pytest.mark.parametrize("path,method,arg", [
    ("/work-orders/51", "get_by_id", 51),
    ("/work-orders/by-number/" + quote("W3/O'Brien?灯", safe=""), "get_by_number", "W3/O'Brien?灯"),
])
def test_query_details_include_utc_and_keep_nulls(api_client, path, method, arg):
    client, service = api_client
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["created_at"] == "2026-10-22T08:00:00Z"
    assert response.json()["received_at"] is response.json()["battery_id"] is None
    getattr(service, method).assert_called_once_with(arg)


@pytest.mark.parametrize("path,method", [("/work-orders/51", "get_by_id"),
                                         ("/work-orders/by-number/W3-demo", "get_by_number")])
@pytest.mark.parametrize("error,status,code", [
    (WorkOrderNotFoundError, 404, "WORK_ORDER_NOT_FOUND"),
    (DatabaseConnectionError, 503, "DATABASE_UNAVAILABLE"),
    (WorkOrderPersistenceError, 503, "DATABASE_OPERATION_FAILED"),
    (RuntimeError, 500, "INTERNAL_ERROR"),
])
def test_query_failure_does_not_leak_details(api_client, path, method, error, status, code):
    client, service = api_client
    getattr(service, method).side_effect = error(SENSITIVE)
    response = client.get(path)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert SENSITIVE not in response.text


@pytest.mark.parametrize("path", ["/work-orders/0", "/work-orders/-1", "/work-orders/no-id",
                                 "/work-orders/18446744073709551616", "/work-orders/by-number/%20",
                                 "/work-orders/by-number/" + "a" * 33])
def test_invalid_query_never_calls_service(api_client, path):
    client, service = api_client
    assert client.get(path).status_code == 422
    service.get_by_id.assert_not_called()
    service.get_by_number.assert_not_called()


def test_unconfigured_database_does_not_break_health_or_openapi(monkeypatch):
    for name in ("USER", "PASSWORD", "NAME"):
        monkeypatch.delenv("EBIKE_DB_" + name, raising=False)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        schema = client.get("/openapi.json").json()
        assert "/work-orders/by-number/{work_order_no}" in schema["paths"]
        assert "201" in schema["paths"]["/work-orders"]["post"]["responses"]
        response = client.post("/work-orders", json=payload())
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DATABASE_NOT_CONFIGURED"
