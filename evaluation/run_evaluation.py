
from core.tool_registry import Tool, ToolRegistry
from core.react_loop import AgentLoop
from tools.knowledge_tools import create_knowledge_tools
import json

# ① 读测试集
with open("evaluation/test_cases.json", encoding="utf-8") as f:
    cases = json.load(f)              # json.load：JSON 字符串 → Python 列表
print(f"加载了 {len(cases)} 条用例")

# ② 建 Agent（跟 api.py 的 build_agent 一样）
from langchain_community.chat_models import ChatTongyi
from core.tool_registry import ToolRegistry
from core.react_loop import AgentLoop
from tools.hardware_tools import create_hardware_tools
from tools.knowledge_tools import create_knowledge_tools
from config import config

llm = ChatTongyi(model=config.llm.model, dashscope_api_key=config.llm.api_key,
                 temperature=config.llm.temperature,
                 model_kwargs={"max_tokens": config.llm.max_tokens})
registry = ToolRegistry()
for tool in create_hardware_tools() + create_knowledge_tools():
    registry.register(tool)
agent = AgentLoop(llm=llm, registry=registry, max_iter=10)

# 建评委 LLM（temperature=0，保证评委判断稳定）
judge_llm = ChatTongyi(model=config.llm.model, dashscope_api_key=config.llm.api_key,
                       temperature=0, model_kwargs={"max_tokens": 500})


# ③ 循环跑 + 打分
from evaluation.judges import KeywordJudge, FormatJudge, HallucinationJudge, ToolCallJudge, RobustnessJudge
judges = [KeywordJudge(), FormatJudge(), HallucinationJudge(judge_llm), ToolCallJudge(), RobustnessJudge()]

results = []
RUNS = 3
for case in cases[-2:]:
    # ===== 为这条用例造一个"假 get_battery_data" =====
    registry = ToolRegistry()

    def fake_get_battery_data():
        return case["hardware_data"]  # mock：返回这条用例的数据，不读文件

    registry.register(Tool(
        name="get_battery_data",
        description="读取电动车电池的最新电压数据，包括每串电芯和总电压",
        func=fake_get_battery_data,
        parameters={"type": "object", "properties": {}, "required": []},
    ))
    for tool in create_knowledge_tools():
        registry.register(tool)

    # ① 新增：每个维度一个空列表，准备装 N 次的结果
    passes_by_dim = {judge.name: [] for judge in judges}

    # ② 新增：内层循环跑 N 次
    for _ in range(RUNS):
        agent = AgentLoop(llm=llm, registry=registry, max_iter=10)  # 每次 new 一个 agent
        answer, state = agent.run(case["fault_text"])
        for judge in judges:
            r = judge.judge(case, answer, state)
            passes_by_dim[judge.name].append(r["passed"])  # 记录这一维度的结果

    # ③ 新增：汇总成"通过率"
    row = {"fault_text": case["fault_text"], "category": case["category"]}
    for name, passes in passes_by_dim.items():
        valid = [p for p in passes if p is not None]  # 排除"不适用"(None)
        row[name] = sum(valid) / len(valid) if valid else None  # 通过率
    results.append(row)

    agent = AgentLoop(llm=llm, registry=registry, max_iter=10)

    # # 跑 Agent（把硬件数据 + 故障描述拼成输入）
    # answer, state = agent.run(case['fault_text'])
    #
    # # 收集这一条的 4 个维度结果
    # row = {"fault_text": case["fault_text"], "category": case["category"]}
    # for judge in judges:
    #     r = judge.judge(case, answer, state)
    #     row[r["name"]] = r["passed"]       # 把"过没过"存进这一行
    # results.append(row)

# ④ Pandas 汇总 + 导出
import pandas as pd
df = pd.DataFrame(results)                 # 列表 → 表格
print(df)                                  # 打印看看
df.to_excel("evaluation/report.xlsx", index=False)
print("报告已保存")
