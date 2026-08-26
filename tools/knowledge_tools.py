# Agent 可调用的知识库检索工具

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embedding_utils import MyDashScopeEmbedding
from langchain_chroma import Chroma
from core.tool_registry import Tool
from config import config

# 向量库路径
DB_PATH = config.path.chroma_db


# 这个函数在外面定义，Tool 的 func 指向它
def search_repair_knowledge(query: str) -> str:
    """
    根据用户的问题，检索维修知识库，返回相关文档内容。
    """
    # 初始化 embedding（和建库时一样）
    embeddings = MyDashScopeEmbedding(
        model=config.embedding.model,
        api_key=config.embedding.api_key,
    )
    # 加载向量库
    vectorstore = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)

    # 检索 k 条
    docs = vectorstore.similarity_search(query, k=config.embedding.search_top_k)

    # 把检索到的文档拼接成一个字符串返回
    if not docs:
        return "未找到相关维修资料"
    return "\n\n".join(doc.page_content for doc in docs)


def create_knowledge_tools():
    """创建并返回所有知识库相关工具的列表"""
    tools = []

    tool = Tool(
        name="search_repair_knowledge",
        description="搜索电动车维修知识库，输入故障描述，返回相关的维修手册内容",
        func=search_repair_knowledge,
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "故障描述或关键词，如'电池电压低'、'起步无力'"
                }
            },
            "required": ["query"]
        }
    )
    tools.append(tool)
    return tools
