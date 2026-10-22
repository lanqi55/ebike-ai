"""工具参数在运行时校验，结果以统一 JSON 契约传给模型。"""

import json
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError


class NoArguments(BaseModel):
    """无参数工具也必须拒绝多余参数。"""
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchArguments(NoArguments):
    """检索参数；禁止隐式数字转文本以及空白查询。"""
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500, description="故障描述或关键词")


class ToolError(BaseModel):
    """只使用服务端定义的错误，不放入底层异常文本。"""
    code: str
    message: str


class ToolResult(BaseModel):
    """成功的空结果与执行失败通过 ok 区分。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    ok: bool
    data: JsonValue = None
    error: ToolError | None = None

    def to_json(self) -> str:
        """拒绝不可序列化或非有限数值，确保生成标准 JSON。"""
        return json.dumps(self.model_dump(), ensure_ascii=False, allow_nan=False)


def tool_failure(code: str, message: str) -> str:
    """由调用方传入固定错误码及固定提示。"""
    return ToolResult(ok=False, error=ToolError(code=code, message=message)).to_json()


class Tool:
    """参数 Schema 和执行校验使用同一个 Pydantic 模型。"""

    def __init__(self, name: str, description: str, func, parameters: dict | None = None,
                 *, args_model: type[BaseModel] = NoArguments, output_validator=None):
        # 兼容旧无参数构造；有参数工具必须显式提供模型，避免只声明而不校验。
        if parameters and parameters.get("properties") and args_model is NoArguments:
            raise ValueError("有参数工具必须提供 args_model")
        self.name = name
        self.description = description
        self.func = func
        self.args_model = args_model
        self.output_validator = output_validator
        self.parameters = args_model.model_json_schema()

    def to_openai_schema(self) -> dict:
        """生成模型工具调用协议使用的参数描述。"""
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters,
        }}


class ToolRegistry:
    """集中分派工具，模型不能直接调用任意 Python 函数。"""

    def __init__(self):
        self.tools = {}

    def register(self, tool: Tool):
        """注册工具，拒绝同名覆盖。"""
        if tool.name in self.tools:
            raise ValueError("工具名称重复")
        self.tools[tool.name] = tool

    def get_schemas(self) -> list[dict]:
        """仅描述当前已注册工具。"""
        return [tool.to_openai_schema() for tool in self.tools.values()]

    def execute(self, name: str, arguments: dict) -> str:
        """参数错误不执行函数；输出校验错误也不冒充成功。"""
        if not isinstance(name, str) or name not in self.tools:
            return tool_failure("TOOL_NOT_FOUND", "工具未注册")
        tool = self.tools[name]
        try:
            args = tool.args_model.model_validate(arguments).model_dump()
        except ValidationError:
            return tool_failure("TOOL_ARGUMENTS_INVALID", "工具参数不符合要求")
        try:
            result = tool.func(**args)
        except Exception:
            return tool_failure("TOOL_EXECUTION_FAILED", "工具执行失败，请补充资料或人工复检")
        # 读取硬件日志的旧返回格式在这里转换，不向模型暴露任意错误文本。
        if isinstance(result, dict) and "error" in result:
            return tool_failure("TOOL_DATA_UNAVAILABLE", "数据缺失或无效，请检查数据来源")
        try:
            if tool.output_validator is not None:
                result = tool.output_validator(result)
            return ToolResult(ok=True, data=result).to_json()
        except (ValidationError, TypeError, ValueError):
            return tool_failure("TOOL_OUTPUT_INVALID", "工具返回的数据格式无效")
