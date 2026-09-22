import json

from ebike_ai.battery_data import (
    BatteryDataValidationError,
    validate_battery_data,
)
from ebike_ai.config import config


def get_latest_battery_data() -> dict:
    try:
        # 只读模式打开日志文件（用 config 的绝对路径，不依赖运行目录）
        with open(config.path.car_data_log, 'r', encoding="utf-8") as f:
            all_lines = f.readlines()
            if not all_lines:
                return {"error": "硬件数据日志为空，请先生成或采集数据"}
            # 获取最后一行最新数据
            last_line = all_lines[-1].strip()
            # 字符串转回Python字典
            battery_dict = json.loads(last_line)
            return validate_battery_data(battery_dict)
    except FileNotFoundError:
        return {"error": "硬件数据日志不存在，请先生成或采集数据"}
    except json.JSONDecodeError:
        return {"error": "最新硬件数据不是有效的 JSON"}
    except BatteryDataValidationError as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    result = get_latest_battery_data()
    if "error" in result:
        print("读取失败:", result["error"])
    else:
        print("解析后的数据字典", result)
        print("第一串电芯电压", result["cell1"])
        print("总电压:", result["total_vol"])
