import pytest
import allure

from evaluation.metrics import detect_hallucination, tool_success_rate

# 构造批量测试用例
# 每个用例包含: 硬件电压数据、故障描述、预期关键词列表
# 策略: N 个关键词中至少命中半数才算通过（不要求逐字匹配长句）
test_case_list = [
    {
        "hardware_data": {"cell1": 3.26, "cell2": 3.25, "cell3": 2.11, "total_vol": 8.62},
        "fault_text": "电动车起步无力，爬坡断电",
        # cell3=2.11V 远低于正常值 → 核心诊断必然涉及这些词
        "expect_keywords": ["电芯", "cell3", "电压偏低"]
    },
    {
        "hardware_data": {"cell1": 3.28, "cell2": 3.27, "cell3": 3.29, "total_vol": 9.84, "charge_fast": True},
        "fault_text": "充电一小时就满，续航大幅变短",
        # 充电快+续航短 → 核心诊断必然涉及这些词
        "expect_keywords": ["老化", "电池", "电芯"]
    }
]


# 参数化批量执行: pytest 会为 test_case_list 中每个 dict 生成一条独立测试
@pytest.mark.parametrize("case", test_case_list)
def test_agent_diagnose_accuracy(case, agent):
    """验证 Agent 诊断准确性：关键词命中 + 幻觉检测 + 工具调用成功率"""
    with allure.step("运行 Agent 诊断"):
        answer, state = agent.run(
            f"【当前电池电压】{case['hardware_data']}\n【用户问题】{case['fault_text']}"
        )

    # 指标1：幻觉检测（回答里有没有编造不存在的电芯）
    hallucinated = detect_hallucination(answer, str(case["hardware_data"]))
    with allure.step("幻觉检测"):
        allure.attach(
            "无幻觉" if not hallucinated else f"幻觉电芯: {hallucinated}",
            name="幻觉检测结果",
            attachment_type=allure.attachment_type.TEXT,
        )

    # 指标2：工具调用成功率
    rate = tool_success_rate(state["tool_trace"])
    with allure.step("工具调用成功率"):
        allure.attach(f"{rate:.2%}", name="工具调用成功率", attachment_type=allure.attachment_type.TEXT)

    # 原有断言：关键词命中
    keywords = case["expect_keywords"]
    hits = [kw for kw in keywords if kw in answer]
    hit_count = len(hits)
    required = max(1, len(keywords) // 2 + 1)  # 至少命中一半（向上取整）

    print(f"\n📝 Agent 输出:\n{answer}")
    print(f"🔍 关键词命中: {hits} ({hit_count}/{len(keywords)}，需要≥{required})")
    print(f"🚨 幻觉检测: {hallucinated if hallucinated else '无'}")
    print(f"⚙️ 工具调用成功率: {rate:.2%}")

    assert hit_count >= required, (
        f"用例判定失败！\n"
        f"关键词命中不足: {hit_count}/{len(keywords)}（需要≥{required}）\n"
        f"命中: {hits}\n"
        f"未命中: {[kw for kw in keywords if kw not in answer]}\n"
        f"--- Agent 完整回答 ---\n{answer}"
    )
