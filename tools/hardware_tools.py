# Agent 可调用的硬件工具
# 基于 read_hardware.py 封装为 Tool 对象

import sys
import os
# 确保能 import 项目根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from read_hardware import get_latest_battery_data
from core.tool_registry import Tool


def create_hardware_tools():
    """创建并返回所有硬件相关工具的列表"""
    tools = []

    # 工具1：读电池电压
    tool1 = Tool(
        name="get_battery_data",
        description="读取电动车电池的最新电压数据，包括每串电芯和总电压",
        func=get_latest_battery_data,
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    tools.append(tool1)

    return tools
