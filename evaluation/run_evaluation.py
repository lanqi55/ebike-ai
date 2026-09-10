from evaluation.evaluate import evaluate
import json
from langchain_community.chat_models import ChatTongyi
from config import config
import pandas as pd

# 读测试集
with open("evaluation/test_cases.json", encoding="utf-8") as f:
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
df.to_excel("evaluation/report.xlsx", index=False)
