# 所有可配置常量集中管理，改一处全项目生效

import os
from dataclasses import dataclass
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent

@dataclass
class PathConfig:
    """路径配置"""
    repair_docs: str = str(PROJECT_ROOT / "data" / "repair_docs")        # repair_docs 路径
    chroma_db: str = str(PROJECT_ROOT / "chroma_repair_db")                  # 向量库路径
    car_data_log: str = str(PROJECT_ROOT / "logs" / "car_data_log.txt")       # 日志路径

@dataclass
class LLMConfig:
    """大模型配置"""
    model: str = "qwen-plus"              # 模型名
    temperature: float = 0.1
    max_tokens: int = 500
    api_key: str = os.environ.get("DASHSCOPE_API_KEY", "")  # 环境变量名
    request_timeout: int = 30             # LLM 单次请求超时秒数
    max_retries: int = 2           # LLM 调用失败最多重试次数

@dataclass
class EmbeddingConfig:
    """向量模型配置"""
    model: str = "text-embedding-v1"              # embedding 模型名
    host: str = "dashscope.aliyuncs.com"               # 阿里云 host
    api_path: str = "/api/v1/services/embeddings/text-embedding/text-embedding"           # API 路径
    api_key: str = os.environ.get("DASHSCOPE_API_KEY", "")
    search_top_k: int = 2         # 填检索数量

@dataclass
class AppConfig:
    """总配置"""
    path: PathConfig = PathConfig()
    llm: LLMConfig = LLMConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()

# 全局单例
config = AppConfig()
