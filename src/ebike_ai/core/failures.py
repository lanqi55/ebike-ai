"""诊断错误与有限重试；对外只暴露固定文案，不保留底层异常文本。"""

import time
from collections.abc import Mapping


ERRORS = {
    "INPUT_INVALID": (422, "故障描述必须为 1 至 500 字的非空文本"),
    "MODEL_NOT_CONFIGURED": (503, "模型未配置，请设置服务端凭据"),
    "MODEL_UNAVAILABLE": (503, "模型服务不可用，请检查配置或稍后重试"),
    "MODEL_TIMEOUT": (504, "模型请求超时，本次诊断未完成"),
    "MODEL_RESPONSE_INVALID": (502, "模型返回格式异常，本次诊断未完成"),
    "EMBEDDING_NOT_CONFIGURED": (503, "检索模型未配置，请设置服务端凭据"),
    "EMBEDDING_UNAVAILABLE": (503, "检索服务不可用，请稍后重试或人工复检"),
    "EMBEDDING_TIMEOUT": (504, "检索请求超时，请稍后重试或人工复检"),
    "EMBEDDING_RESPONSE_INVALID": (502, "检索服务返回格式异常"),
    "KNOWLEDGE_NOT_READY": (503, "维修知识库尚未准备，请先构建知识库"),
    "TOOL_FAILED": (503, "工具未能提供有效证据，本次诊断未完成，请人工复检"),
    "TOOL_NOT_FOUND": (502, "模型请求了未注册工具，本次诊断未完成"),
    "TOOL_ARGUMENTS_INVALID": (502, "模型给出的工具参数无效，本次诊断未完成"),
    "TOOL_OUTPUT_INVALID": (502, "工具返回的数据格式无效，本次诊断未完成"),
    "TOOL_EXECUTION_FAILED": (503, "工具执行失败，请补充资料或人工复检"),
    "TOOL_DATA_UNAVAILABLE": (503, "测量数据缺失或无效，请检查硬件日志并人工复检"),
    "TOOL_TIMEOUT": (504, "工具执行超时，本次诊断未完成"),
    "AGENT_ITERATION_LIMIT": (503, "已达到诊断迭代上限，本次诊断未完成"),
    "INTERNAL_ERROR": (500, "诊断内部错误，请联系维护人员"),
}


class DiagnosisError(Exception):
    """保存受控错误码；state 仅用于本地评测，不自动返回 HTTP。"""
    def __init__(self, code: str, state=None):
        self.code = code
        self.status_code, self.message = ERRORS[code]
        self.state = state
        super().__init__(self.message)

    def detail(self):
        """构造不含原始异常的响应。"""
        return {"code": self.code, "message": self.message}


class TransientServiceError(Exception):
    """上游明确返回暂时性失败，只携带状态码。"""
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__("上游服务暂时不可用")


def _requests_family(exc, name):
    """识别 DashScope 使用的传递依赖异常，不读取其可能含密钥的文本。"""
    return any(cls.__module__ == "requests.exceptions" and cls.__name__ == name
               for cls in type(exc).__mro__)


def is_timeout(exc):
    """同时识别标准库和 DashScope 同步传输的超时。"""
    return isinstance(exc, TimeoutError) or _requests_family(exc, "Timeout")


def is_transient(exc):
    """仅允许连接中断、超时、限流和部分服务故障重试。"""
    if _requests_family(exc, "SSLError"):
        return False
    if is_timeout(exc) or isinstance(exc, ConnectionError) or _requests_family(exc, "ConnectionError"):
        return True
    if isinstance(exc, TransientServiceError):
        return exc.status_code in (429, 500, 502, 503, 504)
    # ChatTongyi 的 HTTPError.response 可能是 SDK 字典，也可能是 HTTP 响应。
    response = getattr(exc, "response", None)
    status = response.get("status_code") if isinstance(response, Mapping) else getattr(response, "status_code", None)
    return status in (429, 500, 502, 503, 504)


def call_dependency(operation, *, dependency, attempts, delay, sleep=None):
    """attempts 包含首次调用；只在本层重试，不记录第三方异常对象。"""
    if attempts < 1 or delay < 0:
        raise ValueError("重试配置无效")
    sleeper = time.sleep if sleep is None else sleep
    for attempt in range(attempts):
        try:
            return operation()
        except DiagnosisError:
            raise
        except Exception as exc:
            if is_transient(exc) and attempt + 1 < attempts:
                sleeper(delay)
                continue
            suffix = "TIMEOUT" if is_timeout(exc) else "UNAVAILABLE"
            raise DiagnosisError(f"{dependency}_{suffix}") from None
