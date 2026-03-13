import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from queue import Queue
from typing import List, Dict, Any, Optional

# 安全路径检查（供工具函数使用）
def safe_path(work_dir: Path, p: str) -> Path:
    path = (work_dir / p).resolve()
    if not str(path).startswith(str(work_dir.resolve())):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

# Token估算（简单字符数/4）
def estimate_tokens(messages: List[Dict]) -> int:
    return len(json.dumps(messages, default=str)) // 4

# 微压缩：清理过长的 tool_result 内容
def microcompact(messages: List[Dict]):
    indices = []
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    indices.append(part)
    if len(indices) <= 3:
        return
    for part in indices[:-3]:
        if isinstance(part.get("content"), str) and len(part["content"]) > 100:
            part["content"] = "[cleared]"