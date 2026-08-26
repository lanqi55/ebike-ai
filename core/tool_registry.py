import json
# 定义工具：用 Tool 类把 Python 函数包装成大模型可理解的格式（名字、描述、参数 Schema）。
# 注册工具：用 ToolRegistry 把所有工具集中管理。
# 工具查询：通过 get_schemas() 生成符合 OpenAI 规范的 tools 参数，每次对话时传给大模型，让模型知道有哪些工具可用。
# 执行调用：当大模型返回一个工具调用请求（包含工具名和参数），execute() 根据名称找到对应的函数，解包参数执行，并把结果序列化为 JSON 字符串返回给模型，形成闭环。

# 工具身份证，工具要给 LLM 用，需要告诉 什么东西
class Tool:
    def __init__(self, name: str, description: str,  func,parameters: dict):
        self.name = name #工具的唯一名称
        self.description = description #工具的功能描述
        self.func = func #真正要执行的 Python 函数对象
        self.parameters = parameters #一个字典，描述了调用这个工具时需要哪些输入参数、参数的类型、哪些是必填的。

    #把工具信息转成 OpenAI 规定的 JSON Schema 格式，API 请求体
    #每个工具都需要把自己的名字、功能描述、参数格式告诉大模型，这样大模型才知道“我有这个工具可以用，怎么调用它”。
    def to_openai_schema(self)->dict:
        #返回值是一个字典
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

# 工具管理中心来统一调度
# 负责注册所有工具，并提供给大模型，以及执行大模型请求的工具调用。
class ToolRegistry:
    def __init__(self):
        # 一个空字典 self.tools，key 是工具名字符串，value 是 Tool 对象
        self.tools = {}

    # 注册方法，接收一个 Tool 对象作为参数
    def register(self, tool: Tool):
        #把一个 Tool 对象存进 self.tools 字典
        self.tools[tool.name] = tool

    # 返回所有工具对应的 OpenAI Schema 列表，供大模型选择。返回值是一个列表，里面每个元素是一个字典
    def get_schemas(self)->list[dict]:
        # 遍历self.tools里所有工具，对每个工具调to_openai_schema()，把结果装进一个列表返回。
        result = []
        for tool in self.tools.values():
            result.append(tool.to_openai_schema())
        return result

        #return [tool.to_openai_schema() for tool in tools.values()]

    #大模型会告诉要调用的工具名称name,传来字典arguments，包含了调用工具所需的参数
    def execute(self, name:str, arguments: dict)-> str:
        if name not in self.tools:
            # 把字典转成对应字符串
            return json.dumps({"error": "tool not found"})
        tool = self.tools[name]
        try:
            result = tool.func(**arguments)
            return json.dumps(result,ensure_ascii=False) # 中文正常显示
        except Exception as e:
            return json.dumps({"error": str(e)})



if __name__ == "__main__":
    from read_hardware import get_latest_battery_data
    tool2 = Tool(
        name="get_battery_data",
        description="读取电动车电池的最新电压数据，包括每串电芯和总电压",
        func=get_latest_battery_data,
        parameters={
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    registry = ToolRegistry()
    registry.register(tool2)

    # 测试：调这个工具
    print("\n=== 测试 get_battery_data ===")
    result = registry.execute("get_battery_data", {})
    print(f"返回值: {result}")