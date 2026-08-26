# Agent 的"记忆"（记住之前的对话）

from collections import deque
from langchain_chroma import Chroma
from embedding_utils import MyDashScopeEmbedding
from config import config
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent  # core/ 的上一级 = 项目根目录


class ShortTermMemory:
    """短期对话记忆：只保留最近 N 轮对话"""

    def __init__(self, max_turns: int = 10):
        # 用一个定长队列存对话，满了就自动丢掉最旧的
        self.buffer = deque(maxlen=max_turns)

    def add(self, user_msg: str, assistant_msg: str):
        """存一轮对话"""
        self.buffer.append({"user": user_msg, "assistant": assistant_msg})

    def to_string(self) -> str:
        """把所有对话拼接成一段文本，方便注入 prompt"""
        if not self.buffer:
            return "暂无历史对话"
        lines = []
        for i, turn in enumerate(self.buffer, 1):
            lines.append(f"第{i}轮 - 用户：{turn['user']}")
            lines.append(f"第{i}轮 - 助手：{turn['assistant']}")
        return "\n".join(lines)


class LongTermMemory:
    """长期案例记忆：Chroma 持久化存储，语义检索历史维修案例"""

    def __init__(self, persist_dir: str = None):
        # 1. 持久化目录（放项目根目录 long_term_db）
        if persist_dir is None:
            persist_dir = str(PROJECT_ROOT / "long_term_db")

        # 2. embedding 模型（和知识库同一个向量模型）
        self.embedding = MyDashScopeEmbedding(
            model=config.embedding.model,
            api_key=config.embedding.api_key,
        )

        # 3. embedding_function 必须在这里传进去，
        #    否则 Chroma 会偷偷用自己内置的默认向量，和知识库的向量对不上
        self.vectorstore = Chroma(
            collection_name="repair_cases",
            embedding_function=self.embedding,
            persist_directory=persist_dir,
        )

    def add_case(self, fault: str, solution: str):
        """存一条维修案例：故障→解决方案"""
        self.vectorstore.add_texts(
            texts=[solution],             # 方案内容用于生成向量
            metadatas=[{"fault": fault}],  # 故障描述存在元数据里
        )

    def search(self, query: str, k: int = 3) -> list[str]:
        """语义搜索：输入故障描述，返回相关历史方案"""
        docs = self.vectorstore.similarity_search(query, k=k)
        if not docs:
            return []

        cases = []
        for doc in docs:
            cases.append(
                f"【历史故障】{doc.metadata.get('fault', '')}\n【解决方案】{doc.page_content}"
            )
        return cases


if __name__ == "__main__":
    mem = LongTermMemory()
    # 存一条案例
    mem.add_case("电池掉电快", "第三串电芯电压偏低，需更换")
    # 搜一下
    results = mem.search("续航变短")
    print("搜索结果：")
    for r in results:
        print(r)
