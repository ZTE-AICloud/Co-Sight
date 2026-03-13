import json
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.common.logger_util import logger
from app.cosight.llm.chat_llm import ChatLLM

from .models import TodoManager, TaskManager, BackgroundManager, MessageBus, TeammateManager
from .tools import TOOLS, TOOL_HANDLERS, run_bash, run_read, run_write, run_edit
from .utils import safe_path, estimate_tokens, microcompact

class FullAgent:
    def __init__(self, work_dir: Path, model_config: dict):
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # 初始化各个管理器
        self.todo = TodoManager()
        self.tasks_dir = work_dir / ".tasks"
        self.task_mgr = TaskManager(self.tasks_dir)

        self.bg = BackgroundManager()

        self.inbox_dir = work_dir / ".team" / "inbox"
        self.bus = MessageBus(self.inbox_dir)

        self.team_dir = work_dir / ".team"
        self.team = TeammateManager(self.bus, self.task_mgr, self.team_dir)

        self.skills_dir = work_dir / "skills"
        # 简化：技能加载功能暂略，可后续扩展

        # 消息历史
        self.messages: List[Dict] = []

        # LLM 实例
        self.llm = ChatLLM(**model_config)

        # 压缩阈值
        self.token_threshold = 100000

        # 用于 plan approval 和 shutdown 的临时存储（可移到实例变量）
        self.shutdown_requests = {}
        self.plan_requests = {}

        logger.info(f"FullAgent initialized at {self.work_dir}")

    @property
    def system_prompt(self) -> str:
        # 可根据需要动态生成，这里保持简洁
        return f"""You are a coding agent at {self.work_dir}. Use tools to solve tasks.
Prefer task_create/task_update/task_list for multi-step work. Use TodoWrite for short checklists.
Available tools: bash, read_file, write_file, edit_file, TodoWrite, task (subagent), load_skill, compress,
background_run, check_background, task_create, task_get, task_update, task_list, spawn_teammate,
list_teammates, send_message, read_inbox, broadcast, shutdown_request, plan_approval, idle, claim_task."""

    def process_message(self, user_input: str) -> str:
        """处理单条用户消息，返回最终响应文本"""
        self.messages.append({"role": "user", "content": user_input})

        # 压缩预处理
        microcompact(self.messages)
        if estimate_tokens(self.messages) > self.token_threshold:
            logger.info("Auto-compact triggered")
            self.messages = self._auto_compact(self.messages)

        # 检查后台任务通知
        notifs = self.bg.drain()
        if notifs:
            txt = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            self.messages.append({"role": "user", "content": f"<background-results>\n{txt}\n</background-results>"})
            self.messages.append({"role": "assistant", "content": "Noted background results."})

        # 检查收件箱
        inbox = self.bus.read_inbox("lead")
        if inbox:
            self.messages.append({"role": "user", "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"})
            self.messages.append({"role": "assistant", "content": "Noted inbox messages."})

        # 调用 LLM
        response = self.llm.client.chat.completions.create(
            model=self.llm.model,
            messages=[{"role": "system", "content": self.system_prompt}] + self.messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=self.llm.max_tokens,
            temperature=self.llm.temperature
        )
        assistant_msg = response.choices[0].message
        self.messages.append(assistant_msg)

        # 处理工具调用
        if assistant_msg.tool_calls:
            results = []
            used_todo = False
            manual_compress = False
            for tool_call in assistant_msg.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                if func_name == "compress":
                    manual_compress = True
                # 调用对应的处理函数（注意需要传入 work_dir）
                handler = TOOL_HANDLERS.get(func_name)
                if handler:
                    try:
                        # 部分工具需要 work_dir，部分不需要，需适配
                        if func_name in ["bash", "read_file", "write_file", "edit_file"]:
                            output = handler(self.work_dir, **args)
                        else:
                            output = handler(**args)
                    except Exception as e:
                        output = f"Error: {e}"
                else:
                    output = f"Unknown tool: {func_name}"
                logger.info(f"> {func_name}: {str(output)[:200]}")
                results.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(output)
                })
                if func_name == "TodoWrite":
                    used_todo = True

            # 检查 todo 提醒
            rounds_without_todo = 0  # 需要跟踪状态，这里简化处理
            if self.todo.has_open_items() and rounds_without_todo >= 3:
                results.insert(0, {"role": "system", "content": "<reminder>Update your todos.</reminder>"})
            self.messages.extend(results)

            # 手动压缩
            if manual_compress:
                logger.info("Manual compact triggered")
                self.messages = self._auto_compact(self.messages)

            # 递归调用直到没有工具调用（或达到限制）
            return self.process_message("")  # 传入空字符串表示继续处理工具结果
        else:
            # 最终响应
            return assistant_msg.content or ""

    def _auto_compact(self, messages: List[Dict]) -> List[Dict]:
        """压缩对话历史"""
        transcript_dir = self.work_dir / ".transcripts"
        transcript_dir.mkdir(exist_ok=True)
        path = transcript_dir / f"transcript_{int(time.time())}.jsonl"
        with open(path, "w") as f:
            for msg in messages:
                f.write(json.dumps(msg, default=str) + "\n")
        conv_text = json.dumps(messages, default=str)[:80000]
        resp = self.llm.chat([{"role": "user", "content": f"Summarize for continuity:\n{conv_text}"}])
        summary = resp.content  # 根据 ChatLLM 返回调整
        return [
            {"role": "user", "content": f"[Compressed. Transcript: {path}]\n{summary}"},
            {"role": "assistant", "content": "Understood. Continuing with summary context."}
        ]