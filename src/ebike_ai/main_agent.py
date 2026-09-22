# Agent 模式主入口——LLM 自主决定调哪些工具

from langchain_community.chat_models import ChatTongyi

from ebike_ai.core.memory import LongTermMemory
from ebike_ai.read_hardware import get_latest_battery_data
from ebike_ai.core.tool_registry import ToolRegistry
from ebike_ai.core.react_loop import AgentLoop
from ebike_ai.tools.hardware_tools import create_hardware_tools
from ebike_ai.tools.knowledge_tools import create_knowledge_tools
from ebike_ai.config import config
from ebike_ai.utils.logger import get_logger
from ebike_ai.tools.memory_tools import create_memory_tools

logger = get_logger(__name__)

if __name__ == "__main__":
    long_mem = LongTermMemory()
    # 1. 读取硬件数据
    battery_info = get_latest_battery_data()
    if "error" in battery_info:
        logger.error(f"错误：{battery_info['error']}")
        exit()

    # 2. 初始化 LLM
    llm = ChatTongyi(
        model=config.llm.model,
        dashscope_api_key=config.llm.api_key,
        temperature=config.llm.temperature,
        model_kwargs={"max_tokens": config.llm.max_tokens}
    )

    # 3. 创建工具注册中心，把所有工具登记进去
    registry = ToolRegistry()
    for tool in create_hardware_tools():
        registry.register(tool)
    for tool in create_knowledge_tools():
        registry.register(tool)
    for tool in create_memory_tools(long_mem):
        registry.register(tool)


    # 4. 启动 Agent 循环
    agent = AgentLoop(llm=llm, registry=registry, max_iter=10)


    while True:
        fault_input = input("\n请输入电动车故障描述（输入 quit 退出）：")
        if fault_input.lower() == "quit":
            break

        try:
            answer, state = agent.run(fault_input)
            # 诊断成功，存入长期记忆
            long_mem.add_case(fault_input,answer)
            logger.info(f"\n诊断轮数: {state['iteration_count']}")
            logger.info(f"硬件数据: {state['hardware_data'][:80]}...")
            logger.info(f"检索文档: {state['retrieved_docs'][:80]}...")
        except Exception as e:
            logger.error(f"\n❌ 诊断出错: {e}")
            continue

        print("\n========== AI维修诊断结果 ==========")
        print(answer)
        print("\n========== 对话历史 ==========")
        print(agent.memory.to_string())
