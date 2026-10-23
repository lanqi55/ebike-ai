"""使用假 HTTPS 连接验证超时、响应校验、关闭资源与有限重试。"""

import json
from types import SimpleNamespace

import pytest

from ebike_ai import embedding_utils
from ebike_ai.config import config
from ebike_ai.core import failures
from ebike_ai.core.failures import DiagnosisError
from ebike_ai.embedding_utils import MyDashScopeEmbedding
from ebike_ai.tools import knowledge_tools

pytestmark = pytest.mark.unit


def fake_connections(monkeypatch, outcomes):
    created = []
    responses = iter(outcomes)
    class FakeConnection:
        def __init__(self, host, timeout):
            self.timeout = timeout
            self.closed = False
            self.outcome = next(responses)
            created.append(self)

        def request(self, method, path, payload, headers):
            self.payload = json.loads(payload)
            if isinstance(self.outcome, Exception):
                raise self.outcome

        def getresponse(self):
            status, body = self.outcome
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            return SimpleNamespace(status=status, read=lambda: raw)

        def close(self):
            self.closed = True

    monkeypatch.setattr(embedding_utils.http.client, "HTTPSConnection", FakeConnection)
    monkeypatch.setattr(config.embedding, "request_timeout", 4)
    monkeypatch.setattr(config.embedding, "max_attempts", 2)
    monkeypatch.setattr(config.embedding, "retry_delay", 1)
    sleeps = []
    monkeypatch.setattr(failures.time, "sleep", sleeps.append)
    return created, sleeps


def vector_response():
    return {"output": {"embeddings": [{"text_index": 0, "embedding": [0.1, 0.2]}]}}


@pytest.mark.parametrize("failure", [TimeoutError("synthetic-secret"), (429, {}), (503, {})])
def test_embedding_retry_timeout_and_connections_are_closed(monkeypatch, failure):
    created, sleeps = fake_connections(monkeypatch, [failure, (200, vector_response())])
    result = MyDashScopeEmbedding(api_key="offline-placeholder").embed_query("故障")
    assert result == [0.1, 0.2]
    assert len(created) == 2 and sleeps == [1]
    assert all(conn.closed and conn.timeout == 4 for conn in created)
    assert created[-1].payload["input"]["texts"] == ["故障"]


@pytest.mark.parametrize("status", [400, 401, 403])
def test_embedding_auth_and_parameter_errors_do_not_retry(monkeypatch, status):
    created, sleeps = fake_connections(monkeypatch, [(status, {"message": "synthetic-secret"})])
    with pytest.raises(DiagnosisError) as caught:
        MyDashScopeEmbedding(api_key="offline-placeholder").embed_query("故障")
    assert caught.value.code == "EMBEDDING_UNAVAILABLE"
    assert len(created) == 1 and created[0].closed and sleeps == []
    assert "synthetic-secret" not in str(caught.value)


def test_embedding_timeout_attempts_exhausted(monkeypatch):
    created, sleeps = fake_connections(monkeypatch, [TimeoutError(), TimeoutError()])
    with pytest.raises(DiagnosisError) as caught:
        MyDashScopeEmbedding(api_key="offline-placeholder").embed_query("故障")
    assert caught.value.code == "EMBEDDING_TIMEOUT"
    assert len(created) == 2 and all(conn.closed for conn in created)
    assert sleeps == [1]


@pytest.mark.parametrize("body", [b"", b"not-json", b"\xff", {"message": "synthetic-secret"},
    {"output": {"embeddings": []}},
    {"output": {"embeddings": [{"embedding": []}]}},
    {"output": {"embeddings": [{"embedding": [True]}]}},
    {"output": {"embeddings": [{"embedding": [float("nan")]}]}},
])
def test_embedding_malformed_response_is_not_retried(monkeypatch, body):
    created, sleeps = fake_connections(monkeypatch, [(200, body)])
    with pytest.raises(DiagnosisError) as caught:
        MyDashScopeEmbedding(api_key="offline-placeholder").embed_query("故障")
    assert caught.value.code == "EMBEDDING_RESPONSE_INVALID"
    assert created[0].closed and sleeps == []
    assert "synthetic-secret" not in str(caught.value)


def test_embedding_reorders_by_text_index(monkeypatch):
    body = {"output": {"embeddings": [
        {"text_index": 1, "embedding": [2.0]}, {"text_index": 0, "embedding": [1.0]},
    ]}}
    fake_connections(monkeypatch, [(200, body)])
    assert MyDashScopeEmbedding(api_key="offline-placeholder").embed_documents(["甲", "乙"]) == [[1.0], [2.0]]


def test_missing_key_never_connects(monkeypatch):
    monkeypatch.setattr(config.embedding, "api_key", "")
    monkeypatch.setattr(embedding_utils.http.client, "HTTPSConnection", lambda *a, **kw: pytest.fail("不应联网"))
    with pytest.raises(DiagnosisError) as caught:
        MyDashScopeEmbedding().embed_query("故障")
    assert caught.value.code == "EMBEDDING_NOT_CONFIGURED"
    assert MyDashScopeEmbedding().embed_documents([]) == []


def test_missing_knowledge_is_not_silently_created(monkeypatch, tmp_path):
    path = tmp_path / "missing"
    monkeypatch.setattr(knowledge_tools, "DB_PATH", str(path))
    monkeypatch.setattr(knowledge_tools, "Chroma", lambda **kw: pytest.fail("不应创建空库"))
    with pytest.raises(DiagnosisError) as caught:
        knowledge_tools.search_repair_knowledge("故障")
    assert caught.value.code == "KNOWLEDGE_NOT_READY"
    assert not path.exists()


def test_existing_knowledge_without_matches_is_empty_success(monkeypatch, tmp_path):
    (tmp_path / "chroma.sqlite3").touch()
    monkeypatch.setattr(knowledge_tools, "DB_PATH", str(tmp_path))
    monkeypatch.setattr(config.embedding, "api_key", "offline-placeholder")
    monkeypatch.setattr(knowledge_tools, "MyDashScopeEmbedding", lambda **kw: object())
    monkeypatch.setattr(knowledge_tools, "Chroma", lambda **kw: SimpleNamespace(similarity_search=lambda *a, **k: []))
    assert knowledge_tools.search_repair_knowledge("故障") == ""
