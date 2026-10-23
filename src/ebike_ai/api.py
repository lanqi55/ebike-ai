# FastAPI 服务化：把诊断 Agent 包装成 HTTP 接口
# 作用：（前端 / 其他服务）用 HTTP 就能调用诊断能力，不用 import Python 代码
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from langchain_community.chat_models import ChatTongyi
from ebike_ai.agent_factory import build_agent
from ebike_ai.config import config
from ebike_ai.work_order_api import router as work_order_router
from ebike_ai.core.failures import DiagnosisError
from ebike_ai.utils.logger import get_logger

logger = get_logger(__name__)


# ========== 1. 定义"入参 / 出参"结构（Pydantic 自动校验） ==========

class DiagnoseRequest(BaseModel):
    """POST /diagnose 的请求体"""
    model_config = ConfigDict(strict=True, str_strip_whitespace=True)
    fault_text: str = Field(..., min_length=1, max_length=500, description="电动车故障描述")


class DiagnoseResponse(BaseModel):
    """POST /diagnose 的响应体"""
    answer: str = Field(..., description="AI 诊断结论")
    iteration_count: int = Field(..., description="Agent 走了几轮")
    hardware_data: str = Field(..., description="读取到的硬件电压数据")
    retrieved_docs: str = Field(..., description="检索到的维修知识")
    tool_trace: list[dict] = Field(..., description="工具调用轨迹")


class TestCase(BaseModel):
    fault_text: str
    hardware_data: dict
    expect_keywords: list[str]
    expect_tool: str
    category: str
    inject_marker: str | None = None   # 可选字段（普通用例没有）

class EvaluateRequest(BaseModel):
    cases: list[TestCase]


# ========== 2. 构建请求独占的 Agent ==========

app = FastAPI(title="电动车维修诊断 API", version="0.1.0")
app.include_router(work_order_router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """诊断输入错误不回显用户内容；其他接口保留原有校验响应。"""
    if request.url.path == "/diagnose":
        error = DiagnosisError("INPUT_INVALID")
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail()})
    return await request_validation_exception_handler(request, exc)


# ========== 3. 诊断接口 ==========

# 坑：Agent 是同步的（invoke 会阻塞等 LLM 返回），所以这里用 def 而不是 async def。
# FastAPI 会把 def 端点丢进线程池跑，不卡事件循环；用 async def 反而会阻塞整个服务。
@app.post("/diagnose", response_model=DiagnoseResponse)
def diagnose(req: DiagnoseRequest):
    """接收故障描述，返回诊断结果 + 诊断过程摘要"""
    try:
        agent = build_agent()
        answer, state = agent.run(req.fault_text)
        return DiagnoseResponse(
            answer=answer,
            iteration_count=state["iteration_count"],
            hardware_data=state["hardware_data"],
            retrieved_docs=state["retrieved_docs"],
            tool_trace=state["tool_trace"],
        )
    except DiagnosisError as exc:
        logger.warning("诊断未完成，错误码=%s", exc.code)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail()) from None
    except Exception:
        error = DiagnosisError("INTERNAL_ERROR")
        logger.error("诊断未完成，错误码=%s", error.code)
        raise HTTPException(status_code=error.status_code, detail=error.detail()) from None

@app.post("/evaluate")
def evaluate_endpoint(req: EvaluateRequest):
    from ebike_ai.evaluation.evaluate import evaluate

    # ① Pydantic 对象 → 字典列表（evaluate 要的是字典）
    cases = [c.model_dump() for c in req.cases]

    # ② 建 LLM + 评委 LLM（跟 run_evaluation 一样）
    llm = ChatTongyi(model=config.llm.model, dashscope_api_key=config.llm.api_key,
                     temperature=config.llm.temperature, model_kwargs={"max_tokens": config.llm.max_tokens})
    judge_llm = ChatTongyi(model=config.llm.model, dashscope_api_key=config.llm.api_key,
                           temperature=0, model_kwargs={"max_tokens": 500})

    # ③ 跑评测（复用函数，不用复制循环）
    results = evaluate(cases, llm, judge_llm, runs=3)

    # ④ 汇总各维度通过率
    import pandas as pd
    df = pd.DataFrame(results)
    cols = ["关键词命中率", "格式合规率", "幻觉检测", "工具调用正确率", "输入鲁棒性"]
    summary = {}
    for c in cols:
        v = df[c].mean()
        summary[c] = None if pd.isna(v) else float(v)

    return {"total_cases": len(results), "summary": summary, "results": results}


@app.get("/health")
def health():
    """健康检查：确认服务活着"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
