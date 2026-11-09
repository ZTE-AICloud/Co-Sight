#!/usr/bin/env python3
"""rag-knowledge-search 的 stdin/stdout 执行入口。

协议（供 Agent 调用）::

    echo '{"question": "..."}' | python execute.py

标准输入（JSON）::

    {
      "question":        "必填，非空字符串",
      "conversation_id": "可选，多轮会话标识；缺省自动生成 UUID",
      "dialogue_id":     "已废弃，conversation_id 的旧别名（仅兼容旧调用方）",
      "workflow_id":     "可选，覆盖注入的 RAG 工作流 id"
    }

标准输出（JSON）::

    {"success", "answer", "conversation_id", "dialogue_id",
     "citations", "placeholder", "error", "retrieval"}

退出码：0 = 查询成功；1 = 输入非法或查询失败（stdout 仍输出完整 JSON）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag_knowledge_search import rag_knowledge_search  # noqa: E402


def emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def fail(error: str, conversation_id: str = "") -> int:
    emit({
        "success": False,
        "answer": "",
        "conversation_id": conversation_id,
        "dialogue_id": conversation_id,
        "citations": [],
        "placeholder": {},
        "error": error,
        "retrieval": None,
    })
    return 1


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return fail("INVALID_INPUT: 标准输入为空，需提供 JSON {question, conversation_id?}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return fail(f"INVALID_INPUT: 非法 JSON: {exc}")

    if not isinstance(payload, dict):
        return fail("INVALID_INPUT: 标准输入必须是 JSON 对象")

    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        return fail("INVALID_INPUT: question 必填且不能为空")

    conversation_id = payload.get("conversation_id")
    if conversation_id is not None and not isinstance(conversation_id, str):
        return fail("INVALID_INPUT: conversation_id 必须是字符串")

    dialogue_id = payload.get("dialogue_id")
    if dialogue_id is not None and not isinstance(dialogue_id, str):
        return fail("INVALID_INPUT: dialogue_id 必须是字符串")

    result = rag_knowledge_search(
        question=question,
        conversation_id=conversation_id or None,
        dialogue_id=dialogue_id or None,
        workflow_id=payload.get("workflow_id"),
    )
    emit(result)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
