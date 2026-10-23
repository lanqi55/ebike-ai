"""第四周离线演示：真实 HTTP 路由和 Agent，使用固定假模型及假工具。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest.mock import patch
import socket

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from ebike_ai import api
from ebike_ai.agent_factory import build_agent
from ebike_ai.core.tool_registry import SearchArguments, Tool, ToolRegistry


def demo_factory(observed, *, barrier=None, fail_query=None):
    """所有依赖固定在内存中，不读取硬件日志或向量库。"""
    class DemoModel:
        def __init__(self):
            self.inputs = []

        def bind_tools(self, schemas):
            return self

        def invoke(self, messages):
            self.inputs.append(deepcopy(messages))
            query = next(m["content"] for m in reversed(messages) if m.get("role") == "user")
            if barrier is not None and len(self.inputs) == 1:
                barrier.wait(timeout=10)
            if query == fail_query:
                raise ValueError("离线模拟服务不可用")
            if messages[-1]["role"] != "tool":
                return AIMessage(content="", tool_calls=[
                    {"id": "demo-1", "name": "echo", "args": {"query": query}},
                ])
            return AIMessage(content=f"离线演示结果：{query}；待人工确认。")

    model = DemoModel()
    observed.append(model)
    registry = ToolRegistry()
    registry.register(Tool("echo", "固定回显工具", lambda query: {"query": query}, args_model=SearchArguments))
    return build_agent(llm=model, registry=registry)


def post(query):
    """进程内 HTTP 请求，不启动端口或访问网络。"""
    with TestClient(api.app) as client:
        return client.post("/diagnose", json={"fault_text": query})


def check_response(response, query):
    """同时核对回答归属与实际执行的工具参数。"""
    assert response.status_code == 200
    assert response.json()["answer"] == f"离线演示结果：{query}；待人工确认。"
    assert response.json()["tool_trace"][0]["args"] == {"query": query}


def run_demo():
    """先复现对象复用，再验证顺序、并发及部分失败场景。"""
    print("离线演示：不调用真实模型，不产生模型费用，不保存维修案例。")
    shared_inputs = []
    shared = demo_factory(shared_inputs)
    shared.run("车辆甲")
    shared.run("车辆乙")
    assert "车辆甲" in str(shared_inputs[0].inputs[2])
    print("旧行为复现：复用同一 Agent，第二次输入包含第一次历史。")

    observed = []
    with patch.object(api, "build_agent", lambda: demo_factory(observed)):
        for query in ("车辆甲", "车辆乙"):
            check_response(post(query), query)
    assert len(observed) == 2 and "车辆甲" not in str(observed[1].inputs)
    print("顺序请求：两个 Agent，历史隔离，回答和工具参数分别对应车辆。")

    for fail_query in (None, "车辆甲"):
        observed = []
        barrier = Barrier(2)
        with patch.object(api, "build_agent", lambda: demo_factory(observed, barrier=barrier, fail_query=fail_query)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(post, query) for query in ("车辆甲", "车辆乙")]
                first, second = [job.result(timeout=20) for job in jobs]
        check_response(second, "车辆乙")
        if fail_query:
            assert first.status_code == 503
            assert first.json()["detail"]["code"] == "MODEL_UNAVAILABLE"
        else:
            check_response(first, "车辆甲")
        assert len(observed) == 2
        for model in observed:
            query = model.inputs[0][-1]["content"]
            other = "车辆乙" if query == "车辆甲" else "车辆甲"
            assert other not in str(model.inputs)
        print(f"并发请求：甲={first.status_code}，乙={second.status_code}，上下文各自独立。")
    print("演示通过；这些结果证明调用控制行为，不证明真实维修诊断准确。")


if __name__ == "__main__":
    # Windows 事件循环通过本机 socketpair 唤醒线程，不能禁止该内部连接。
    original_connect = socket.socket.connect

    def offline_connect(sock, address):
        """阻断外部连接，只允许事件循环使用的本机地址。"""
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise AssertionError("离线演示禁止外部连接")
        return original_connect(sock, address)

    with patch("socket.socket.connect", new=offline_connect), patch(
        "socket.create_connection", side_effect=AssertionError("离线演示禁止网络请求")
    ):
        run_demo()
