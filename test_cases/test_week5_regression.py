"""真实案例驱动的离线契约与报告回归，保留失败行和退出状态。"""

import json
import sys

import pytest

from scripts import week5_evidence_demo as demo
from ebike_ai.evaluation.agent_tester import AgentTester
from ebike_ai.evaluation.judges import EvidenceJudge

pytestmark = pytest.mark.integration


def test_three_real_cases_run_without_answer_leakage_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("离线回归不得联网")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    report = demo.run_demo()
    assert report["real_case_count"] == 3
    assert report["passed"] == report["scenario_count"] == 12 and not report["failures"]
    assert {row["case_id"] for row in report["results"]} == {"CASE-001", "CASE-002", "CASE-003"}


@pytest.mark.parametrize("failed", [False, True])
def test_demo_report_and_exit_code_preserve_failure(monkeypatch, tmp_path, failed):
    report = {"real_case_count": 1, "passed": 0 if failed else 1, "scenario_count": 1,
              "failures": [{"error": "合成失败"}] if failed else [], "limitation": "合成报告"}
    monkeypatch.setattr(demo, "run_demo", lambda: report)
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["demo", "--output", str(output)])
    assert demo.main() == (1 if failed else 0)
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_evidence_abstention_is_counted_separately_from_passes():
    class InsufficientAgent:
        def run(self, query):
            return "证据不足，请复检", {"status": "insufficient_evidence"}
    row = AgentTester(lambda case: InsufficientAgent(), [EvidenceJudge()], runs=2).test([
        {"fault_text": "故障", "category": "真实案例"},
    ])[0]
    assert row["insufficient_evidence_count"] == 2
    assert row["failure_count"] == 0 and row["证据引用有效率"] is None


def test_batch_evaluation_preserves_abstention_count(monkeypatch):
    import importlib
    module = importlib.import_module("ebike_ai.evaluation.evaluate")
    class InsufficientAgent:
        def run(self, query):
            return "证据不足", {"status": "insufficient_evidence", "tool_trace": []}
    class JudgeModel:
        def invoke(self, prompt):
            return type("Reply", (), {"content": "无幻觉"})()
    monkeypatch.setattr(module, "AgentLoop", lambda **kwargs: InsufficientAgent())
    row = module.evaluate([{"fault_text": "故障", "category": "模糊", "hardware_data": {},
                            "expect_keywords": ["证据不足"], "expect_tool": ""}], object(), JudgeModel(), runs=2)[0]
    assert row["insufficient_evidence_count"] == 2 and row["failure_count"] == 0
    assert row["证据引用有效率"] is None
