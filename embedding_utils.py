# embedding_utils.py
from typing import List
import http.client
import json
from langchain_core.embeddings import Embeddings
from config import config


class MyDashScopeEmbedding(Embeddings):
    def __init__(self, model: str = None, api_key: str = None):
        #如果不传，就用 config 的默认值；传了就用传的
        self.model = model or config.embedding.model
        self.api_key = api_key or config.embedding.api_key
        self.host = config.embedding.host
        self.api_path = config.embedding.api_path

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        conn = http.client.HTTPSConnection(self.host)
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
            response_body = res.read().decode("utf-8").strip()
            if not response_body:
                raise Exception("阿里向量接口返回空内容，请检查API密钥、额度、网络")
            data = json.loads(response_body)
            if "code" in data:
                raise Exception(f"接口业务错误: {data['code']}, {data['message']}")
            return [item["embedding"] for item in data["output"]["embeddings"]]
        finally:
            conn.close()

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]