
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

    def judge(self, case, answer, state):
        hallucinated = detect_hallucination(answer, str(case["hardware_data"]))

        score =  0.0 if hallucinated else 1.0      # 有幻觉 0 分，空列表(没幻觉) 1 分

        passed = not hallucinated    # 空列表 → not [] → True（通过）

        detail = f"幻觉电芯：{hallucinated}" if hallucinated else "无幻觉"

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

        passed = expect_tool in called_tools

        score = 1.0 if passed else 0.0

        detail = f"期望调用{expect_tool}，实际调用了{called_tools}"

        return {"name": self.name,
                "score": score,
                "passed": passed,
                "detail": detail
                }