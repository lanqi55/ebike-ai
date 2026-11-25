"""构建带版本的知识快照；验证成功后切换入口，保留既有向量库。"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from langchain_chroma import Chroma
from ebike_ai.embedding_utils import MyDashScopeEmbedding
from ebike_ai.config import config, PROJECT_ROOT
from ebike_ai.knowledge import prepare_documents
from ebike_ai.utils.logger import get_logger

logger = get_logger(__name__)

DOC_PATH = config.path.repair_docs
DB_PATH = config.path.chroma_db
MANIFEST_NAME = "evidence_manifest.json"

def build_repair_knowledge_base(*, doc_path=None, case_path=None, db_path=None, embedding=None):
    """显式调用才建库；测试注入假 Embedding 与临时路径，不覆盖旧集合。"""
    documents = prepare_documents(Path(doc_path or DOC_PATH),
                                  Path(case_path or PROJECT_ROOT / "data" / "repair_cases"))
    if not documents:
        raise ValueError("没有可用于建库的参考文档或已确认案例")
    ids = [doc.metadata["chunk_id"] for doc in documents]
    fingerprint = hashlib.sha256(json.dumps([
        {"text": doc.page_content, "metadata": doc.metadata} for doc in documents
    ], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    collection_name = "repair_evidence_" + fingerprint[:24]
    destination = Path(db_path or DB_PATH)
    embeddings = embedding if embedding is not None else MyDashScopeEmbedding(
        model=config.embedding.model, api_key=config.embedding.api_key)
    store = Chroma.from_documents(documents=documents, ids=ids, embedding=embeddings,
                                  collection_name=collection_name, persist_directory=str(destination))
    # 切换前核对实际写入的编号、正文和元数据，失败保留原入口。
    saved = store.get(ids=ids, include=["documents", "metadatas"])
    expected = {key: (doc.page_content, doc.metadata) for key, doc in zip(ids, documents)}
    actual = {key: (body, metadata) for key, body, metadata in
              zip(saved["ids"], saved["documents"], saved["metadatas"])}
    if actual != expected:
        raise ValueError("知识快照写入核对失败，未切换检索入口")
    manifest = {"schema_version": 1, "collection_name": collection_name, "fingerprint": fingerprint,
                "chunk_count": len(ids)}
    destination.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, destination / MANIFEST_NAME)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    logger.info("知识快照构建并核对完成，片段数=%s", len(ids))
    return manifest


if __name__ == "__main__":
    build_repair_knowledge_base()
