"""工具契约覆盖参数、执行、输出及评测消费者。"""

import json

import pytest

from ebike_ai.core.tool_registry import Tool, ToolRegistry, SearchArguments, ToolResult
from ebike_ai.evaluation.judges import HallucinationJudge, ToolCallJudge
from ebike_ai.evaluation.metrics import tool_success_rate
from ebike_ai.tools.hardware_tools import create_hardware_tools
from ebike_ai.tools.knowledge_tools import create_knowledge_tools

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("arguments", [{}, {"query": 5}, {"query": " "},
    {"query": "x" * 501}, {"query": "故障", "extra": 1}, None, [], "故障"])
def test_invalid_arguments_never_execute_tool(arguments):
    calls = []
    registry = ToolRegistry()
    registry.register(Tool("search", "测试检索", lambda **kw: calls.append(kw), args_model=SearchArguments))
    result = json.loads(registry.execute("search", arguments))
    assert result["ok"] is False
    assert result["error"]["code"] == "TOOL_ARGUMENTS_INVALID"
    assert calls == []


def test_unknown_tool_and_extra_arguments_are_rejected():
    registry = ToolRegistry()
    registry.register(Tool("empty", "无参数", lambda: "正常"))
    assert json.loads(registry.execute("unknown", {}))["error"]["code"] == "TOOL_NOT_FOUND"
    assert json.loads(registry.execute("empty", {"query": "多余"}))["ok"] is False


@pytest.mark.parametrize("data", ["", [], {}, None, "检索结果"])
def test_empty_results_are_successful_and_serializable(data):
    registry = ToolRegistry()
    registry.register(Tool("read", "读取", lambda: data))
    assert json.loads(registry.execute("read", {})) == {"ok": True, "data": data, "error": None}


@pytest.mark.parametrize("result, code", [
    ({"error": "不应传播的内部信息"}, "TOOL_DATA_UNAVAILABLE"),
    (object(), "TOOL_OUTPUT_INVALID"), (float("nan"), "TOOL_OUTPUT_INVALID"),
])
def test_failed_or_invalid_outputs_are_not_success(result, code):
    registry = ToolRegistry()
    registry.register(Tool("read", "读取", lambda: result))
    output = registry.execute("read", {})
    assert json.loads(output)["error"]["code"] == code
    assert "不应传播" not in output


def test_tool_exception_is_sanitized():
    def broken():
        raise RuntimeError("Authorization: Bearer synthetic-secret")
    registry = ToolRegistry()
    registry.register(Tool("broken", "失败工具", broken))
    output = registry.execute("broken", {})
    assert json.loads(output)["error"]["code"] == "TOOL_EXECUTION_FAILED"
    assert "synthetic-secret" not in output and "Authorization" not in output


def test_production_output_validators_reject_wrong_types():
    registry = ToolRegistry()
    hardware = create_hardware_tools()[0]
    hardware.func = lambda: {"cell1": 3, "cell2": 3, "cell3": 3, "total_vol": 99}
    registry.register(hardware)
    knowledge = create_knowledge_tools()[0]
    knowledge.func = lambda query: {"not": "text"}
    registry.register(knowledge)
    for name, args in [(hardware.name, {}), (knowledge.name, {"query": "故障"})]:
        assert json.loads(registry.execute(name, args))["error"]["code"] == "TOOL_OUTPUT_INVALID"


def test_failure_trace_does_not_pass_tool_judge():
    trace = [{"name": "get_battery_data", "success": False}]
    result = ToolCallJudge().judge({"expect_tool": "get_battery_data"}, "", {"tool_trace": trace})
    assert result["passed"] is False
    assert tool_success_rate(trace) == 0


def test_hallucination_judge_uses_data_instead_of_envelope():
    prompts = []
    class JudgeLLM:
        def invoke(self, prompt):
            prompts.append(prompt)
            return type("Reply", (), {"content": "无幻觉"})()
    state = {"retrieved_docs": ToolResult(ok=True, data="已核对的维修资料").to_json()}
    HallucinationJudge(JudgeLLM()).judge({"hardware_data": {}}, "待确认建议", state)
    assert "已核对的维修资料" in prompts[0]
    assert '"ok"' not in prompts[0]
