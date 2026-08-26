# Agent 的"心脏"（while 循环 + 调工具逻辑）

from core.memory import ShortTermMemory
from core.state import AgentState
from config import config
from utils.logger import get_logger
from tenacity import retry, stop_after_attempt, wait_fixed
import json
import time

logger = get_logger(__name__)


# Agent 循环需要一个 LLM 能返回两件事：文字回答 和 工具调用请求
class AgentLoop:
    def __init__(self, llm, registry, max_iter=10):
        self.llm = llm
        self.registry = registry
        self.max_iter = max_iter
        # 统一绑定工具，保证 self.llm 一定带工具
        self.llm = self.llm.bind_tools(self.registry.get_schemas())
        self.memory = ShortTermMemory(max_turns=5)

    def run(self, user_query: str) -> tuple[str, AgentState]:
        # 初始化所有字段为空
        state: AgentState = {
            "user_query": user_query,
            "hardware_data": "",
            "retrieved_docs": "",
            "final_answer": "",
            "iteration_count": 0,
            "tool_trace": [],
        }

        system_prompt = (
            "你是一名电动车维修专家，负责根据电池电压数据诊断故障。"
            "你有两个工具可用："
            "1）get_battery_data —— 读取电池实时电压，当你需要了解电芯状态时必须调用它；"
            "2）search_repair_knowledge —— 搜索维修知识库，当电压异常需要匹配维修方案时调用。"
            "3）search_history_cases —— 搜索历史维修案例，当用户说'之前修过'或问题可能复发时，先查历史案例获取经验。"
            "诊断时先用工具获取数据，再结合知识库分析，最后用以下格式输出（不超过200字）：\n"
            "🔧 故障定位：xxx\n"
            "📊 判断依据：xxx\n"
            "🛠️ 检修步骤：1.xxx 2.xxx 3.xxx\n"
            "📦 需更换配件：xxx\n"
            "禁止编造知识库和电压数据中不存在的信息。"
            "如果对话历史中有之前的诊断记录，先检查当前问题是否和历史相关："
            "若相关，结合历史结论做补充诊断，避免重复给出相同的答案；"
            "若不相关，重新从头诊断。"
        )

        # 对话历史
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        # 如果之前有对话历史，注入进来
        if self.memory.buffer:
            history_text = self.memory.to_string()
            messages.append({"role": "user", "content": f"以下是我们之前的对话记录：\n{history_text}"})

        messages.append({"role": "user", "content": user_query})

        for i in range(self.max_iter):
            # 把对话历史发给 LLM，LLM 返回一个回复
            response = self._call_llm(messages)
            state["iteration_count"] = i + 1

            # 拿到 LLM 回复的文字和工具调用请求
            ai_text = response.content  # LLM 说了什么
            tool_calls = response.tool_calls  # LLM 要调工具吗？（列表）

            # 情况A：LLM 没要调工具 → 它就是最终回答
            if not tool_calls:
                state["final_answer"] = response.content
                self.memory.add(user_query, state["final_answer"])
                return ai_text, state

            # 情况B：LLM 要调工具 → 帮它执行
            # 把 LLM 的回复加入对话历史
            messages.append(response.model_dump())

            # 对每个工具调用，执行它并把结果加入对话
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                logger.info(f"🔧 调用工具: {tool_name}, 参数: {tool_args}")
                start = time.time()      # 记录开始时间
                result = self.registry.execute(tool_name, tool_args)    # 执行工具
                elapsed = time.time() - start   # 计算耗时
                if elapsed > 5:
                    logger.warning(f"工具 {tool_name} 执行耗时 {elapsed:.1f}s，超过 5s 阈值")
                logger.info(f"📋 工具返回: {result[:100]}...")

                # 判断工具是否成功：返回 JSON 里带 "error" 字段就算失败
                try:
                    success = "error" not in json.loads(result)
                except Exception:
                    success = True  # 非 JSON 字符串，视为工具正常返回

                # 记录工具调用轨迹，供评测框架统计（成功率、延迟等指标）
                state["tool_trace"].append({
                    "iteration": i + 1,
                    "name": tool_name,
                    "args": tool_args,
                    "elapsed": round(elapsed, 3),
                    "success": success,
                })

                # 根据工具名，把结果写进 state 对应字段
                if tool_name == "get_battery_data":
                    state["hardware_data"] = result

                elif tool_name == "search_repair_knowledge":
                    state["retrieved_docs"] = result

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result
                })
            # 回到循环开头，让 LLM 看工具结果继续思考

        return "诊断超时，请简化问题", state

    def _call_llm(self, message):
        """调用 LLM，失败自动重试"""
        # @retry 捕获异常
        @retry(
            stop=stop_after_attempt(config.llm.max_retries),  # 最多执行的次数
            wait=wait_fixed(2),  # 每次重试间隔 2 秒
            reraise=True         # 都失败后，把原始错误抛出来
        )
        def _call():
            logger.info(f"📞 正在调用 LLM...")
            return self.llm.invoke(message)

        return _call()
