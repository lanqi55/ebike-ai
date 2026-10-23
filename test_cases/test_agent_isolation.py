"""使用真实 AgentLoop 和假模型验证请求之间的上下文隔离。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from ebike_ai import api
from ebike_ai.core.react_loop import AgentLoop
from ebike_ai.core.tool_registry import Tool, ToolRegistry, SearchArguments

pytestmark = pytest.mark.integration


def make_agent(observed, barrier=None, fail_query=None):
    """每个 Agent 有独立模型；观测列表只用于收集测试证据。"""
    class FakeLLM:
        def __init__(self):
            self.inputs = []

        def bind_tools(self, schemas):
            return self

        def invoke(self, messages):
            self.inputs.append(deepcopy(messages))
            query = next(m["content"] for m in reversed(messages) if m.get("role") == "user")
            if len(self.inputs) == 1 and barrier is not None:
                barrier.wait(timeout=10)
            if query == fail_query:
                raise ValueError("模拟请求失败")
            if messages[-1]["role"] != "tool":
                return AIMessage(content="", tool_calls=[
                    {"id": "echo-1", "name": "echo", "args": {"query": query}}
                ])
            return AIMessage(content=f"结果：{query}")

    llm = FakeLLM()
    observed.append(llm)
    registry = ToolRegistry()
    registry.register(Tool("echo", "回显测试输入", lambda query: {"query": query},
                           args_model=SearchArguments))
    return AgentLoop(llm, registry)


def test_shared_agent_reproduces_old_history_leak():
    """顺序复用对象也会带入历史，因此仅加锁无法隔离不同用户。"""
    observed = []
    agent = make_agent(observed)
    agent.run("车辆甲")
    agent.run("车辆乙")
    assert "车辆甲" in str(observed[0].inputs[2])


def test_api_sequential_requests_have_fresh_memory(monkeypatch):
    observed = []
    monkeypatch.setattr(api, "build_agent", lambda: make_agent(observed))
    with TestClient(api.app) as client:
        first = client.post("/diagnose", json={"fault_text": "车辆甲"})
        second = client.post("/diagnose", json={"fault_text": "车辆乙"})
    assert first.status_code == second.status_code == 200
    assert len(observed) == 2
    assert "车辆甲" not in str(observed[1].inputs)
    assert second.json()["answer"] == "结果：车辆乙"
    assert second.json()["tool_trace"][0]["args"] == {"query": "车辆乙"}


@pytest.mark.parametrize("fail_query", [None, "车辆甲"])
def test_api_concurrent_requests_keep_inputs_answers_and_traces_separate(monkeypatch, fail_query):
    barrier = Barrier(2)
    observed = []
    lock = Lock()

    def factory():
        with lock:
            return make_agent(observed, barrier, fail_query)

    monkeypatch.setattr(api, "build_agent", factory)

    def request(query):
        with TestClient(api.app) as client:
            return client.post("/diagnose", json={"fault_text": query})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(request, q) for q in ("车辆甲", "车辆乙")]
        first, second = [f.result(timeout=20) for f in futures]
    assert first.status_code == (503 if fail_query else 200)
    assert second.status_code == 200
    assert len(observed) == 2
    for model in observed:
        query = model.inputs[0][-1]["content"]
        other = "车辆乙" if query == "车辆甲" else "车辆甲"
        assert other not in str(model.inputs)
    for response, query in ((first, "车辆甲"), (second, "车辆乙")):
        if response.status_code == 200:
            assert response.json()["answer"] == f"结果：{query}"
            assert [t["args"] for t in response.json()["tool_trace"]] == [{"query": query}]
