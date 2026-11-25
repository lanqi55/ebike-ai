# Agent 可调用的知识库检索工具

from ebike_ai.embedding_utils import MyDashScopeEmbedding
from langchain_chroma import Chroma
from ebike_ai.core.tool_registry import Tool, SearchArguments
import json
import re
from pathlib import Path
from ebike_ai.core.failures import DiagnosisError
from ebike_ai.config import config
from ebike_ai.knowledge import document_to_chunk, validate_chunks

# 向量库路径
DB_PATH = config.path.chroma_db


# 这个函数在外面定义，Tool 的 func 指向它
def search_repair_knowledge(query: str) -> list[dict]:
    """
    根据用户问题返回带来源的片段；无结果为成功的空列表。
    """
    # 不让 Chroma 在检索时悄悄创建一个空库；构建知识库是独立操作。
    if not (Path(DB_PATH) / "chroma.sqlite3").is_file():
        raise DiagnosisError("KNOWLEDGE_NOT_READY")
    if not config.embedding.api_key.strip():
        raise DiagnosisError("EMBEDDING_NOT_CONFIGURED")
    # 初始化 embedding（和建库时一样）
    embeddings = MyDashScopeEmbedding(
        model=config.embedding.model,
        api_key=config.embedding.api_key,
    )
    # 加载向量库
    manifest_path = Path(DB_PATH) / "evidence_manifest.json"
    options = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            name = manifest["collection_name"]
            if manifest["schema_version"] != 1 or not re.fullmatch(r"repair_evidence_[0-9a-f]{24}", name):
                raise ValueError("知识快照清单无效")
            options = {"collection_name": name, "create_collection_if_not_exists": False}
        except (ValueError, KeyError, TypeError):
            raise DiagnosisError("KNOWLEDGE_NOT_READY") from None
    vectorstore = Chroma(persist_directory=DB_PATH, embedding_function=embeddings, **options)

    # 检索 k 条
    docs = vectorstore.similarity_search(query, k=config.embedding.search_top_k)

    return [document_to_chunk(doc) for doc in docs if doc.page_content.strip()]


def create_knowledge_tools():
    """创建并返回所有知识库相关工具的列表"""
    tools = []

    tool = Tool(
        name="search_repair_knowledge",
        description="搜索维修资料与已确认历史案例，返回含来源、版本和片段编号的证据；历史案例不等于当前车辆结论",
        func=search_repair_knowledge,
        args_model=SearchArguments,
        output_validator=validate_chunks,
    )
    tools.append(tool)
    return tools
