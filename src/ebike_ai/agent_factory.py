"""API 与命令行共用的 Agent 组装入口；导入时不创建客户端。"""

from langchain_community.chat_models import ChatTongyi

from ebike_ai.config import config
from ebike_ai.core.react_loop import AgentLoop
from ebike_ai.core.tool_registry import ToolRegistry
from ebike_ai.core.failures import DiagnosisError
from ebike_ai.utils.logger import protect_sdk_logs
from ebike_ai.tools.hardware_tools import create_hardware_tools
from ebike_ai.tools.knowledge_tools import create_knowledge_tools


def build_llm():
    """设置传输超时并关闭 SDK 包装层重试，统一由 Agent 限制尝试次数。"""
    if not config.llm.api_key.strip():
        raise DiagnosisError("MODEL_NOT_CONFIGURED")
    protect_sdk_logs()
    return ChatTongyi(
        model=config.llm.model,
        dashscope_api_key=config.llm.api_key,
        max_retries=1,
        model_kwargs={
            "max_tokens": config.llm.max_tokens,
            "temperature": config.llm.temperature,
            "request_timeout": config.llm.request_timeout,
        },
    )


def build_registry() -> ToolRegistry:
    """仅注册测量和维修知识工具；旧历史库尚未完成人工可信性整理。"""
    registry = ToolRegistry()
    for tool in [*create_hardware_tools(), *create_knowledge_tools()]:
        registry.register(tool)
    return registry


def build_agent(*, llm=None, registry=None, max_iter=10) -> AgentLoop:
    """每次返回独立 Agent；测试可注入模型和工具，无须访问外部服务。"""
    return AgentLoop(
        llm=build_llm() if llm is None else llm,
        registry=build_registry() if registry is None else registry,
        max_iter=max_iter,
    )
