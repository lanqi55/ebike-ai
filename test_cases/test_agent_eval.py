import pytest

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
    """验证 Agent 模式诊断输出是否包含核心关键词（半数命中即通过）"""
    # agent 由 conftest.py 的 fixture 提供，测试里不再手写 LLM/工具初始化
    answer, state = agent.run(
        f"【当前电池电压】{case['hardware_data']}\n【用户问题】{case['fault_text']}"
    )

    # 统计命中了几个关键词
    keywords = case["expect_keywords"]
    hits = [kw for kw in keywords if kw in answer]
    hit_count = len(hits)
    required = max(1, len(keywords) // 2 + 1)  # 至少命中一半（向上取整）

    print(f"\n📝 Agent 输出:\n{answer}")
    print(f"🔍 关键词命中: {hits} ({hit_count}/{len(keywords)}，需要≥{required})")

    assert hit_count >= required, (
        f"用例判定失败！\n"
        f"关键词命中不足: {hit_count}/{len(keywords)}（需要≥{required}）\n"
        f"命中: {hits}\n"
        f"未命中: {[kw for kw in keywords if kw not in answer]}\n"
        f"--- Agent 完整回答 ---\n{answer}"
    )
