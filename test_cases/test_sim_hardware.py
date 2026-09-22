import pytest

from ebike_ai.sim_hardware import build_battery_data

# 验证：算出来的 total_vol 必须等于三个电芯相加再保留两位小数
@pytest.mark.parametrize("timestamp", [0, 1.23, 123.45, 1_000_000.0])
def test_total_voltage_equals_sum_of_cells(timestamp):
    battery_data = build_battery_data(timestamp)

    expected_total = round(
        battery_data["cell1"]
        + battery_data["cell2"]
        + battery_data["cell3"],
        2,
    )

    assert battery_data["total_vol"] == expected_total
