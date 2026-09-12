# 一个跟电动车、跟 LLM 都无关的假 Agent
class FakeChatbot:
    def run(self, query):
        return "这是聊天机器人的回答", {"tool_trace": []}

def fake_factory(case):
    return FakeChatbot()

# 一个跟电动车无关的最简单 Judge（回答非空就过）
class NotEmptyJudge:
    name = "回答非空"
    def judge(self, case, answer, state):
        passed = bool(answer.strip())
        return {"name": self.name, "score": float(passed), "passed": passed, "detail": "非空检测"}


from evaluation.agent_tester import AgentTester

tester = AgentTester(agent_factory=fake_factory, judges=[NotEmptyJudge()], runs=2)
cases = [{"fault_text": "今天天气怎么样", "category": "闲聊"}]
results = tester.test(cases)
print(results)
