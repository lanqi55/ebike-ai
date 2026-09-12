from evaluation.agent_tester import AgentTester
from evaluation.metrics import tool_latency, max_iter_reached


# ===== 假 Agent 和假 Judge（测试用） =====

class FakeChatbot:
    """跟电动车、跟 LLM 都无关的假 Agent（验证通用性）"""

    def run(self, query):
        return "这是聊天机器人的回答", {"tool_trace": []}


class FakeAgentWithTools:
    """带 tool_trace 的假 Agent（验证 metrics）"""

    def run(self, query):
        state = {
            "iteration_count": 10,
            "tool_trace": [
                {"name": "get_battery_data", "elapsed": 0.5, "success": True},
                {"name": "search_knowledge", "elapsed": 1.0, "success": True},
            ]}
        return "测试回答", state


class NotEmptyJudge:
    """最简单的 Judge：回答非空就过"""
    name = "回答非空"

    def judge(self, case, answer, state):
        passed = bool(answer.strip())
        return {"name": self.name, "score": float(passed), "passed": passed, "detail": "非空检测"}


# ===== 测试 =====

def test_agent_tester_is_generic():
    """验证 AgentTester 能测一个跟电动车无关的假 Agent（通用性）"""
    tester = AgentTester(
        agent_factory=lambda case: FakeChatbot(),
        judges=[NotEmptyJudge()],
        runs=2)
    results = tester.test([{"fault_text": "今天天气怎么样", "category": "闲聊"}])
    assert results[0]["回答非空"] == 1.0


def test_agent_tester_with_metrics():
    """验证 AgentTester 能跑 metrics，算出平均延迟"""
    tester = AgentTester(
        agent_factory=lambda case: FakeAgentWithTools(),
        judges=[],
        metrics=[tool_latency],
        runs=1)
    results = tester.test([{"fault_text": "测试", "category": "测试"}])
    assert results[0]["tool_latency"] == 0.75


def test_agent_tester_max_iter_reached():
    """验证死循环检测：iteration_count=10 应该被判为'走到上限'"""
    tester = AgentTester(
        agent_factory=lambda case: FakeAgentWithTools(),
        judges=[],
        metrics=[max_iter_reached],
        runs=1,
    )
    results = tester.test([{"fault_text": "测试", "category": "测试"}])
    assert results[0]["max_iter_reached"] == True
