"""不联网地验证错误边界、SDK 传输参数、重试次数及失败状态。"""

from copy import deepcopy
import json
import logging

import pytest
import requests
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_community.chat_models import ChatTongyi

from ebike_ai import api
from ebike_ai.agent_factory import build_agent, build_llm
from ebike_ai.config import config
from ebike_ai.core import failures
from ebike_ai.core.failures import DiagnosisError
from ebike_ai.core.react_loop import AgentLoop
from ebike_ai.core.tool_registry import Tool, ToolRegistry
from ebike_ai.evaluation.metrics import max_iter_reached

pytestmark = pytest.mark.integration


class ScriptedLLM:
    """按固定顺序返回响应或抛异常，并保存调用输入。"""
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.inputs = []

    def bind_tools(self, schemas):
        return self

    def invoke(self, messages):
        self.inputs.append(deepcopy(messages))
        result = next(self.outcomes)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(failures.time, "sleep", calls.append)
    monkeypatch.setattr(config.llm, "max_attempts", 2)
    monkeypatch.setattr(config.llm, "retry_delay", 1)
    return calls


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError(),
    requests.exceptions.ReadTimeout(), requests.exceptions.ConnectionError(),
    requests.HTTPError(response={"status_code": 429}), requests.HTTPError(response={"status_code": 503})])
def test_transient_failure_retries_once_then_succeeds(error, sleeps):
    llm = ScriptedLLM([error, AIMessage(content="正常回答")])
    answer, state = build_agent(llm=llm).run("故障")
    assert answer == "正常回答" and state["status"] == "completed"
    assert len(llm.inputs) == 2 and sleeps == [1]


@pytest.mark.parametrize("error", [ValueError("鉴权或参数错误"),
    requests.HTTPError(response={"status_code": 400}),
    requests.HTTPError(response={"status_code": 401}),
    requests.HTTPError(response={"status_code": 403}), requests.exceptions.SSLError()])
def test_permanent_failures_are_not_retried(error, sleeps):
    llm = ScriptedLLM([error])
    agent = build_agent(llm=llm)
    with pytest.raises(DiagnosisError) as caught:
        agent.run("故障")
    assert caught.value.code == "MODEL_UNAVAILABLE"
    assert len(llm.inputs) == 1 and sleeps == []
    assert not agent.memory.buffer


def test_timeout_exhaustion_is_bounded_and_does_not_save_history(sleeps):
    llm = ScriptedLLM([TimeoutError("synthetic-secret"), TimeoutError("synthetic-secret")])
    agent = build_agent(llm=llm)
    with pytest.raises(DiagnosisError) as caught:
        agent.run("故障")
    assert caught.value.code == "MODEL_TIMEOUT"
    assert caught.value.state["status"] == "failed"
    assert caught.value.state["final_answer"] == ""
    assert len(llm.inputs) == 2 and sleeps == [1]
    assert "synthetic-secret" not in str(caught.value)
    assert not agent.memory.buffer


@pytest.mark.parametrize("status, code", [(422, "INPUT_INVALID"), (503, "MODEL_NOT_CONFIGURED"),
    (504, "MODEL_TIMEOUT"), (502, "MODEL_RESPONSE_INVALID"), (500, "INTERNAL_ERROR")])
@pytest.mark.integration
def test_api_has_stable_sanitized_errors(monkeypatch, caplog, status, code):
    def factory():
        if code == "INTERNAL_ERROR":
            raise RuntimeError("Authorization: Bearer synthetic-secret")
        raise DiagnosisError(code)
    monkeypatch.setattr(api, "build_agent", factory)
    with TestClient(api.app) as client:
        response = client.post("/diagnose", json={"fault_text": " " if status == 422 else "故障"})
    assert response.status_code == status
    assert response.json()["detail"] == DiagnosisError(code).detail()
    assert "synthetic-secret" not in response.text + caplog.text
    assert "Authorization" not in response.text + caplog.text


def test_missing_key_does_not_build_client(monkeypatch):
    monkeypatch.setattr(config.llm, "api_key", "")
    from ebike_ai import agent_factory
    monkeypatch.setattr(agent_factory, "ChatTongyi", lambda **kwargs: pytest.fail("不应创建客户端"))
    with pytest.raises(DiagnosisError) as caught:
        build_llm()
    assert caught.value.code == "MODEL_NOT_CONFIGURED"


def sdk_response(content="假模型结果", tool_calls=None):
    """使用 SDK 的真实解析器，只替换最底层 HTTP 响应。"""
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "application/json"
    response._content = json.dumps({"request_id": "offline-test", "usage": {}, "output": {
        "choices": [{"finish_reason": "stop", "message": message}],
    }}).encode()
    return response


@pytest.mark.integration
def test_real_sdk_receives_timeout_and_has_no_nested_retries(monkeypatch, sleeps, caplog):
    monkeypatch.setattr(config.llm, "api_key", "offline-placeholder")
    monkeypatch.setattr(config.llm, "request_timeout", 7)
    requests_seen = []
    def request(self, method, url, **kwargs):
        requests_seen.append(kwargs["timeout"])
        # 模拟 SDK 调试日志，即使启用 DEBUG 也不能输出异常内容。
        logging.getLogger("dashscope").debug("Authorization: Bearer synthetic-secret")
        raise requests.exceptions.ReadTimeout("Authorization: Bearer synthetic-secret")
    monkeypatch.setattr(requests.Session, "request", request)
    with caplog.at_level(logging.DEBUG, logger="dashscope"):
        with pytest.raises(DiagnosisError) as caught:
            build_agent().run("故障")
    assert caught.value.code == "MODEL_TIMEOUT"
    assert requests_seen == [7, 7] and sleeps == [1]
    assert "synthetic-secret" not in caplog.text


@pytest.mark.integration
def test_actual_sdk_tool_message_round_trip(monkeypatch):
    monkeypatch.setattr(config.llm, "api_key", "offline-placeholder")
    payloads = []
    def request(self, method, url, **kwargs):
        payloads.append(kwargs["json"])
        if len(payloads) == 1:
            return sdk_response("", [{"id": "call-1", "type": "function", "function": {
                "name": "echo", "arguments": "{}",
            }}])
        return sdk_response()
    monkeypatch.setattr(requests.Session, "request", request)
    registry = ToolRegistry()
    registry.register(Tool("echo", "离线回显", lambda: {"value": "固定证据"}))
    answer, state = build_agent(registry=registry).run("故障")
    assert answer == "假模型结果" and state["tool_trace"][0]["success"]
    messages = payloads[1]["input"]["messages"]
    assert messages[-2]["role"] == "assistant"
    assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "call-1"
    assert json.loads(messages[-1]["content"])["data"] == {"value": "固定证据"}


@pytest.mark.parametrize("status, attempts", [(401, 1), (403, 1), (429, 2), (503, 2)])
def test_injected_sdk_client_has_bounded_http_retries_without_mutation(monkeypatch, sleeps, status, attempts):
    seen = []
    def request(self, method, url, **kwargs):
        seen.append(kwargs["timeout"])
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps({"code": "TestError", "message": "synthetic-secret",
                                        "request_id": "offline"}).encode()
        return response
    monkeypatch.setattr(requests.Session, "request", request)
    original = ChatTongyi(model="qwen-plus", api_key="offline-placeholder", max_retries=7)
    with pytest.raises(DiagnosisError) as caught:
        build_agent(llm=original).run("故障")
    assert caught.value.code == "MODEL_UNAVAILABLE"
    assert seen == [config.llm.request_timeout] * attempts
    assert original.max_retries == 7 and "request_timeout" not in original.model_kwargs
    assert len(sleeps) == attempts - 1


def test_iteration_exhaustion_preserves_trace_and_is_not_network_timeout():
    response = AIMessage(content="", tool_calls=[{"id": "loop", "name": "echo", "args": {}}])
    llm = ScriptedLLM([response, response])
    registry = ToolRegistry()
    registry.register(Tool("echo", "固定工具", lambda: "成功"))
    agent = build_agent(llm=llm, registry=registry, max_iter=2)
    with pytest.raises(DiagnosisError) as caught:
        agent.run("故障")
    assert caught.value.code == "AGENT_ITERATION_LIMIT"
    assert len(caught.value.state["tool_trace"]) == 2
    assert max_iter_reached(caught.value.state)
    assert not agent.memory.buffer


def test_last_iteration_can_complete_successfully():
    agent = build_agent(llm=ScriptedLLM([AIMessage(content="完成")]), max_iter=1)
    _, state = agent.run("故障")
    assert not max_iter_reached(state, max_iter=1)


@pytest.mark.parametrize("name, result, code", [
    ("missing", "unused", "TOOL_NOT_FOUND"),
    ("read", {"error": "synthetic-secret"}, "TOOL_DATA_UNAVAILABLE"),
    ("read", TimeoutError(), "TOOL_TIMEOUT"),
    ("read", RuntimeError("synthetic-secret"), "TOOL_EXECUTION_FAILED"),
])
def test_failed_tools_stop_before_model_can_invent_answer(name, result, code):
    def read():
        if isinstance(result, Exception):
            raise result
        return result
    registry = ToolRegistry()
    registry.register(Tool("read", "数据读取", read))
    llm = ScriptedLLM([AIMessage(content="", tool_calls=[{"id": "1", "name": name, "args": {}}])])
    agent = build_agent(llm=llm, registry=registry)
    with pytest.raises(DiagnosisError) as caught:
        agent.run("故障")
    assert caught.value.code == code
    assert caught.value.state["tool_trace"][0]["success"] is False
    assert len(llm.inputs) == 1 and not agent.memory.buffer
    assert "synthetic-secret" not in str(caught.value.state)


def test_empty_knowledge_has_deterministic_human_review_fallback():
    registry = ToolRegistry()
    registry.register(Tool("search_repair_knowledge", "检索", lambda: ""))
    llm = ScriptedLLM([AIMessage(content="", tool_calls=[
        {"id": "1", "name": "search_repair_knowledge", "args": {}},
    ])])
    answer, state = build_agent(llm=llm, registry=registry).run("故障")
    assert "证据不足" in answer and "复检" in answer
    assert state["status"] == "insufficient_evidence" and state["tool_trace"][0]["success"]
    assert len(llm.inputs) == 1


@pytest.mark.parametrize("tool_calls", [[{"name": "echo", "args": {}}], "invalid", [
    {"id": "same", "name": "echo", "args": {}}, {"id": "same", "name": "echo", "args": {}},
]])
def test_malformed_tool_protocol_does_not_execute(tool_calls):
    response = type("Reply", (), {"content": "", "tool_calls": tool_calls})()
    registry = ToolRegistry()
    registry.register(Tool("echo", "不应执行", lambda: pytest.fail("不应执行畸形调用")))
    with pytest.raises(DiagnosisError) as caught:
        build_agent(llm=ScriptedLLM([response]), registry=registry).run("故障")
    assert caught.value.code == "MODEL_RESPONSE_INVALID"
