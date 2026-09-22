"""电池测量数据的结构契约。"""

import math
from collections.abc import Mapping
from typing import Any


VOLTAGE_FIELDS = ("cell1", "cell2", "cell3", "total_vol")


class BatteryDataValidationError(ValueError):
    """电池测量数据不满足结构契约。"""


def validate_battery_data(data: object) -> dict[str, Any]:
    """校验并复制一条电池测量数据，不判断电压是否属于正常业务范围。"""
    if not isinstance(data, Mapping):
        raise BatteryDataValidationError("电池测量数据必须是 JSON 对象")

    missing_fields = [field for field in VOLTAGE_FIELDS if field not in data]
    if missing_fields:
        raise BatteryDataValidationError(
            f"缺少必填字段: {', '.join(missing_fields)}"
        )

    for field in VOLTAGE_FIELDS:
        value = data[field]
        # bool 是 int 的子类，必须在 int/float 判断中显式排除。
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BatteryDataValidationError(f"{field} 必须是数字")
        # int 本身没有 NaN/Infinity；只需检查 float 的非有限值。
        if isinstance(value, float) and not math.isfinite(value):
            raise BatteryDataValidationError(f"{field} 必须是有限数字")
        if value < 0:
            raise BatteryDataValidationError(f"{field} 不能小于 0")

    expected_total = round(data["cell1"] + data["cell2"] + data["cell3"], 2)
    actual_total = round(data["total_vol"], 2)
    if actual_total != expected_total:
        raise BatteryDataValidationError(
            "total_vol 与三个电芯电压之和不一致，"
            f"按两位小数计算应为 {expected_total:.2f}"
        )

    # 返回浅拷贝，避免校验函数修改调用方传入的数据，并保留额外元数据。
    return dict(data)
