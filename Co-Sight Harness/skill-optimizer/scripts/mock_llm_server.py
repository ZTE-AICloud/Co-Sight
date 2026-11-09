#!/usr/bin/env python3
"""Mock LLM server for skillx-cosight self-test.

用法（无真实 ANTHROPIC_API_KEY 时也能跑端到端）：
    1. 启动：python3 scripts/mock_llm_server.py --port 18080
    2. 配置 config/optimize-user-config.yaml：
         llm_api:
           model:
             name: mock-llm
             base_url: http://127.0.0.1:18080
             api_key: sk-mock-dummy
    3. 跑：node openclaw.mjs skillx-cosight optimize <SKILL.md>

协议：Anthropic Messages API 兼容（POST /v1/messages）
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def detect_role(user_prompt: str, system: str) -> str:
    blob = (system + "\n" + user_prompt).lower()
    if "evaluator" in blob or "评分" in blob or "score" in blob or "rubric" in blob:
        return "evaluator"
    if "optimizer" in blob or "modifications" in blob or "优化" in blob or "propose" in blob:
        return "proposer"
    return "generic"


def make_evaluator_response(user_prompt: str) -> str:
    text = user_prompt
    has_failure_section = "失败处理" in text or "failure" in text.lower()
    has_checkpoint = "🔴" in text or "checkpoint" in text.lower() or "STOP" in text
    has_frontmatter = text.startswith("---") or "name:" in text[:200]
    import re
    has_dim_specificity = bool(re.search(r"--\w+", text))
    has_consistency = "##" in text

    dim3 = 8.0 if has_failure_section else 3.5
    dim4 = 7.5 if has_checkpoint else 4.0
    dim5 = 7.0 if has_dim_specificity else 4.5
    dim6 = 7.5 if has_consistency else 5.0

    return json.dumps({
        "dim_scores": {
            "dim1_frontmatter": 8.0 if has_frontmatter else 4.0,
            "dim2_workflow": 6.5,
            "dim3_failure_modes": dim3,
            "dim4_checkpoints": dim4,
            "dim5_specificity": dim5,
            "dim6_consistency": dim6,
            "dim7_anti_pattern": 6.0,
            "dim8_global_context": 6.5,
            "dim9_design_form": 6.0,
            "dim10_coverage": 5.0,
            "dim11_safety": 8.0,
            "dim12_efficiency": 8.0,
        },
        "gaps": [
            {"type": "missing", "severity": "high", "message": "缺少失败处理三段式"}
        ] if not has_failure_section else [],
    }, ensure_ascii=False)


def make_proposer_response(user_prompt: str) -> str:
    return json.dumps({
        "round": 1,
        "diagnosis": {
            "weakest_dims": ["dim3_failure_modes", "dim4_checkpoints"],
            "weakest_sections": [
                {"dim": "dim3_failure_modes", "file": "SKILL.md", "section": "异常处理",
                 "root_cause": "未定义三段式失败处理"}
            ]
        },
        "modifications": [
            {
                "id": "M1",
                "file": "SKILL.md",
                "section": "## 3. 异常处理",
                "operation": "replace",
                "old_text": "如果文件不存在则跳过。",
                "new_text": (
                    "如果文件不存在则跳过。\n\n"
                    "#### 失败处理（三段式）\n\n"
                    "| 失败类型 | 触发条件 | 一线修复 | 仍失败兜底 |\n"
                    "|---------|---------|---------|-----------|\n"
                    "| 文件不存在 | $ARGUMENTS 为空 | 提示输入用法 | exit 12 |\n"
                    "| 解析失败 | 文本非 markdown | 提示格式 | exit 13 |\n"
                    "| 超时 | 超过 30s | 重试 1 次 | exit 14 |\n"
                ),
                "rationale": "加入三段式失败处理覆盖 dim3"
            },
        ],
        "coverage": ["dim3_failure_modes"],
        "uncovered_gaps": [],
        "expert_guidance_ref": ""
    }, ensure_ascii=False)


def make_response(role: str, user_prompt: str) -> str:
    if role == "evaluator":
        return make_evaluator_response(user_prompt)
    if role == "proposer":
        return make_proposer_response(user_prompt)
    return json.dumps({"echo": user_prompt[:100]}, ensure_ascii=False)


class MockLLMHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path != "/v1/messages":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        user_prompt = ""
        if req.get("messages"):
            user_prompt = req["messages"][-1].get("content", "")
        system = req.get("system", "")
        role = detect_role(user_prompt, system)
        response_text = make_response(role, user_prompt)

        resp = {
            "id": f"msg_mock_{hash(response_text) % 10000}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": response_text}],
            "model": req.get("model", "mock-llm"),
            "stop_reason": "end_turn",
            "usage": {"input_tokens": len(user_prompt), "output_tokens": len(response_text)},
        }
        resp_bytes = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)


def main():
    parser = argparse.ArgumentParser(description="Mock LLM server for skillx-cosight self-test")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), MockLLMHandler)
    print(f"[mock-llm] 监听 {args.host}:{args.port}（Anthropic Messages 协议）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()