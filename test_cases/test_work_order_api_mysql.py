"""验证 HTTP → 真实 Service → 真实 MySQL 链路，并用新连接核对结果。"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from ebike_ai.api import app
from ebike_ai.services.work_order import WorkOrderService
from ebike_ai.work_order_api import MAX_ID, get_work_order_service


pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.fixture
def real_api(work_order_lab, monkeypatch):
    lab = work_order_lab
    # 只替换连接配置与追踪方式；整条业务链路仍使用真实实现。
    monkeypatch.setitem(app.dependency_overrides, get_work_order_service, lambda: WorkOrderService(lab.connect))
    with TestClient(app) as client:
        yield client, lab


@pytest.mark.parametrize("with_battery", [False, True])
def test_http_create_query_and_independent_database_verification(real_api, with_battery):
    client, lab = real_api
    fields = lab.order(
        battery_id=lab.records["battery"][0]["id"] if with_battery else None,
        received_at=datetime(2026, 10, 22, 8, 30) if with_battery else None,
    )
    body = {**fields, "received_at": "2026-10-22T16:30:00+08:00" if with_battery else None}
    created = client.post("/work-orders", json=body)
    assert created.status_code == 201
    order_id = created.json()["id"]
    lab.remember_order_id(order_id)
    stored = lab.find_order(fields["work_order_no"])
    assert stored["id"] == order_id
    assert all(stored[key] == value for key, value in fields.items())
    by_id = client.get(f"/work-orders/{order_id}")
    by_number = client.get("/work-orders/by-number/" + fields["work_order_no"])
    assert by_id.status_code == by_number.status_code == 200
    assert by_id.json() == by_number.json()
    assert by_id.json()["received_at"] == ("2026-10-22T08:30:00Z" if with_battery else None)
    assert by_id.json()["status"] == "RECEIVED"
    assert by_id.json()["completion_outcome"] is by_id.json()["completed_at"] is None
    assert created.json()["warning"] is None


@pytest.mark.parametrize("scenario,status,code", [
    ("missing_vehicle", 404, "VEHICLE_NOT_FOUND"),
    ("missing_battery", 404, "BATTERY_NOT_FOUND"),
    ("wrong_vehicle", 409, "BATTERY_VEHICLE_MISMATCH"),
])
def test_http_rejects_invalid_associations_without_persisting(real_api, scenario, status, code):
    client, lab = real_api
    # 使用能通过 HTTP 校验的正整数 ID；先确认练习库中不存在该 ID。
    with lab.connection() as connection:
        with connection.cursor() as cursor:
            for table in ("vehicle", "battery"):
                cursor.execute(f"SELECT id FROM {table} WHERE id = %s", (MAX_ID,))
                assert cursor.fetchone() is None
    overrides = {"missing_vehicle": {"vehicle_id": MAX_ID}, "missing_battery": {"battery_id": MAX_ID},
                 "wrong_vehicle": {"battery_id": lab.records["battery"][1]["id"]}}[scenario]
    fields = lab.order(**overrides)
    response = client.post("/work-orders", json=fields)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert lab.find_order(fields["work_order_no"]) is None


def test_http_duplicate_number_never_overwrites_original(real_api):
    client, lab = real_api
    fields = lab.order()
    first = client.post("/work-orders", json=fields)
    assert first.status_code == 201
    lab.remember_order_id(first.json()["id"])
    original = lab.find_order(fields["work_order_no"])
    duplicate = client.post("/work-orders", json={**fields, "reported_symptom": "不得覆盖原单"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "DUPLICATE_WORK_ORDER"
    assert lab.find_order(fields["work_order_no"]) == original


def test_http_missing_order_is_404_for_both_lookups(real_api):
    client, lab = real_api
    number = lab.records["work_order"][0]["work_order_no"]
    with lab.connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM work_order WHERE id = %s", (MAX_ID,))
            assert cursor.fetchone() is None
    for path in (f"/work-orders/{MAX_ID}", "/work-orders/by-number/" + number):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "WORK_ORDER_NOT_FOUND"
