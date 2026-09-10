
from core.tool_registry import Tool, ToolRegistry
from core.react_loop import AgentLoop
from tools.knowledge_tools import create_knowledge_tools
from evaluation.judges import KeywordJudge, FormatJudge, HallucinationJudge, ToolCallJudge, RobustnessJudge


def evaluate(cases, llm, judge_llm, runs=3):
    """批量评测：每个用例跑 runs 次，返回各维度通过率列表"""
    judges = [KeywordJudge(), FormatJudge(), HallucinationJudge(judge_llm), ToolCallJudge(), RobustnessJudge()]

    results = []
    for case in cases:
        # 建 mock 工具（每条用例一个）
        registry = ToolRegistry()
        def fake_get_battery_data():
            return case["hardware_data"]
        registry.register(Tool(name="get_battery_data", description="读取电池电压",
                               func=fake_get_battery_data, parameters={"type":"object","properties":{},"required":[]}))
        for tool in create_knowledge_tools():
            registry.register(tool)

        # 跑 runs 次，收集各维度结果
        passes_by_dim = {judge.name: [] for judge in judges}
        for _ in range(runs):
            agent = AgentLoop(llm=llm, registry=registry, max_iter=10)
            answer, state = agent.run(case["fault_text"])
            for judge in judges:
                r = judge.judge(case, answer, state)
                passes_by_dim[judge.name].append(r["passed"])

        # 汇总成通过率
        row = {"fault_text": case["fault_text"], "category": case["category"]}
        for name, passes in passes_by_dim.items():
            valid = [p for p in passes if p is not None]
            row[name] = sum(valid) / len(valid) if valid else None
        results.append(row)

    return results
