from core.tool_registry import Tool, ToolRegistry
from core.react_loop import AgentLoop


def test_agent_llm_empty_content():
    """测试：LLM 返回空内容且不调工具时，Agent 不应崩溃"""

    class FakeLLM:
        def bind_tools(self, schemas):
            return self  # bind_tools 返回自己，保持链式调用

        def invoke(self, messages):
            class FakeResponse:
                content = ""  # LLM 返回空内容
                tool_calls = None  # 也不调工具

            return FakeResponse()

    registry = ToolRegistry()
    agent = AgentLoop(llm=FakeLLM(), registry=registry, max_iter=10)

    answer, state = agent.run("测试")

    # 断言：Agent 正常结束（返回空字符串或提示），而不是抛异常
    assert isinstance(answer, str)


def test_agent_max_iter_protection():
    """测试：max_iter=0 时，Agent 应立即返回超时提示，而不是无限循环"""

    # 造一个假 LLM
    class FakeLLM:
        def bind_tools(self, schemas):
            return self  # bind_tools 返回自己，保持链式调用

        def invoke(self, messages):
            # 模拟 LLM 总是返回"要调工具"，导致循环不结束
            class FakeResponse:
                content = "我要调工具"
                tool_calls = [{"name": "some_tool", "args": {}, "id": "1"}]

            return FakeResponse()

    registry = ToolRegistry()
    agent = AgentLoop(llm=FakeLLM(), registry=registry, max_iter=0)

    answer, state = agent.run("测试")

    # 断言：max_iter=0，循环一次都不该跑，直接返回超时提示
    assert "超时" in answer


def test_execute_unknown_tool():
    """测试：调用不存在的工具，应该优雅返回 error，而不是抛异常"""
    registry = ToolRegistry()   # 空注册中心，没有任何工具

    result = registry.execute("不存在的工具", {})

    # 断言：返回的是包含 error 的字符串，且没有抛异常
    assert "error" in result


def test_execute_tool_exception():
    """测试：工具内部抛异常，execute 应该捕获并返回 error"""
    def broken_tool():
        raise ValueError("模拟工具内部错误")

    registry = ToolRegistry()
    registry.register(Tool(
        name="broken_tool",
        description="测试用",
        func=broken_tool,
        parameters={"type": "object", "properties": {}}
    ))

    result = registry.execute("broken_tool", {})

    # 断言：异常被捕获，返回 error 字符串，而不是让测试崩溃
    assert "error" in result
