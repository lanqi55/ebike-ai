
from evaluation.metrics import detect_hallucination

class KeywordJudge:
    name = "关键词命中率"

    def judge(self, case, answer, state):
        keywords = case["expect_keywords"]          # 预期关键词

        hits = [kw for kw in keywords if kw.lower() in answer.lower()]

        score = len(hits) / len(keywords)

        passed = score >= 0.5

        detail = f"命中 {len(hits)}/{len(keywords)} 个关键词"

        return {
            "name": self.name,
            "score": score,
            "passed": passed,
            "detail": detail,
        }


class FormatJudge:
    name = "格式合规率"

    def judge(self, case, answer, state):
        # 只有"正常"类才要求格式（对抗要拒绝、模糊要追问，不该评格式）
        if case["category"] != "正常":
            return {"name": self.name, "score": 1.0, "passed": None, "detail": "该类别不要求格式"}

        markers = ["🔧", "📊", "🛠️", "📦"]     # 4 个板块的标记

        found = [mk for mk in markers if mk in answer]

        score = len(found) / len(markers)

        passed = score == 1.0

        detail = f"包含 {len(found)}/{len(markers)} 个板块"

        return {"name": self.name,
                "score": score,
                "passed": passed,
                "detail": detail
                }



class HallucinationJudge:
    name = "幻觉检测"

    def __init__(self,judge_llm):
        self.judge_llm = judge_llm      # 评委 LLM 从外面传进来

    def judge(self, case, answer, state):
        prompt = f"""你是严格的评测员。判断下面的电动车诊断回答有没有编造真实数据中不存在的信息（电压数值、维修步骤、配件型号）。

【真实电压数据】
{case['hardware_data']}

【知识库内容】
{state['retrieved_docs']}

【Agent 的回答】
{answer}

请只回复"有幻觉"或"无幻觉"，不要加任何其他文字。
若有幻觉，格式为：有幻觉：<编造的内容>
"""

        result = self.judge_llm.invoke(prompt)

        has_hallucination = "无幻觉" not in result.content

        score =  0.0 if has_hallucination else 1.0      # 有幻觉 0 分，空列表(没幻觉) 1 分

        passed = not has_hallucination    # 空列表 → not [] → True（通过）

        detail = result.content

        return {"name": self.name,
                "score": score,
                "passed": passed,
                "detail": detail
                }


class ToolCallJudge:
    name = "工具调用正确率"

    def judge(self, case, answer, state):
        expect_tool = case["expect_tool"]    # 用例里指定"该调哪个工具"

        called_tools =  [t["name"] for t in state["tool_trace"]]

        if expect_tool:
            passed = expect_tool in called_tools
            detail = f"期望调用{expect_tool}，实际调用了{called_tools}"

        else:
            passed = called_tools == []
            detail = f"期望不调工具，实际调用 {called_tools}"

        score = 1.0 if passed else 0.0

        return {"name": self.name,
                "score": score,
                "passed": passed,
                "detail": detail
                }