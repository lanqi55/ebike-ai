"""Real commits, independently observed; requires --run-db and the existing lab."""

import pytest

from ebike_ai.services.work_order import (
    BatteryNotFoundError, BatteryVehicleMismatchError, VehicleNotFoundError,
    WorkOrderPersistenceError, WorkOrderService,
)


pytestmark = [pytest.mark.integration, pytest.mark.db]


@pytest.mark.parametrize("with_battery", [False, True])
def test_commit_visible_from_new_connection(work_order_lab, with_battery):
    lab = work_order_lab
    battery_id = lab.records["battery"][0]["id"] if with_battery else None
    fields = lab.order(battery_id=battery_id)
    order_id = WorkOrderService(lab.connect).create_work_order(**fields)
    row = lab.find_order(fields["work_order_no"])
    assert row["id"] == order_id
    assert all(row[key] == value for key, value in fields.items())
    assert row["status"] == "RECEIVED"
    assert row["completion_outcome"] is row["completed_at"] is row["cancel_reason"] is None


@pytest.mark.parametrize("scenario,error_type", [
    ("missing_vehicle", VehicleNotFoundError),
    ("missing_battery", BatteryNotFoundError),
    ("wrong_vehicle", BatteryVehicleMismatchError),
])
def test_invalid_association_leaves_no_order(work_order_lab, scenario, error_type):
    lab = work_order_lab
    overrides = {"missing_vehicle": {"vehicle_id": -1}, "missing_battery": {"battery_id": -1},
                 "wrong_vehicle": {"battery_id": lab.records["battery"][1]["id"]}}[scenario]
    fields = lab.order(**overrides)
    with pytest.raises(error_type):
        WorkOrderService(lab.connect).create_work_order(**fields)
    assert lab.find_order(fields["work_order_no"]) is None


def test_duplicate_number_preserves_original(work_order_lab):
    lab = work_order_lab
    fields = lab.order()
    service = WorkOrderService(lab.connect)
    original_id = service.create_work_order(**fields)
    original = lab.find_order(fields["work_order_no"])
    with pytest.raises(WorkOrderPersistenceError):
        service.create_work_order(**{**fields, "reported_symptom": "不得覆盖原单"})
    assert lab.find_order(fields["work_order_no"]) == original
    assert original["id"] == original_id
