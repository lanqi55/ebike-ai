"""第五周离线证据演示：真实 Agent、固定假模型与假检索，结果不代表诊断准确率。"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from ebike_ai.agent_factory import build_agent
from ebike_ai.config import PROJECT_ROOT
from ebike_ai.core.tool_registry import Tool, ToolRegistry, SearchArguments
from ebike_ai.knowledge import document_to_chunk, load_cases, prepare_documents, validate_chunks


class DemoModel:
    """按测试场景生成固定回复，不进行真实语言推理。"""
    def __init__(self, mode):
        self.mode = mode
        self.inputs = []

    def bind_tools(self, schemas):
        return self

    def invoke(self, messages):
        self.inputs.append(deepcopy(messages))
        if len(self.inputs) == 1:
            return AIMessage(content="", tool_calls=[{
                "id": "demo-search", "name": "search_repair_knowledge", "args": {"query": "离线固定检索"},
            }])
        chunk = json.loads(messages[-1]["content"])["data"][0]
        identifier = "not-returned" if self.mode == "invalid_citation" else chunk["chunk_id"]
        return AIMessage(content=f"历史片段仅供参考，本车具体检查结果仍需补充，配件待确认。[来源:{identifier}]")


def run_demo():
    """每个真实案例使用留一语料，分别验证合法引用、空结果、旧来源及错误引用。"""
    directory = PROJECT_ROOT / "data" / "repair_cases"
    results = []
    cases = load_cases(directory)
    for case in cases:
        documents = prepare_documents(PROJECT_ROOT / "data" / "repair_docs", directory,
                                      excluded_case_ids=[case.case_id])
        assert all(doc.metadata["doc_id"] != case.case_id for doc in documents)
        chunks = [document_to_chunk(documents[0])]
        for mode in ("valid_citation", "empty", "legacy", "invalid_citation"):
            selected = [] if mode == "empty" else [{"content": "合成旧资料，无来源"}] if mode == "legacy" else chunks
            registry = ToolRegistry()
            registry.register(Tool("search_repair_knowledge", "固定假检索", lambda query: selected,
                                   args_model=SearchArguments, output_validator=validate_chunks))
            model = DemoModel(mode)
            answer, state = build_agent(llm=model, registry=registry).run(case.diagnosis_input())
            expected = "completed" if mode == "valid_citation" else "insufficient_evidence"
            input_fields = set(json.loads(case.diagnosis_input()))
            passed = (state["status"] == expected and "not-returned" not in answer
                      and not {"final_diagnosis", "repair_actions", "recheck"} & input_fields
                      and all(case.final_diagnosis not in str(messages) for messages in model.inputs))
            results.append({
                "case_id": case.case_id, "scenario": mode, "passed": passed,
                "expected_status": expected, "actual_status": state["status"], "answer": answer,
                "retrieved_docs": json.loads(state["retrieved_docs"]),
                "held_out_case": case.case_id, "model_calls": len(model.inputs),
                "error": None if passed else "证据状态、引用检查或输入隔离不符合预期",
            })
    return {"mode": "offline_contract", "real_case_count": len(cases), "scenario_count": len(results),
            "passed": sum(row["passed"] for row in results),
            "failures": [row for row in results if not row["passed"]], "results": results,
            "limitation": "假模型和固定假检索仅验证契约；其他案例不代表相关命中，未验证真实诊断或检索质量。"}


def main():
    """默认报告写入被 Git 忽略的 reports 目录，失败时返回非零退出码。"""
    parser = argparse.ArgumentParser(description="第五周离线证据回归")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "week5" / "evidence-demo.json")
    args = parser.parse_args()
    # 此演示不使用 HTTP 客户端，所有网络连接都应被拒绝。
    with patch("socket.socket.connect", side_effect=AssertionError("离线演示禁止联网")), patch(
        "socket.create_connection", side_effect=AssertionError("离线演示禁止联网")
    ):
        report = run_demo()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"真实案例 {report['real_case_count']} 条；离线场景 {report['passed']}/{report['scenario_count']} 通过。")
    print(report["limitation"])
    print(f"报告：{args.output}")
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
