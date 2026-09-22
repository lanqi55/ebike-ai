from ebike_ai.evaluation.evaluate import evaluate
import json
from pathlib import Path
from langchain_community.chat_models import ChatTongyi
from ebike_ai.config import config
import pandas as pd

# 读测试集（相对文件自己的路径，不依赖运行目录）
with open(Path(__file__).parent / "test_cases.json", encoding="utf-8") as f:
    cases = json.load(f)

# 建 LLM + 评委 LLM
llm = ChatTongyi(model=config.llm.model, dashscope_api_key=config.llm.api_key,
                 temperature=config.llm.temperature, model_kwargs={"max_tokens": config.llm.max_tokens})
judge_llm = ChatTongyi(model=config.llm.model, dashscope_api_key=config.llm.api_key,
                       temperature=0, model_kwargs={"max_tokens": 500})

# 批量评测
results = evaluate(cases[:2], llm, judge_llm, runs=3)

# 出报告
df = pd.DataFrame(results)
df.to_excel(Path(__file__).parent / "report.xlsx", index=False)
