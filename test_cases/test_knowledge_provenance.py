"""真实切分与本地 Chroma 使用假 Embedding，不访问付费服务。"""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma

from ebike_ai import build_rag
from ebike_ai.config import PROJECT_ROOT, config
from ebike_ai.core.failures import DiagnosisError
from ebike_ai.knowledge import document_to_chunk, load_cases, prepare_documents, validate_chunks
from ebike_ai.tools import knowledge_tools

CASE_PATH = PROJECT_ROOT / "data" / "repair_cases"


class FixedEmbeddings(Embeddings):
    """固定向量只验证存取契约，不代表语义检索质量。"""
    def embed_documents(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


@pytest.mark.unit
def test_cases_have_confirmed_narratives_without_fabricated_measurements():
    cases = load_cases(CASE_PATH)
    assert {c.case_id for c in cases} == {"CASE-001", "CASE-002", "CASE-003"}
    assert all(c.confirmation == "confirmed" and c.measurements is None for c in cases)
    for case in cases:
        data = json.loads(case.diagnosis_input())
        assert set(data) == {"symptoms", "vehicle_context", "checks", "measurements", "initial_assessment"}
        assert case.final_diagnosis not in case.diagnosis_input()
        assert case.recheck not in case.diagnosis_input()


@pytest.mark.unit
def test_stable_ids_and_versions_change_only_for_changed_case(tmp_path):
    folder = tmp_path / "cases"
    shutil.copytree(CASE_PATH, folder)
    first = prepare_documents(tmp_path / "empty", folder)
    assert first == prepare_documents(tmp_path / "empty", folder)
    path = folder / "CASE-002.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["missing_information"].append("离线测试新增说明")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    second = prepare_documents(tmp_path / "empty", folder)
    versions = lambda docs, key: {d.metadata["version"] for d in docs if d.metadata["doc_id"] == key}
    assert versions(first, "CASE-001") == versions(second, "CASE-001")
    assert versions(first, "CASE-002").isdisjoint(versions(second, "CASE-002"))
    for doc in second:
        chunk = document_to_chunk(doc)
        assert chunk["content"] == doc.page_content
        assert chunk["provenance_status"] == "complete"


@pytest.mark.parametrize("case_id", ["CASE-001", "CASE-002", "CASE-003"])
@pytest.mark.unit
def test_regression_corpus_excludes_held_out_case_and_arbitrary_reference_docs(tmp_path, case_id):
    docs = prepare_documents(PROJECT_ROOT / "data" / "repair_docs", CASE_PATH, excluded_case_ids=[case_id])
    assert docs
    assert all(d.metadata["doc_id"] != case_id and d.metadata["source_kind"] == "repair_case" for d in docs)


@pytest.mark.unit
def test_unconfirmed_case_is_not_indexed(tmp_path):
    folder = tmp_path / "cases"
    folder.mkdir()
    data = json.loads((CASE_PATH / "CASE-001.json").read_text(encoding="utf-8"))
    data["confirmation"] = "pending"
    (folder / "CASE-001.json").write_text(json.dumps(data), encoding="utf-8")
    assert prepare_documents(tmp_path / "empty", folder) == []


@pytest.mark.unit
def test_legacy_chunk_keeps_missing_metadata_explicit():
    chunk = document_to_chunk(Document(page_content="旧正文", metadata={"source": "old.docx"}))
    assert chunk["source"] == "old.docx" and chunk["version"] is None and chunk["chunk_id"] is None
    assert chunk["confirmation"] == "unconfirmed" and chunk["provenance_status"] == "missing"


@pytest.mark.parametrize("value", ["旧正文", {}, [1], [{"content": "正文", "provenance_status": "complete"}]])
@pytest.mark.unit
def test_tool_payload_rejects_invalid_shapes(value):
    with pytest.raises(ValueError):
        validate_chunks(value)


@pytest.mark.unit
def test_search_returns_source_with_content_using_fake_vectorstore(monkeypatch, tmp_path):
    docs = prepare_documents(tmp_path / "empty", CASE_PATH)[:2]
    (tmp_path / "chroma.sqlite3").touch()
    monkeypatch.setattr(knowledge_tools, "DB_PATH", str(tmp_path))
    monkeypatch.setattr(config.embedding, "api_key", "offline-placeholder")
    monkeypatch.setattr(knowledge_tools, "MyDashScopeEmbedding", lambda **kw: FixedEmbeddings())
    monkeypatch.setattr(knowledge_tools, "Chroma", lambda **kw: SimpleNamespace(similarity_search=lambda *a, **k: docs))
    result = knowledge_tools.search_repair_knowledge("灯失效")
    assert result == [document_to_chunk(doc) for doc in docs]


@pytest.mark.unit
def test_invalid_manifest_never_creates_collection(monkeypatch, tmp_path):
    (tmp_path / "chroma.sqlite3").touch()
    (tmp_path / "evidence_manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(knowledge_tools, "DB_PATH", str(tmp_path))
    monkeypatch.setattr(config.embedding, "api_key", "offline-placeholder")
    monkeypatch.setattr(knowledge_tools, "Chroma", lambda **kw: pytest.fail("不得创建集合"))
    with pytest.raises(DiagnosisError) as caught:
        knowledge_tools.search_repair_knowledge("故障")
    assert caught.value.code == "KNOWLEDGE_NOT_READY"


@pytest.mark.integration
def test_local_chroma_round_trip_repeat_build_and_search(monkeypatch, tmp_path):
    # 独立临时库与假向量，不加载项目现有数据库。
    kwargs = dict(doc_path=tmp_path / "empty", case_path=CASE_PATH, db_path=tmp_path / "db", embedding=FixedEmbeddings())
    first = build_rag.build_repair_knowledge_base(**kwargs)
    second = build_rag.build_repair_knowledge_base(**kwargs)
    assert first == second
    store = Chroma(collection_name=first["collection_name"], persist_directory=str(tmp_path / "db"),
                   embedding_function=FixedEmbeddings())
    assert len(store.get()["ids"]) == first["chunk_count"]
    monkeypatch.setattr(knowledge_tools, "DB_PATH", str(tmp_path / "db"))
    monkeypatch.setattr(config.embedding, "api_key", "offline-placeholder")
    monkeypatch.setattr(knowledge_tools, "MyDashScopeEmbedding", lambda **kw: FixedEmbeddings())
    chunks = knowledge_tools.search_repair_knowledge("故障")
    assert chunks and all(c["provenance_status"] == "complete" for c in chunks)
    expected = {d.metadata["chunk_id"]: d.page_content for d in prepare_documents(tmp_path / "empty", CASE_PATH)}
    assert all(expected[c["chunk_id"]] == c["content"] for c in chunks)


@pytest.mark.unit
def test_failed_build_keeps_previous_manifest(monkeypatch, tmp_path):
    manifest = tmp_path / "evidence_manifest.json"
    manifest.write_text("previous", encoding="utf-8")
    def broken(**kwargs):
        raise RuntimeError("合成写入失败")
    monkeypatch.setattr(build_rag.Chroma, "from_documents", broken)
    with pytest.raises(RuntimeError):
        build_rag.build_repair_knowledge_base(doc_path=tmp_path / "empty", case_path=CASE_PATH,
                                             db_path=tmp_path, embedding=FixedEmbeddings())
    assert manifest.read_text(encoding="utf-8") == "previous"
