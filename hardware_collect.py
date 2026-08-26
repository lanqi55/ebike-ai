# read_hardware, calc_voltage_diff

import serial
import json
import time
from config import config


# 回家后仅修改这两个参数即可
SERIAL_PORT = "COM3"
BAUD_RATE = 115200

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
                        battery_dict = json.loads(line)
                        print("ESP32真实采集电压：", battery_dict)
                        # 写入和 sim_hardware.py 完全相同的格式
                        with open(config.path.car_data_log, "a", encoding="utf-8") as f:
                            f.write(json.dumps(battery_dict, ensure_ascii=False) + "\n")
                    except json.JSONDecodeError:
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