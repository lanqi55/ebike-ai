# Agent 评测指标：量化"工具调得好不好"、"有没有幻觉"
import re


def tool_success_rate(trace: list[dict]) -> float:
    """工具调用成功率 = 成功的调用次数 ÷ 总调用次数。

    trace 是 AgentLoop 记录的 tool_trace（每条含 success 字段）。
    没调任何工具时返回 1.0，避免除零。
    """
    if not trace:
        return 1.0
    success_count = sum(1 for t in trace if t.get("success"))
    return success_count / len(trace)


def detect_hallucination(answer: str, ground_truth: str) -> list[str]:
    """幻觉检测：找出回答里提到、但真实数据里不存在的电芯编号。

    例：硬件只有 cell1/cell2/cell3，回答却说"cell4 电压低" → 返回 ["cell4"]。

    局限（v1）：只识别 "cellN" 这种英文编号，回答若写"第四串电芯"识别不到。
    后续可以换成"允许词表"或接 LLM 判断。
    """
    mentioned = set(re.findall(r"cell\d+", answer, re.IGNORECASE))
    valid = set(re.findall(r"cell\d+", str(ground_truth), re.IGNORECASE))
    return sorted(mentioned - valid)


def hallucination_rate(answer: str, ground_truth: str) -> float:
    """幻觉率 = 幻觉的电芯数 ÷ 回答里提到的电芯总数（没提到电芯则为 0）"""
    mentioned = set(re.findall(r"cell\d+", answer, re.IGNORECASE))
    if not mentioned:
        return 0.0
    valid = set(re.findall(r"cell\d+", str(ground_truth), re.IGNORECASE))
    return len(mentioned - valid) / len(mentioned)
