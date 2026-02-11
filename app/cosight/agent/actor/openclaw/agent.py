# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
OpenclawAgent：与 TaskActorAgent 同级，将用户消息转发到 18789 端口的 OpenClaw Gateway，
取回回复后通过 plan_process 事件在前端呈现。不依赖 LLM/tools，由上层注入 openclaw_sender。
"""

import ast
import json
from typing import Dict, Any, Callable

from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
from app.cosight.task.plan_report_manager import plan_report_event_manager
from app.cosight.task.task_manager import TaskManager
from app.cosight.task.time_record_util import time_record
from app.common.logger_util import logger


def _format_openclaw_history_to_text(raw: Dict[str, Any]) -> str:
    """
    将 OpenClaw send_message_and_get_history 的返回转为前端可展示的字符串。
    """
    if not isinstance(raw, dict):
        return str(raw) if raw is not None else ""

    error = raw.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if raw.get("ok") is False and error:
        return str(error) if isinstance(error, str) else str(error.get("message", error))

    payload = raw.get("payload") or {}
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return str(raw)[:2000] if raw else ""

    parts = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or msg.get("roleName")
        if role and str(role).lower() not in ("assistant", "ai", "bot"):
            continue
        content = msg.get("content") or msg.get("text")
        if content is None:
            continue
        if isinstance(content, list):
            for seg in content:
                if isinstance(seg, dict) and seg.get("type") == "text" and seg.get("text"):
                    parts.append(str(seg["text"]).strip())
        else:
            parts.append(str(content).strip())
    if parts:
        return "\n".join(parts).strip()
    return str(raw)[:2000] if raw else ""


def _openclaw_messages_to_segments(raw: Dict[str, Any]) -> list:
    """将 payload.messages 转为前端可按角色展示的 segments 列表。"""
    if not isinstance(raw, dict):
        return []
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    messages = payload.get("messages") or raw.get("messages")
    if not isinstance(messages, list):
        return []

    segments = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = (msg.get("role") or msg.get("roleName") or "assistant")
        role = str(role).lower()
        if role not in ("user", "assistant", "ai", "bot"):
            role = "assistant"
        content = msg.get("content") or msg.get("text")
        if isinstance(content, str) and content.strip().startswith("["):
            try:
                content = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                try:
                    content = ast.literal_eval(content)
                except (ValueError, SyntaxError):
                    pass

        if isinstance(content, list):
            for seg in content:
                if not isinstance(seg, dict):
                    continue
                seg_type = seg.get("type") or "text"
                if seg_type == "thinking":
                    segments.append({
                        "messageType": "thinking",
                        "role": "assistant",
                        "content": seg.get("thinking") or seg.get("content") or "",
                    })
                elif seg_type == "toolCall":
                    segments.append({
                        "messageType": "toolCall",
                        "role": "assistant",
                        "toolName": seg.get("name") or "tool",
                        "arguments": seg.get("arguments") or {},
                    })
                elif seg_type == "toolResult":
                    segments.append({
                        "messageType": "toolResult",
                        "role": "assistant",
                        "toolName": seg.get("name") or "tool",
                        "content": seg.get("content") or seg.get("result") or "",
                        "isError": seg.get("isError") or False,
                    })
                elif seg_type == "text":
                    segments.append({
                        "messageType": "text",
                        "role": "assistant",
                        "content": seg.get("text") or seg.get("content") or "",
                    })
        else:
            segments.append({
                "messageType": "text",
                "role": "user" if role == "user" else "assistant",
                "content": str(content).strip() if content is not None else "",
            })
    return segments


class OpenclawAgent:
    """
    与 TaskActorAgent 同级的执行器：收到消息后通过 openclaw_sender 发往 18789 端口，
    取回响应并写入 plan 的 step_notes，通过 plan_process 推送到前端。
    """

    AGENT_ID = "openclaw"
    DESCRIPTION = (
        "本地文件智能执行器（OpenClaw）。专门负责对本地文件系统进行操作，例如遍历指定目录"
        "（如 /home/... 或工作区目录）、批量收集/筛选/重命名/移动文件、解析日志或配置文件等。"
        "当步骤描述中明确提到“访问工作区目录”“从某文件夹收集文件”“遍历/扫描本地目录”“处理 /home/... 等本地路径”"
        "并且主要目标是获取/整理本地文件，而不是直接生成完整分析报告时，应优先选择本执行器。仅当系统已配置 openclaw_sender 时可用。"
    )
    ICON_FILENAME = "openclaw.svg"

    def __init__(
        self,
        agent_instance: AgentInstance,
        plan_id: str,
        work_space_path: str,
        openclaw_sender: Callable[..., Dict[str, Any]],
    ):
        self.agent_instance = agent_instance
        self.plan_id = plan_id
        self.work_space_path = work_space_path or ""
        self.openclaw_sender = openclaw_sender

        self.plan = TaskManager.get_plan(plan_id)
        if self.plan is None:
            raise ValueError(
                f"Plan with id '{plan_id}' not found in TaskManager. "
                f"Available plans: {list(TaskManager.plans.keys())}"
            )
        logger.info(f"OpenclawAgent: plan_id={plan_id}, plan steps count={len(self.plan.steps)}")

    def _build_prev_steps_context(self, current_step_index: int) -> str:
        """构造前置已完成步骤摘要，发给 OpenClaw 作为上下文。"""
        if not self.plan or not getattr(self.plan, "steps", None):
            return "（暂无已完成的前置步骤）"

        lines = []
        for i, step in enumerate(self.plan.steps):
            if i >= current_step_index:
                break
            status = self.plan.step_statuses.get(step)
            if status != "completed":
                continue

            note = ""
            files_info = ""
            try:
                note = (self.plan.step_notes or {}).get(step, "") or ""
            except Exception:
                note = ""
            try:
                files = (self.plan.step_files or {}).get(step, "")
            except Exception:
                files = ""

            if isinstance(files, list):
                file_items = []
                for f in files:
                    if not isinstance(f, dict):
                        continue
                    name = f.get("name") or ""
                    path = f.get("path") or ""
                    if name and path:
                        file_items.append(f"{name} ({path})")
                    elif path:
                        file_items.append(path)
                    elif name:
                        file_items.append(name)
                if file_items:
                    files_info = "；".join(file_items)
            elif files:
                files_info = str(files)

            line = f"Step{i}（已完成）: {step}"
            if note:
                line += f"\n备注: {note}"
            if files_info:
                line += f"\n相关文件: {files_info}"
            lines.append(line)

        if not lines:
            return "（暂无已完成的前置步骤）"
        return "\n\n".join(lines)

    @time_record
    def act(self, question: str, step_index: int) -> str:
        """执行一步：将用户问题与当前步骤发往 OpenClaw Gateway，结果写入 plan 并发布 plan_process。"""
        if self.plan is None:
            logger.error(f"OpenclawAgent.act: self.plan is None for step_index {step_index}")
            raise ValueError("Plan is None. Cannot execute step.")

        step_desc = self.plan.steps[step_index] if 0 <= step_index < len(self.plan.steps) else ""
        prev_context = self._build_prev_steps_context(step_index)
        message_to_send = (
            f"【用户问题】{question}\n"
            f"【前置步骤摘要】\n{prev_context}\n\n"
            f"【当前步骤】{step_desc or question}"
        )

        self.plan.mark_step(step_index, step_status="in_progress")
        plan_report_event_manager.publish("plan_process", self.plan)

        try:
            session_key = f"agent:main:cosight:{self.plan_id}:step_{step_index}"
            raw = self.openclaw_sender(message_to_send, session_key)
            response_text = _format_openclaw_history_to_text(raw)
            self.plan.mark_step(
                step_index,
                step_status="completed",
                step_notes=response_text or "(无文本回复)",
            )
            plan_report_event_manager.publish("plan_process", self.plan)
            segments = _openclaw_messages_to_segments(raw)
            plan_report_event_manager.publish(
                "openclaw_step_display",
                self.plan_id,
                event_data={
                    "type": "openclaw-step-response",
                    "plan_id": self.plan_id,
                    "step_index": step_index,
                    "step_title": step_desc,
                    "content": response_text or "(无文本回复)",
                    "segments": segments,
                },
            )
            return response_text or "(无文本回复)"
        except Exception as e:
            logger.error(f"OpenclawAgent.act error: {e}", exc_info=True)
            err_msg = str(e)
            self.plan.mark_step(step_index, step_status="blocked", step_notes=err_msg)
            plan_report_event_manager.publish("plan_process", self.plan)
            return err_msg
