# Agent 可调用的历史案例检索工具

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_registry import Tool

def create_memory_tools(memory):
    """创建并返回历史案例检索工具列表
    参数 memory: 一个已初始化的 LongTermMemory 实例（由 main_agent.py 传入）
    """
    tools = []

    #闭包：内层函数捕获外层的 memory
    def search_history_cases(query: str) -> str:
        """搜索历史维修案例"""
        cases = memory.search(query)
        if not cases:
            return "暂无相关历史维修案例"
        return "\n\n".join(cases)

    tool = Tool(
        name="search_history_cases",
        description="搜索历史维修案例库，输入故障描述，返回之前类似的维修记录和解决方案",
        func= search_history_cases,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "故障描述或关键词"
                }
            },
            "required": ["query"]
        }
    )
    tools.append(tool)
    return tools
