"""维修知识的来源契约、案例输入隔离及可复现切分；不调用模型。"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class CaseCheck(BaseModel):
    """检查动作与实际发现分开；缺失结果不等于正常。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    action: str = Field(min_length=1)
    result: str | None


class RepairCase(BaseModel):
    """匿名历史记录，不含车辆身份信息或补造的 AI 参与记录。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str = Field(pattern=r"^CASE-[0-9]{3,}$")
    collected_on: str
    repair_date: str | None
    provenance: str = Field(min_length=1)
    confirmation: Literal["confirmed", "pending"]
    vehicle_context: str | None
    symptoms: str = Field(min_length=1)
    checks: list[CaseCheck]
    measurements: list[dict] | None
    initial_assessment: str | None
    final_diagnosis: str
    repair_actions: list[str]
    recheck: str
    missing_information: list[str]

    def diagnosis_input(self) -> str:
        """只导出当时已知输入，故意不包含最终判断、维修与复检。"""
        return json.dumps(self.model_dump(include={
            "symptoms", "vehicle_context", "checks", "measurements", "initial_assessment",
        }), ensure_ascii=False)


class KnowledgeChunk(BaseModel):
    """返回给调用者的片段；旧库缺少的信息必须显式保留为空。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    doc_id: str | None = None
    version: str | None = None
    chunk_id: str | None = None
    source: str | None = None
    content: str = Field(min_length=1)
    confirmation: Literal["confirmed", "unconfirmed"] = "unconfirmed"
    source_kind: Literal["repair_case", "reference", "legacy"] = "legacy"
    provenance_status: Literal["complete", "missing"] = "missing"

    @model_validator(mode="after")
    def check_provenance(self):
        """完整标记不能掩盖缺失来源；版本必须是源文件内容指纹。"""
        if self.provenance_status == "complete":
            if not all(isinstance(v, str) and v.strip() for v in (
                self.doc_id, self.version, self.chunk_id, self.source,
            )):
                raise ValueError("片段缺少来源字段")
            if len(self.version) != 64 or any(c not in "0123456789abcdef" for c in self.version):
                raise ValueError("版本必须是 SHA256 内容指纹")
            if not self.chunk_id.startswith(f"{self.doc_id}-{self.version[:12]}-"):
                raise ValueError("片段编号与文档版本不一致")
        return self


def validate_chunks(value) -> list[dict]:
    """工具边界只接受片段列表，不再接受裸文本。"""
    chunks = TypeAdapter(list[KnowledgeChunk]).validate_python(value, strict=True)
    return [chunk.model_dump() for chunk in chunks]


def load_cases(directory: Path) -> list[RepairCase]:
    """读取并验证案例，拒绝重复编号；待确认案例仍可用于采集核对。"""
    cases = [RepairCase.model_validate_json(path.read_text(encoding="utf-8"))
             for path in sorted(Path(directory).glob("CASE-*.json"))]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("案例编号重复")
    return cases


def prepare_documents(doc_path: Path, case_path: Path, *, excluded_case_ids=()) -> list[Document]:
    """准备独立参考资料和已确认案例；留一回归不加载可能含答案的任意参考文档。"""
    from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
    output = []

    def append_parts(documents, *, doc_id, version, source, source_kind, confirmation):
        for index, part in enumerate(splitter.split_documents(documents)):
            metadata = {
                "doc_id": doc_id, "version": version,
                "chunk_id": f"{doc_id}-{version[:12]}-{index:04d}",
                "source": source, "source_kind": source_kind,
                "confirmation": confirmation, "provenance_status": "complete",
            }
            output.append(Document(page_content=part.page_content, metadata={**part.metadata, **metadata}))

    if not excluded_case_ids:
        for path in sorted(Path(doc_path).rglob("*")):
            if path.suffix.lower() not in {".docx", ".pdf"} or not path.is_file():
                continue
            relative = path.relative_to(doc_path).as_posix()
            loader = Docx2txtLoader(str(path)) if path.suffix.lower() == ".docx" else PyPDFLoader(str(path))
            append_parts(loader.load(), doc_id="DOC-" + hashlib.sha256(relative.encode()).hexdigest()[:12],
                         version=hashlib.sha256(path.read_bytes()).hexdigest(), source="repair_docs/" + relative,
                         source_kind="reference", confirmation="unconfirmed")
    for case in load_cases(case_path):
        if case.confirmation != "confirmed" or case.case_id in excluded_case_ids:
            continue
        # 对规范化的完整案例计算版本，格式化空格不改变知识版本。
        body = json.dumps(case.model_dump(), ensure_ascii=False, sort_keys=True)
        append_parts([Document(page_content=body)], doc_id=case.case_id,
                     version=hashlib.sha256(body.encode()).hexdigest(), source=f"repair_cases/{case.case_id}.json",
                     source_kind="repair_case", confirmation="confirmed")
    return output


def document_to_chunk(document: Document) -> dict:
    """新库返回完整来源；旧库只显示已有文件名，不编造版本与确认状态。"""
    metadata = document.metadata
    if metadata.get("provenance_status") == "complete":
        return KnowledgeChunk(content=document.page_content, **{
            key: metadata.get(key) for key in (
                "doc_id", "version", "chunk_id", "source", "source_kind", "confirmation", "provenance_status",
            )
        }).model_dump()
    source = metadata.get("source")
    return KnowledgeChunk(content=document.page_content,
                          source=Path(source).name if isinstance(source, str) and source else None).model_dump()


def usable_chunk_ids(chunks) -> set[str]:
    """仅完整且已确认的片段可用于最终回答的机器校验引用。"""
    return {item["chunk_id"] for item in validate_chunks(chunks)
            if item["provenance_status"] == "complete" and item["confirmation"] == "confirmed"}
