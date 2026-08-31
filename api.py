# FastAPI 服务化：把诊断 Agent 包装成 HTTP 接口
# 作用：（前端 / 其他服务）用 HTTP 就能调用诊断能力，不用 import Python 代码
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from langchain_community.chat_models import ChatTongyi
from core.tool_registry import ToolRegistry
from core.react_loop import AgentLoop
from tools.hardware_tools import create_hardware_tools
from tools.knowledge_tools import create_knowledge_tools
from config import config


# ========== 1. 定义"入参 / 出参"结构（Pydantic 自动校验） ==========

class DiagnoseRequest(BaseModel):
    """POST /diagnose 的请求体"""
    fault_text: str = Field(..., min_length=1, max_length=500, description="电动车故障描述")


class DiagnoseResponse(BaseModel):
    """POST /diagnose 的响应体"""
    answer: str = Field(..., description="AI 诊断结论")
    iteration_count: int = Field(..., description="Agent 走了几轮")
    hardware_data: str = Field(..., description="读取到的硬件电压数据")
    retrieved_docs: str = Field(..., description="检索到的维修知识")
    tool_trace: list[dict] = Field(..., description="工具调用轨迹")


# ========== 2. 构建 Agent（模块加载时建一次，之后所有请求复用） ==========

def build_agent() -> AgentLoop:
    """把 LLM + 工具组装成 Agent（逻辑和 main_agent.py 一样）"""
    llm = ChatTongyi(
        model=config.llm.model,
        dashscope_api_key=config.llm.api_key,
        temperature=config.llm.temperature,
        model_kwargs={"max_tokens": config.llm.max_tokens},
    )
    registry = ToolRegistry()
    for tool in create_hardware_tools():
        registry.register(tool)
    for tool in create_knowledge_tools():
        registry.register(tool)
    return AgentLoop(llm=llm, registry=registry, max_iter=10)


app = FastAPI(title="电动车维修诊断 API", version="0.1.0")
# agent = build_agent()
agent = None   # 惰性初始化：import 时不建，第一次请求才建


# ========== 3. 诊断接口 ==========

# 坑：Agent 是同步的（invoke 会阻塞等 LLM 返回），所以这里用 def 而不是 async def。
# FastAPI 会把 def 端点丢进线程池跑，不卡事件循环；用 async def 反而会阻塞整个服务。
@app.post("/diagnose", response_model=DiagnoseResponse)
def diagnose(req: DiagnoseRequest):
    global agent  # 要修改模块级 agent，必须声明 global
    """接收故障描述，返回诊断结果 + 诊断过程摘要"""
    try:
        answer, state = agent.run(req.fault_text)
    except Exception as e:
        # 诊断出错 → 返回 500，而不是让接口直接崩掉
        raise HTTPException(status_code=500, detail=f"诊断失败: {e}")

    return DiagnoseResponse(
        answer=answer,
        iteration_count=state["iteration_count"],
        hardware_data=state["hardware_data"],
        retrieved_docs=state["retrieved_docs"],
        tool_trace=state["tool_trace"],
    )


@app.get("/health")
def health():
    """健康检查：确认服务活着"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
