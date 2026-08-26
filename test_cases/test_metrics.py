# 评测指标函数的单元测试（纯函数，不花钱、不联网、秒跑）
from evaluation.metrics import tool_success_rate, detect_hallucination, hallucination_rate


def test_tool_success_rate_all_success():
    assert tool_success_rate([{"success": True}, {"success": True}]) == 1.0


def test_tool_success_rate_half_failed():
    assert tool_success_rate([{"success": True}, {"success": False}]) == 0.5


def test_tool_success_rate_empty_trace_no_divide_by_zero():
    # 没调工具时不除零，返回 1.0
    assert tool_success_rate([]) == 1.0


def test_detect_hallucination_catches_fake_cell():
    answer = "cell4 电压偏低，建议更换电芯"
    ground_truth = {"cell1": 3.2, "cell2": 3.2, "cell3": 2.1}
    assert detect_hallucination(answer, str(ground_truth)) == ["cell4"]


def test_detect_hallucination_returns_empty_when_no_fake():
    answer = "cell3 电压偏低，建议更换电芯"
    ground_truth = {"cell1": 3.2, "cell2": 3.2, "cell3": 2.1}
    assert detect_hallucination(answer, str(ground_truth)) == []


def test_hallucination_rate_half():
    answer = "cell2 正常，cell4 电压偏低"
    ground_truth = {"cell1": 3.2, "cell2": 3.2, "cell3": 2.1}
    # 提到 2 个电芯（cell2、cell4），其中 1 个是幻觉 → 0.5
    assert hallucination_rate(answer, str(ground_truth)) == 0.5


def test_detect_hallucination_is_case_insensitive():
    # 回答里写 "Cell3"（大写），真实数据里是 "cell3"，不应误判为幻觉
    answer = "Cell3 电压偏低"
    ground_truth = {"cell1": 3.2, "cell2": 3.2, "cell3": 2.1}
    assert detect_hallucination(answer, str(ground_truth)) == []
