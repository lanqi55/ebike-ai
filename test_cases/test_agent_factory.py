"""验证统一组装、命令行会话边界以及禁止自动保存案例。"""

import os
import subprocess
import sys

import pytest
from langchain_core.messages import AIMessage

from ebike_ai import agent_factory, api, main_agent
from ebike_ai.core.memory import LongTermMemory

pytestmark = pytest.mark.unit


class RecordingLLM:
    def __init__(self):
        self.inputs = []

    def bind_tools(self, schemas):
        self.schemas = schemas
        return self

    def invoke(self, messages):
        self.inputs.append(messages)
        if messages[-1]["content"] == "失败":
            raise ValueError("模拟错误")
        return AIMessage(content="待人工确认的建议")


def test_both_entrypoints_use_same_factory_and_only_registered_tools():
    assert api.build_agent is main_agent.build_agent is agent_factory.build_agent
    first, second = RecordingLLM(), RecordingLLM()
    a = api.build_agent(llm=first)
    b = main_agent.build_agent(llm=second)
    assert a is not b and a.memory is not b.memory and a.registry is not b.registry
    assert first.schemas == second.schemas
    assert {s["function"]["name"] for s in first.schemas} == {
        "get_battery_data", "search_repair_knowledge",
    }
    a.run("测试")
    assert "search_history_cases" not in first.inputs[0][0]["content"]


def test_cli_keeps_only_successful_short_term_history_without_long_term_writes(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("诊断不应初始化或写入长期案例库")

    monkeypatch.setattr(LongTermMemory, "__init__", forbidden)
    monkeypatch.setattr(LongTermMemory, "add_case", forbidden)
    llm = RecordingLLM()
    agent = agent_factory.build_agent(llm=llm)
    queries = iter(["车辆甲", "失败", "继续检查", "quit"])
    output = []
    main_agent.run_cli(agent_factory=lambda: agent, input_func=lambda _: next(queries), output_func=output.append)
    assert [turn["user"] for turn in agent.memory.buffer] == ["车辆甲", "继续检查"]
    assert "车辆甲" in str(llm.inputs[-1])
    assert any("诊断失败" in item for item in output)
    assert "模拟错误" not in str(output)


def test_import_entrypoints_does_not_connect_or_initialize_vector_store():
    code = '''
import socket
def forbidden(*args, **kwargs):
    raise AssertionError("unexpected external initialization")
socket.socket.connect = forbidden
from ebike_ai.core.memory import LongTermMemory
from langchain_community.chat_models import ChatTongyi
LongTermMemory.__init__ = forbidden
ChatTongyi.__init__ = forbidden
import ebike_ai.api
import ebike_ai.main_agent
'''
    env = os.environ.copy()
    env.pop("DASHSCOPE_API_KEY", None)
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
