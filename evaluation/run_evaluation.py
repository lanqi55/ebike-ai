
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

# ③ 循环跑 + 打分
from evaluation.judges import KeywordJudge, FormatJudge, HallucinationJudge, ToolCallJudge
judges = [KeywordJudge(), FormatJudge(), HallucinationJudge(), ToolCallJudge()]

results = []
for case in cases[:3]:
    # 跑 Agent（把硬件数据 + 故障描述拼成输入）
    answer, state = agent.run(
            f"【当前电池电压】{case['hardware_data']}\n【用户问题】{case['fault_text']}"
        )

    # 收集这一条的 4 个维度结果
    row = {"fault_text": case["fault_text"], "category": case["category"]}
    for judge in judges:
        r = judge.judge(case, answer, state)
        row[r["name"]] = r["passed"]       # 把"过没过"存进这一行
    results.append(row)

# ④ Pandas 汇总 + 导出
import pandas as pd
df = pd.DataFrame(results)                 # 列表 → 表格
print(df)                                  # 打印看看
df.to_excel("evaluation/report.xlsx", index=False)
print("报告已保存")
