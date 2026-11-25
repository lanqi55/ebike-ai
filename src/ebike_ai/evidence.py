"""证据与引用的确定性检查，不把字符串引用校验冒充诊断正确性验证。"""

import re

from ebike_ai.knowledge import usable_chunk_ids, validate_chunks


def merge_chunks(previous, incoming) -> list[dict]:
    """聚合本次运行实际返回的片段；同编号异文或同文档异版本视为冲突。"""
    chunks = validate_chunks([*previous, *incoming])
    versions = {}
    unique = {}
    legacy = []
    for chunk in chunks:
        if chunk["provenance_status"] != "complete":
            legacy.append(chunk)
            continue
        doc_id, version, chunk_id = chunk["doc_id"], chunk["version"], chunk["chunk_id"]
        if doc_id in versions and versions[doc_id] != version:
            raise ValueError("同一文档出现不同版本")
        if chunk_id in unique and unique[chunk_id] != chunk:
            raise ValueError("同一片段编号出现不同内容")
        versions[doc_id] = version
        unique[chunk_id] = chunk
    return [*unique.values(), *legacy]


def citation_problem(answer: str, chunks) -> str | None:
    """检查规定格式的引用是否属于本次已确认片段；不推断句子是否有事实支撑。"""
    allowed = usable_chunk_ids(chunks)
    if not allowed:
        return "没有来源完整且已确认的检索证据"
    cited = re.findall(r"\[来源:([^\]\r\n]+)\]", answer)
    if not cited:
        return "回答未提供可核对的片段引用"
    if any(identifier not in allowed for identifier in cited):
        return "回答引用了本次未返回或尚未确认的片段"
    if answer.count("[来源") != len(cited):
        return "回答的来源引用格式不完整"
    return None


def insufficient_answer(reason: str) -> str:
    """统一保守回答，只包含服务端检查原因，不包含被拒绝的模型结论。"""
    return f"当前证据不足：{reason}。请补充对应检查或资料，由维修师复检；暂不确定故障及更换配件。"
