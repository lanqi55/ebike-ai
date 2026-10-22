"""命令行诊断：本次运行保留短期历史，不自动写入维修案例。"""

from ebike_ai.agent_factory import build_agent


def run_cli(*, agent_factory=None, input_func=input, output_func=print):
    """一次命令行会话使用一个 Agent；输入和输出可替换为离线演示。"""
    factory = build_agent if agent_factory is None else agent_factory
    try:
        agent = factory()
    except Exception:
        output_func("诊断初始化失败，请检查服务配置。")
        return

    while True:
        try:
            fault_input = input_func("\n请输入电动车故障描述（输入 quit 退出）：")
        except (EOFError, KeyboardInterrupt):
            return
        if fault_input.strip().lower() == "quit":
            return
        if not fault_input.strip():
            output_func("请输入故障描述。")
            continue
        try:
            answer, state = agent.run(fault_input)
        except Exception:
            output_func("诊断失败，请稍后重试或联系维修师复检。")
            continue
        output_func(f"\n诊断轮数：{state['iteration_count']}")
        output_func(answer)
        output_func("\n本次会话历史：")
        output_func(agent.memory.to_string())


if __name__ == "__main__":
    run_cli()
