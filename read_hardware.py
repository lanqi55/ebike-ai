import json
from config import config

def get_latest_battery_data():
    try:
        # 只读模式打开日志文件（用 config 的绝对路径，不依赖运行目录）
        with open(config.path.car_data_log, 'r', encoding="utf-8") as f:
            all_lines = f.readlines()
            if(len(all_lines) == 0):
                return None
            # 获取最后一行最新数据
            last_line = all_lines[-1].strip()
            # 字符串转回Python字典
            battery_dict = json.loads(last_line)
            return battery_dict
    except FileNotFoundError:
        print("日志文件不存在，请先运行sim_hardware.py生成数据")
        return None

if __name__ == "__main__":
    result = get_latest_battery_data()
    if result:
        print("解析后的数据字典",result)
        print("第一串电芯电压",result["cell1"])
        print("总电压:",result["total_vol"])
