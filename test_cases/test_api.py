
from fastapi.testclient import TestClient
from api import app
import api
import pytest

@pytest.fixture(scope="module")
def client():
    return TestClient(app)

# 422情况
# ----空
def test_diagnose_empty_fault_text(client):
    # 发请求
    resp = client.post("/diagnose", json={"fault_text": ""})
    # 断言
    assert resp.status_code == 422


# ----缺字段
def test_diagnose_empty(client):
    # 发请求
    resp = client.post("/diagnose", json={})
    # 断言
    assert resp.status_code == 422


# ----超长
def test_diagnose_long(client):
    # 发请求
    resp = client.post("/diagnose", json={"fault_text": "x" * 600})
    # 断言
    assert resp.status_code == 422

# ----类型错
def test_diagnose_error_type(client):
    # 发请求
    resp = client.post("/diagnose", json={"fault_text": 123})
    # 断言
    assert resp.status_code == 422


# 200 正常情况
def test_diagnose_ok(monkeypatch,client):
    class FakeAgent:
        def run(self, query):
            # ① answer：随便写个字符串，当成"假诊断结果"
            answer = "假诊断结果"

            # ② state：字典，必须包含 endpoint 会读的 4 个 key
            state = {
                "iteration_count": 2,  # 填个数字（int）
                "hardware_data": "cell",  # 填个字符串（str）
                "retrieved_docs": "电池烂了",  # 填个字符串（str）
                "tool_trace": []  # 填个空列表 []
            }

            # ③ 返回一个元组（answer, state），跟真 AgentLoop.run 的返回一致
            return answer, state
    monkeypatch.setattr(api, "agent", FakeAgent())
    resp = client.post("/diagnose", json={"fault_text": "电动车起步无力"})
    assert resp.status_code == 200
    # 再断言：返回的 JSON 里 answer 是填的那个字符串
    assert resp.json()["answer"] == "假诊断结果"


# 500情况
def test_diagnose_error(monkeypatch,client):
    class FakeAgent:
        def run(self, query):
            # raise 一个异常
            raise Exception("模拟 LLM 挂了")
    monkeypatch.setattr(api, "agent", FakeAgent())
    resp = client.post("/diagnose", json={"fault_text": "电动车起步无力"})
    assert resp.status_code == 500

