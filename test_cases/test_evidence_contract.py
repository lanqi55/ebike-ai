"""使用固定假模型验证证据边界，不把预设回答当作模型诊断质量。"""

from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from ebike_ai import api
from ebike_ai.agent_factory import build_agent
from ebike_ai.config import PROJECT_ROOT
from ebike_ai.core.tool_registry import SearchArguments, Tool, ToolRegistry, ToolResult
from ebike_ai.evaluation.judges import EvidenceJudge, HallucinationJudge
from ebike_ai.knowledge import document_to_chunk, prepare_documents, validate_chunks
from ebike_ai.voltage_rules import battery_data_with_rules


class SequenceModel:
    """逐次返回预设内容，并复制模型实际收到的证据。"""
    def __init__(self, replies):
        self.replies = iter(replies)
        self.inputs = []

    def bind_tools(self, schemas):
        return self

    def invoke(self, messages):
        self.inputs.append(deepcopy(messages))
        return next(self.replies)


def sample_chunks():
    docs = prepare_documents(PROJECT_ROOT / "no-reference", PROJECT_ROOT / "data" / "repair_cases")
    return [document_to_chunk(next(doc for doc in docs if doc.metadata["doc_id"] == name))
            for name in ("CASE-001", "CASE-002")]


def search_call(identifier="search-1"):
    return AIMessage(content="", tool_calls=[{
        "id": identifier, "name": "search_repair_knowledge", "args": {"query": "故障"},
    }])


def agent_for(chunks, replies):
    model = SequenceModel(replies)
    registry = ToolRegistry()
    registry.register(Tool("search_repair_knowledge", "测试来源检索", lambda query: chunks,
                           args_model=SearchArguments, output_validator=validate_chunks))
    return build_agent(llm=model, registry=registry), model


@pytest.mark.unit
def test_valid_citation_reaches_model_and_api_state_with_source():
    chunks = sample_chunks()[:1]
    answer = f"仅作历史参考，请补充本车检查结果，配件待确认。[来源:{chunks[0]['chunk_id']}]"
    agent, model = agent_for(chunks, [search_call(), AIMessage(content=answer)])
    actual, state = agent.run("灯失效")
    assert actual == answer and state["status"] == "completed"
    assert json.loads(model.inputs[-1][-1]["content"])["data"] == chunks
    assert json.loads(state["retrieved_docs"])["data"] == chunks
    assert EvidenceJudge().judge({}, actual, state)["passed"] is True


@pytest.mark.unit
@pytest.mark.parametrize("answer", ["直接更换部件", "建议换件[来源:invented]", "建议换件[来源:broken"])
def test_missing_unknown_and_malformed_citations_cannot_escape(answer):
    agent, _ = agent_for(sample_chunks(), [search_call(), AIMessage(content=answer)])
    actual, state = agent.run("故障")
    assert state["status"] == "insufficient_evidence" and "证据不足" in actual
    assert answer not in actual and not agent.memory.buffer
    assert EvidenceJudge().judge({}, actual, state)["passed"] is None


@pytest.mark.unit
def test_no_tool_call_cannot_bypass_production_evidence_requirement():
    model = SequenceModel([AIMessage(content="电池完全正常")])
    agent = build_agent(llm=model)
    answer, state = agent.run("车辆无法启动")
    assert state["status"] == "insufficient_evidence" and "完全正常" not in answer
    assert not agent.memory.buffer


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["empty", "legacy", "unconfirmed"])
def test_no_trusted_sources_stops_before_second_model_call(kind):
    chunks = sample_chunks()[:1]
    if kind == "empty":
        chunks = []
    elif kind == "legacy":
        chunks = [{"content": "缺少出处的正文"}]
    else:
        chunks[0]["confirmation"] = "unconfirmed"
    agent, model = agent_for(chunks, [search_call()])
    answer, state = agent.run("故障")
    assert state["status"] == "insufficient_evidence" and "复检" in answer
    assert len(model.inputs) == 1


@pytest.mark.unit
def test_unconfirmed_source_cannot_hide_next_to_confirmed_source():
    chunks = sample_chunks()
    chunks[1]["confirmation"] = "unconfirmed"
    agent, _ = agent_for(chunks, [search_call(), AIMessage(content=f"建议[来源:{chunks[1]['chunk_id']}]")])
    _, state = agent.run("故障")
    assert state["status"] == "insufficient_evidence"


@pytest.mark.unit
@pytest.mark.parametrize("conflict", [False, True])
def test_multiple_searches_keep_all_citations_and_reject_version_conflict(conflict):
    chunks = sample_chunks()
    if conflict:
        chunks[1] = {**chunks[0], "version": "f" * 64,
                     "chunk_id": f"{chunks[0]['doc_id']}-{'f' * 12}-0000"}
    batches = iter([[chunks[0]], [chunks[1]]])
    registry = ToolRegistry()
    registry.register(Tool("search_repair_knowledge", "测试", lambda query: next(batches),
                           args_model=SearchArguments, output_validator=validate_chunks))
    replies = [search_call(), search_call("search-2")]
    if not conflict:
        replies.append(AIMessage(content=f"仅作参考[来源:{chunks[0]['chunk_id']}] [来源:{chunks[1]['chunk_id']} ]".replace(" ]", "]")))
    model = SequenceModel(replies)
    answer, state = build_agent(llm=model, registry=registry).run("故障")
    assert state["status"] == ("insufficient_evidence" if conflict else "completed")
    if not conflict:
        assert json.loads(state["retrieved_docs"])["data"] == chunks


@pytest.mark.unit
def test_voltage_without_vehicle_context_stops_before_model_invents_threshold():
    registry = ToolRegistry()
    registry.register(Tool("get_battery_data", "合成测量", lambda: {
        "cell1": 3, "cell2": 3, "cell3": 3, "total_vol": 9,
    }, output_validator=battery_data_with_rules))
    model = SequenceModel([AIMessage(content="", tool_calls=[{"id": "1", "name": "get_battery_data", "args": {}}])])
    answer, state = build_agent(llm=model, registry=registry).run("电池如何")
    assert state["status"] == "insufficient_evidence" and "电池类型" in answer
    assert json.loads(state["hardware_data"])["data"]["rule_result"]["status"] == "insufficient_evidence"
    assert len(model.inputs) == 1


@pytest.mark.unit
def test_hallucination_judge_sees_source_metadata():
    prompts = []
    class JudgeModel:
        def invoke(self, prompt):
            prompts.append(prompt)
            return AIMessage(content="无幻觉")
    chunks = sample_chunks()
    HallucinationJudge(JudgeModel()).judge({"hardware_data": {"unobserved": "不可冒充已取证"}}, "建议", {
        "retrieved_docs": ToolResult(ok=True, data=chunks).to_json(),
        "hardware_data": ToolResult(ok=True, data={"rule_result": {"status": "insufficient_evidence"}}).to_json(),
    })
    assert chunks[0]["chunk_id"] in prompts[0] and chunks[0]["version"] in prompts[0]
    assert "不是当前车辆事实" in prompts[0]
    assert "insufficient_evidence" in prompts[0] and "不可冒充已取证" not in prompts[0]


@pytest.mark.unit
def test_successful_cli_history_does_not_authorize_old_citations_in_new_run():
    chunks = sample_chunks()[:1]
    cited = f"历史参考[来源:{chunks[0]['chunk_id']}]"
    agent, _ = agent_for(chunks, [search_call(), AIMessage(content=cited), AIMessage(content=cited)])
    assert agent.run("车辆甲")[1]["status"] == "completed"
    answer, state = agent.run("车辆乙")
    assert state["status"] == "insufficient_evidence" and "没有来源" in answer
    assert len(agent.memory.buffer) == 1


@pytest.mark.unit
def test_same_chunk_id_with_different_text_is_rejected():
    from ebike_ai.evidence import merge_chunks
    chunk = sample_chunks()[0]
    with pytest.raises(ValueError, match="不同内容"):
        merge_chunks([chunk], [{**chunk, "content": "同编号被修改的正文"}])


@pytest.mark.integration
def test_diagnose_top_level_schema_stays_compatible_and_failure_does_not_leak(monkeypatch):
    chunks = sample_chunks()[:1]
    agent, _ = agent_for(chunks, [search_call(), AIMessage(content="错误结论[来源:invented]")])
    monkeypatch.setattr(api, "build_agent", lambda: agent)
    with TestClient(api.app) as client:
        response = client.post("/diagnose", json={"fault_text": "故障"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "iteration_count", "hardware_data", "retrieved_docs", "tool_trace"}
    assert isinstance(body["retrieved_docs"], str) and json.loads(body["retrieved_docs"])["data"] == chunks
    assert "错误结论" not in body["answer"] and "invented" not in body["answer"]
