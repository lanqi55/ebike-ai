# read_hardware, calc_voltage_diff

import serial
import json
import time
from pathlib import Path

from ebike_ai.battery_data import (
    BatteryDataValidationError,
    validate_battery_data,
)
from ebike_ai.config import config


# 回家后仅修改这两个参数即可
SERIAL_PORT = "COM3"
BAUD_RATE = 115200


def store_battery_line(line: str, log_path=None) -> dict:
    """校验一行串口 JSON，只有合法数据才追加到硬件日志。"""
    try:
        battery_dict = json.loads(line)
    except json.JSONDecodeError as exc:
        raise BatteryDataValidationError("串口数据不是有效的 JSON") from exc

    validated_data = validate_battery_data(battery_dict)
    target_path = Path(log_path or config.path.car_data_log)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(validated_data, ensure_ascii=False) + "\n")
    return validated_data


def read_esp32_serial():
    ser = None
    try:
        # 初始化串口对象
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.5)
        print(f"串口 {SERIAL_PORT} 连接成功，开始接收硬件电压数据（Ctrl+C 停止）")
    except Exception as e:
        print(f"串口打开失败，检查端口号、接线、ESP32是否上电\n"
              f"  当前设置: 端口={SERIAL_PORT}, 波特率={BAUD_RATE}\n"
              f"  错误详情: {e}")
        return

    try:
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                # 只解析JSON格式数据，过滤掉ESP32的启动日志和乱码
                if line.startswith("{") and line.endswith("}"):
                    try:
                        battery_dict = store_battery_line(line)
                        print("ESP32真实采集电压：", battery_dict)
                    except BatteryDataValidationError as exc:
                        print(f"忽略无效电池数据：{exc}")
                        continue
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n用户停止采集")
    finally:
        if ser is not None and ser.is_open:
            ser.close()
            print(f"串口 {SERIAL_PORT} 已关闭")



if __name__ == "__main__":
    read_esp32_serial()
