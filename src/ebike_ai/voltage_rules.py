"""纯函数电压规则：结构合法不代表电池正常，未确认阈值不执行。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ebike_ai.battery_data import BatteryDataValidationError, validate_battery_data


class VoltageRule(BaseModel):
    """经人工审核的单电芯电压区间；本项目暂未配置真实业务阈值。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    rule_id: str = Field(min_length=1)
    battery_type: str = Field(min_length=1)
    series_count: int = Field(gt=0)
    measurement_condition: str = Field(min_length=1)
    minimum: float = Field(ge=0)
    maximum: float = Field(ge=0)
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    confirmed: bool = False

    @model_validator(mode="after")
    def ordered_bounds(self):
        """拒绝颠倒的边界及仅包含空格的来源、适用条件。"""
        if self.minimum > self.maximum:
            raise ValueError("规则下限不能高于上限")
        if any(not value.strip() for value in (
            self.rule_id, self.battery_type, self.measurement_condition, self.source, self.version,
        )):
            raise ValueError("规则来源及适用条件不能为空")
        return self


class RuleResult(BaseModel):
    """独立规则证据；通过仅代表满足所选规则，不作安全结论。"""

    status: Literal["invalid_data", "insufficient_evidence", "not_applicable", "matched", "passed", "conflict"]
    rule_ids: list[str] = Field(default_factory=list)
    basis: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    limitation: str = "规则结果不是电池安全鉴定；三串数据不能默认代表当前实车。"


def evaluate_voltage_rules(measurement, *, context=None, rules=()) -> dict:
    """校验三串测量，再按明确的电池类型、串数和测量条件选择已确认规则。"""
    def result(status, **kwargs):
        return RuleResult(status=status, **kwargs).model_dump()

    if measurement is None:
        return result("insufficient_evidence", missing_information=["未提供电压测量记录"])
    try:
        data = validate_battery_data(measurement)
    except (BatteryDataValidationError, OverflowError):
        return result("invalid_data", basis=["三串测量结构或总电压一致性校验失败"])
    basis = ["三串测量结构及按两位小数计算的总电压一致性校验通过"]
    context = context if isinstance(context, dict) else {}
    required = ("battery_type", "series_count", "measurement_condition")
    missing = [key for key in required if context.get(key) in (None, "")]
    if missing:
        return result("insufficient_evidence", basis=basis, missing_information=missing)
    if type(context["series_count"]) is not int or context["series_count"] != 3:
        return result("not_applicable", basis=basis + ["现有测量契约仅支持明确的三串数据"])
    configured = [rule if isinstance(rule, VoltageRule) else VoltageRule.model_validate(rule) for rule in rules]
    applicable = [rule for rule in configured if rule.confirmed and all(
        getattr(rule, key) == context[key] for key in required
    )]
    if not applicable:
        return result("insufficient_evidence", basis=basis,
                      missing_information=["缺少适用于当前电池和测量条件、经维修师确认的规则阈值及来源"])
    ids = [rule.rule_id for rule in applicable]
    basis += [f"{rule.rule_id}: {rule.source}，版本 {rule.version}" for rule in applicable]
    # 同一上下文的不同区间不能静默择一，先要求人工消除配置冲突。
    if len({(rule.minimum, rule.maximum) for rule in applicable}) != 1:
        return result("conflict", rule_ids=ids, basis=basis,
                      missing_information=["同一适用条件的规则区间冲突，请维修师核对"])
    rule = applicable[0]
    findings = [f"{key}={data[key]}V 超出所选规则区间 [{rule.minimum}, {rule.maximum}]V"
                for key in ("cell1", "cell2", "cell3")
                if not rule.minimum <= data[key] <= rule.maximum]
    return result("matched" if findings else "passed", rule_ids=ids, basis=basis, findings=findings)


def battery_data_with_rules(raw):
    """硬件工具输出保留原字段，并附加服务端计算的规则结果，覆盖来路不明的同名字段。"""
    data = validate_battery_data(raw)
    # 日志与当前车辆尚无可信关联，因此不从任意日志字段激活业务规则。
    data["rule_result"] = evaluate_voltage_rules(data)
    return data
