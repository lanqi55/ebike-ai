# embedding_utils.py
from typing import List
import http.client
import json
import math
from langchain_core.embeddings import Embeddings
from ebike_ai.config import config
from ebike_ai.core.failures import DiagnosisError, TransientServiceError, call_dependency


class MyDashScopeEmbedding(Embeddings):
    def __init__(self, model: str = None, api_key: str = None):
        #如果不传，就用 config 的默认值；传了就用传的
        self.model = model or config.embedding.model
        self.api_key = api_key or config.embedding.api_key
        self.host = config.embedding.host
        self.api_path = config.embedding.api_path

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """每次尝试独立建连并关闭；不把原始响应或请求头放入异常。"""
        if not texts:
            return []
        if not self.api_key.strip():
            raise DiagnosisError("EMBEDDING_NOT_CONFIGURED")
        return call_dependency(
            lambda: self._embed_once(texts), dependency="EMBEDDING",
            attempts=config.embedding.max_attempts, delay=config.embedding.retry_delay,
        )

    def _embed_once(self, texts):
        """执行一次有超时的网络请求，鉴权和参数错误不自动重试。"""
        conn = http.client.HTTPSConnection(self.host, timeout=config.embedding.request_timeout)
        # 兼容接口固定 input.texts
        payload = json.dumps({
            "model": self.model,
            "input": {
                "texts": texts
            }
        })
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        try:
            conn.request("POST", self.api_path, payload, headers)
            res = conn.getresponse()
            if res.status in (429, 500, 502, 503, 504):
                raise TransientServiceError(res.status)
            if res.status != 200:
                raise DiagnosisError("EMBEDDING_UNAVAILABLE")
            response_bytes = res.read()
            try:
                response_body = response_bytes.decode("utf-8").strip()
                data = json.loads(response_body)
                items = data["output"]["embeddings"]
                if len(items) != len(texts):
                    raise ValueError("向量数量不匹配")
                if any("text_index" in item for item in items):
                    if sorted(item["text_index"] for item in items) != list(range(len(texts))):
                        raise ValueError("向量索引不匹配")
                    items = sorted(items, key=lambda item: item["text_index"])
                vectors = [item["embedding"] for item in items]
                if any(not isinstance(vector, list) or not vector for vector in vectors):
                    raise ValueError("向量为空或格式无效")
                if len({len(vector) for vector in vectors}) != 1:
                    raise ValueError("向量维度不一致")
                if any(type(value) not in (int, float) or not math.isfinite(value)
                       for vector in vectors for value in vector):
                    raise ValueError("向量含无效数值")
                return vectors
            except (ValueError, KeyError, TypeError):
                raise DiagnosisError("EMBEDDING_RESPONSE_INVALID") from None
        finally:
            conn.close()

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]
