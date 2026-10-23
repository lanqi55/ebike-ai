"""失败运行必须留在统计中，不能作为正常答案交给评委或被丢弃。"""

import importlib

import pytest

from ebike_ai.core.failures import DiagnosisError
from ebike_ai.evaluation.agent_tester import AgentTester
from ebike_ai.evaluation.metrics import max_iter_reached, tool_latency

pytestmark = pytest.mark.unit


class FailingAgent:
    def run(self, query):
        raise DiagnosisError("AGENT_ITERATION_LIMIT", {
            "status": "failed", "error_code": "AGENT_ITERATION_LIMIT",
            "iteration_count": 10, "tool_trace": [],
        })


class ForbiddenJudge:
    name = "质量"
    def judge(self, *args):
        pytest.fail("失败运行不应继续消耗评委模型调用")


def test_generic_tester_records_failed_runs_and_metrics():
    tester = AgentTester(lambda case: FailingAgent(), [ForbiddenJudge()],
                         metrics=[max_iter_reached, tool_latency], runs=2)
    row = tester.test([{"fault_text": "故障", "category": "正常"}])[0]
    assert row["failure_count"] == 2 and row["质量"] == 0
    assert row["failure_codes"] == ["AGENT_ITERATION_LIMIT"] * 2
    assert row["max_iter_reached"] == 1 and row["tool_latency"] is None


def test_generic_tester_handles_failed_factory():
    def factory(case):
        raise DiagnosisError("MODEL_NOT_CONFIGURED")
    row = AgentTester(factory, [ForbiddenJudge()], metrics=[tool_latency], runs=1).test([
        {"fault_text": "故障", "category": "正常"},
    ])[0]
    assert row["failure_count"] == 1 and row["tool_latency"] is None


def test_batch_evaluation_records_failure_without_changing_user_script(monkeypatch):
    module = importlib.import_module("ebike_ai.evaluation.evaluate")
    monkeypatch.setattr(module, "AgentLoop", lambda **kwargs: FailingAgent())
    monkeypatch.setattr(module, "HallucinationJudge", lambda llm: ForbiddenJudge())
    rows = module.evaluate([{"fault_text": "故障", "category": "正常", "hardware_data": {}}],
                           object(), object(), runs=2)
    assert rows[0]["failure_count"] == 2
    assert rows[0]["质量"] == 0 and rows[0]["关键词命中率"] == 0
