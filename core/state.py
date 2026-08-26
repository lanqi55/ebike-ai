from typing import TypedDict

# 把散装变量收进一个统一的结构体里，不用到处找"这个变量叫什么来着"
class AgentState(TypedDict, total=False):
    """
    一次电动车故障诊断的完整状态记录。
    total=False 表示所有字段都是可选的——开始时为空，一步步填充。
    """

    # 用户原始输入
    user_query: str

    # 硬件电压数据
    hardware_data: str

    # 从知识库检索到的文档内容（工具返回的 JSON 字符串）
    retrieved_docs: str

    # LLM 的最终诊断回答
    final_answer: str

    # 已经走了多少轮（防止死循环，上限一般设 10）
    iteration_count: int

    # 工具调用轨迹：每次调了什么工具、耗时、是否成功（供评测框架统计指标）
    tool_trace: list[dict]
