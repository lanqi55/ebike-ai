"""阈值仅为算法测试用合成值，不是维修标准。"""

import pytest
from pydantic import ValidationError

from ebike_ai.voltage_rules import VoltageRule, battery_data_with_rules, evaluate_voltage_rules

pytestmark = pytest.mark.unit


def sample(value=3.0):
    return {"cell1": value, "cell2": 3.0, "cell3": 3.0, "total_vol": round(value + 6, 2)}


CONTEXT = {"battery_type": "离线合成类型", "series_count": 3, "measurement_condition": "合成条件"}


def rule(**changes):
    return VoltageRule(**{**CONTEXT, "rule_id": "synthetic-only", "minimum": 2.0, "maximum": 4.0,
                         "source": "仅验证算法的合成阈值，不可用于维修", "version": "test-v1",
                         "confirmed": True, **changes})


@pytest.mark.parametrize("value,status", [(1.99, "matched"), (2.0, "passed"), (4.0, "passed"), (4.01, "matched")])
def test_synthetic_boundaries_are_inclusive(value, status):
    result = evaluate_voltage_rules(sample(value), context=CONTEXT, rules=[rule()])
    assert result["status"] == status
    assert result["rule_ids"] == ["synthetic-only"]
    assert "test-v1" in result["basis"][-1]
    assert bool(result["findings"]) == (status == "matched")


@pytest.mark.parametrize("measurement", [None, sample()])
def test_missing_evidence_never_implies_normal(measurement):
    result = evaluate_voltage_rules(measurement)
    assert result["status"] == "insufficient_evidence"
    assert result["missing_information"] and not result["rule_ids"]


@pytest.mark.parametrize("rules", [[], [rule(confirmed=False)], [rule(battery_type="其他类型")]])
def test_absent_unconfirmed_or_unrelated_threshold_does_not_execute(rules):
    assert evaluate_voltage_rules(sample(), context=CONTEXT, rules=rules)["status"] == "insufficient_evidence"


@pytest.mark.parametrize("count", [4, True, "3"])
def test_other_pack_and_invalid_series_count_are_not_applicable(count):
    assert evaluate_voltage_rules(sample(), context={**CONTEXT, "series_count": count}, rules=[rule()])["status"] == "not_applicable"


def test_inconsistent_total_and_conflicting_rules():
    assert evaluate_voltage_rules({**sample(), "total_vol": 99})["status"] == "invalid_data"
    result = evaluate_voltage_rules(sample(), context=CONTEXT, rules=[rule(), rule(rule_id="another", maximum=5.0)])
    assert result["status"] == "conflict" and len(result["rule_ids"]) == 2


@pytest.mark.parametrize("changes", [{"minimum": 5.0}, {"maximum": float("inf")}, {"source": " "}])
def test_invalid_rule_configuration_is_rejected(changes):
    with pytest.raises(ValidationError):
        rule(**changes)


def test_hardware_result_is_copied_and_untrusted_rule_result_is_overwritten():
    raw = {**sample(), "rule_result": {"status": "passed"}, "timestamp": 123}
    result = battery_data_with_rules(raw)
    assert raw["rule_result"]["status"] == "passed"
    assert result["rule_result"]["status"] == "insufficient_evidence"
    assert result["timestamp"] == 123 and result["total_vol"] == 9
