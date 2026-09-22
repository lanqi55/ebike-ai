import json

import pytest

from ebike_ai.battery_data import (
    BatteryDataValidationError,
    VOLTAGE_FIELDS,
    validate_battery_data,
)
from ebike_ai.config import config
from ebike_ai.hardware_collect import store_battery_line
from ebike_ai.read_hardware import get_latest_battery_data


def valid_battery_data():
    return {
        "cell1": 3.2,
        "cell2": 3.2,
        "cell3": 2.11,
        "total_vol": 8.51,
    }


def test_valid_data_preserves_extra_fields_without_mutating_input():
    raw_data = {**valid_battery_data(), "timestamp": 123456}

    result = validate_battery_data(raw_data)

    assert result == raw_data
    assert result is not raw_data
    assert result["timestamp"] == 123456


def test_zero_is_a_valid_structural_boundary():
    data = {field: 0 for field in VOLTAGE_FIELDS}

    assert validate_battery_data(data) == data


def test_top_level_non_object_is_rejected():
    with pytest.raises(BatteryDataValidationError, match="必须是 JSON 对象"):
        validate_battery_data([3.2, 3.2, 2.11, 8.51])


@pytest.mark.parametrize("missing_field", VOLTAGE_FIELDS)
def test_missing_required_field_is_rejected(missing_field):
    data = valid_battery_data()
    data.pop(missing_field)

    with pytest.raises(BatteryDataValidationError, match=missing_field):
        validate_battery_data(data)


@pytest.mark.parametrize("invalid_value", ["3.2", True, None, []])
def test_non_numeric_voltage_is_rejected(invalid_value):
    data = valid_battery_data()
    data["cell1"] = invalid_value

    with pytest.raises(BatteryDataValidationError, match="cell1 必须是数字"):
        validate_battery_data(data)


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_voltage_is_rejected(invalid_value):
    data = valid_battery_data()
    data["cell1"] = invalid_value

    with pytest.raises(BatteryDataValidationError, match="cell1 必须是有限数字"):
        validate_battery_data(data)


def test_negative_voltage_is_rejected():
    data = valid_battery_data()
    data["cell2"] = -0.01

    with pytest.raises(BatteryDataValidationError, match="cell2 不能小于 0"):
        validate_battery_data(data)


def test_inconsistent_total_voltage_is_rejected():
    data = valid_battery_data()
    data["total_vol"] = 9.99

    with pytest.raises(BatteryDataValidationError, match="total_vol.*不一致"):
        validate_battery_data(data)


def test_total_voltage_uses_two_decimal_rounding():
    data = {
        "cell1": 3.333,
        "cell2": 3.333,
        "cell3": 3.333,
        "total_vol": 10.0,
    }

    assert validate_battery_data(data) == data


def test_reader_returns_validated_latest_data(tmp_path, monkeypatch):
    log_path = tmp_path / "car_data_log.txt"
    data = valid_battery_data()
    log_path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    monkeypatch.setattr(config.path, "car_data_log", str(log_path))

    assert get_latest_battery_data() == data


def test_reader_returns_clear_error_for_invalid_data(tmp_path, monkeypatch):
    log_path = tmp_path / "car_data_log.txt"
    invalid_data = {**valid_battery_data(), "total_vol": 99}
    log_path.write_text(json.dumps(invalid_data) + "\n", encoding="utf-8")
    monkeypatch.setattr(config.path, "car_data_log", str(log_path))

    result = get_latest_battery_data()

    assert "error" in result
    assert "不一致" in result["error"]


def test_reader_returns_clear_error_when_log_is_missing(tmp_path, monkeypatch):
    missing_log = tmp_path / "missing.txt"
    monkeypatch.setattr(config.path, "car_data_log", str(missing_log))

    result = get_latest_battery_data()

    assert "日志不存在" in result["error"]


@pytest.mark.parametrize(
    ("file_content", "expected_message"),
    [("", "日志为空"), ("not-json\n", "不是有效的 JSON")],
)
def test_reader_returns_clear_error_for_unreadable_content(
    tmp_path,
    monkeypatch,
    file_content,
    expected_message,
):
    log_path = tmp_path / "car_data_log.txt"
    log_path.write_text(file_content, encoding="utf-8")
    monkeypatch.setattr(config.path, "car_data_log", str(log_path))

    result = get_latest_battery_data()

    assert expected_message in result["error"]


def test_invalid_serial_data_is_not_written(tmp_path):
    log_path = tmp_path / "car_data_log.txt"
    original_content = json.dumps(valid_battery_data()) + "\n"
    log_path.write_text(original_content, encoding="utf-8")
    invalid_line = json.dumps({**valid_battery_data(), "cell1": "3.2"})

    with pytest.raises(BatteryDataValidationError, match="cell1 必须是数字"):
        store_battery_line(invalid_line, log_path)

    assert log_path.read_text(encoding="utf-8") == original_content


def test_valid_serial_data_is_written(tmp_path):
    log_path = tmp_path / "nested" / "car_data_log.txt"
    data = {**valid_battery_data(), "source": "esp32"}

    result = store_battery_line(json.dumps(data), log_path)

    assert result == data
    assert json.loads(log_path.read_text(encoding="utf-8")) == data
