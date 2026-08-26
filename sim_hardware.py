import json
import os
import time
from config import config

def simulate_esp32_data():
    # 无限循环，模拟硬件每秒发一组电压
    while True:
        # 定义模拟电池数据：3串锂电电压+总电压
        battery_data = {
            "cell1": round(3.2+0.06*time.time()%1,2),
            "cell2": round(3.2+0.05*time.time()%1,2),
            "cell3": round(2.11,2),
            "total_vol":round(3.26+3.25+2.11,2)
        }
        # json.dumps：字典转字符串，和硬件输出格式统一
        data_str = json.dumps(battery_data)
        print("模拟硬件下发数据:",data_str)

        # 确保 logs 目录存在，再写入
        os.makedirs(os.path.dirname(config.path.car_data_log), exist_ok=True)
        with open(config.path.car_data_log,"a",encoding="utf-8") as f:
            f.write(data_str+"\n")
        time.sleep(1) # 间隔1秒，模拟硬件1秒上传一次
         
# 程序入口固定写法，只有直接运行本文件才执行函数
if __name__ == "__main__":
    simulate_esp32_data()