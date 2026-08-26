# conftest.py - pytest 全局配置 + 共享 fixture
# 作用1：确保 test_cases/ 子目录能 import 项目根目录的模块
# 作用2：提供 llm / registry / agent 三个共享 fixture，避免每个测试重复写初始化代码

import sys
import os
import pytest

# 1. 先把项目根目录加进 Python 搜索路径（必须在 import 项目模块之前）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 2. 再 import 项目模块
from langchain_community.chat_models import ChatTongyi
from config import config
from core.tool_registry import ToolRegistry
from core.react_loop import AgentLoop
from tools.hardware_tools import create_hardware_tools
from tools.knowledge_tools import create_knowledge_tools


@pytest.fixture(scope="module")
def llm():
    """模块级 LLM：一个测试文件只初始化一次，所有测试复用同一个对象"""
    # 没配 API key 就跳过，而不是报一堆鉴权错误
    if not config.llm.api_key:
        pytest.skip("未设置 DASHSCOPE_API_KEY，跳过需要真实 LLM 的测试")
    return ChatTongyi(
        model=config.llm.model,
        dashscope_api_key=config.llm.api_key,
        temperature=config.llm.temperature,
        model_kwargs={"max_tokens": config.llm.max_tokens},
    )


@pytest.fixture(scope="module")
def registry():
    """模块级工具注册中心：工具只注册一次"""
    reg = ToolRegistry()
    for tool in create_hardware_tools():
        reg.register(tool)
    for tool in create_knowledge_tools():
        reg.register(tool)
    return reg


@pytest.fixture()  # 默认 function 级别：每个测试一个全新 Agent，避免短期记忆串味
def agent(llm, registry):
    """函数级 Agent：由 llm + registry 组装，每个测试独立"""
    return AgentLoop(llm=llm, registry=registry, max_iter=10)
