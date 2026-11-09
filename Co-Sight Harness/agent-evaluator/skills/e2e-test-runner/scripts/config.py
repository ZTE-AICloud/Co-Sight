#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py — e2e-test-runner 的全部常量与契约定义。

本模块是唯一的"配置面"：路径形态、并发上限、超时、产物文件名、结果 schema
的键名均在此定义。其余脚本一律 import 本模块，不得就地写魔法数字或字面量。
"""

# ============================== 版本 ==============================

TOOL_VERSION = "e2e-test-runner/0.2.0"

# ============================== 路径形态 ==============================

# 默认探测根：<cwd>/outputs/ 下按目录名倒序找 e2e-test*（相对调用方 cwd）。
RUN_PARENT_DIR = "outputs"
RUN_DIR_GLOB = "e2e-test*"

# 输入侧目录名：e2e-test-generator 的交付目录（--input 探测用）
INPUT_ARTIFACT_DIRNAME = "generated_datasets"
# 输出侧目录名：本 skill 的交付目录，位于 --output 指向的 run 目录之下
OUTPUT_ARTIFACT_DIRNAME = "run_datasets"

SEED_FILENAME = "seed.jsonl"
MANIFEST_FILENAME = "manifest.json"

# --input 指向目录时的探测顺序（先命中者胜）。
# 生成器的交付形态是 <run>/generated_datasets/seed.jsonl，但 --input 也接受
# 直接指向 generated_datasets/ 或 run 目录，两种形态靠这两条探测统一。
SEED_PROBE_RELPATHS = (
    (INPUT_ARTIFACT_DIRNAME, SEED_FILENAME),
    (SEED_FILENAME,),
)

# ============================== 数据契约（seed.jsonl） ==============================

DATA_ID_KEY = "data_id"          # 用例唯一标识，同时用作用例目录名
INPUT_KEY = "input"              # 送进 claude -p stdin 的 prompt；precondition 不入 prompt
TIMEOUT_KEY = "timeout"          # 可选；缺省用 CASE_TIMEOUT_SECONDS
RUN_KEY = "run"                  # 执行结果子对象，回写时新增，原字段一字不改

# manifest.json 里指向被测 agent 根目录的键
AGENT_ROOT_KEY = "agent_root"

# run 子对象的键
RUN_STATUS = "status"
RUN_EXIT_CODE = "exit_code"
RUN_ELAPSED = "elapsed_seconds"
RUN_TIMED_OUT = "timed_out"
# result 文本的完整副本（不截断、不改写；result 非字符串时以 JSON 序列化归一）
RUN_RESULT_PREVIEW = "result_preview"
# 用例目录（5 件产物所在处）；workspace/ 也在其下，但它不是产物
RUN_CASE_DIR = "case_dir"
# 该用例的 agent_root 副本目录，即会话真正的 cwd
RUN_WORKSPACE_DIR = "workspace_dir"
# 仅当用例执行过程本身崩溃（非被测 agent 失败）时出现
RUN_ERROR = "error"
# 会话日志目录（<case_dir>/sessions/）的绝对路径；仅当日志确实拷到时出现
RUN_SESSION_DIR = "session_dir"
# 本用例的会话 id，由 runner 预生成后经 --session-id 交给 CLI。
# 恒出现——它既是日志拷贝的钥匙，也是会话的身份标识，下游 traceaudit 要用。
RUN_SESSION_ID = "session_id"
# 仅当日志没拷到时出现，值是 SESSION_ERROR_* 之一。与 RUN_ERROR 刻意分开：
# status 归被测 Agent（跑没跑成），session_error 归基建（日志录没录到）。
RUN_SESSION_ERROR = "session_error"

# 状态取值
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"

# ============================== 用例目录产物 ==============================

CASE_STDOUT = "stdout.txt"
CASE_STDERR = "stderr.txt"
CASE_RESULT = "result.json"
CASE_TIMING = "timing.json"

# 用例目录下的 agent_root 副本目录名。用例跑在自己那份副本里，彼此不可见，
# 也不写回 agent_root 源目录；复制策略见 run_tests.run_one_case。
WORKSPACE_DIRNAME = "workspace"

# 用例目录下存放 CLI 会话日志的目录名（对齐 agent-genesis 的产物布局）。
# 内容是从 SESSION_LOG_GLOBS 搜来的 <session_id>.jsonl 与 <session_id>/subagents/。
SESSION_DIRNAME = "sessions"

# 会话日志搜索根：claude CLI 把每个会话按 cwd 分目录落在 <config>/projects 下，
# 本机同时存在 ~/.claude 与 ~/.cosight 两个配置根，故用 glob 一并覆盖。
# 刻意**不**重定向 CLAUDE_CONFIG_DIR：那会连带废掉用户级的 hooks / plugins，
# 改变被测 Agent 的运行环境——runner 只忠实执行，不改造环境。
SESSION_LOG_GLOBS = ("~/.*/projects",)

# run.session_error 的取值
SESSION_ERROR_NOT_FOUND = "not_found"        # 磁盘上没有该会话的日志
SESSION_ERROR_COPY_FAILED = "copy_failed"    # 找到了但拷贝失败（IO 错误）

# 迭代产物侧的环境记录：agent_root 源路径 + 期望/实算树哈希 + 隔离模式
RUN_MANIFEST_FILENAME = "run-manifest.json"

# ============================== 执行参数 ==============================

# 单用例超时（秒）；seed 记录里带 timeout 字段时以它为准
CASE_TIMEOUT_SECONDS = 600
# kill 之后等待回收的宽限期（秒）
KILL_GRACE_SECONDS = 5

DEFAULT_CONCURRENCY = 1
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 32

CLAUDE_CLI = "claude"
# 注意：**没有** --no-session-persistence。该 flag 会让会话不落盘，session_id
# 照常有值但磁盘上找不到任何日志——日志拉取会 100% 落空（已实测确认）。
# 会话 id 由 runner 预生成（见 CLAUDE_SESSION_ID_FLAG），因此超时被 kill、
# stdout 无法解析、CLI 缺失这些拿不到 result 的场景同样能定位到日志。
CLAUDE_ARGS = [
    "-p",
    "--permission-mode", "bypassPermissions",
    "--output-format", "json",
]
# 运行时拼接：<CLAUDE_CLI> <CLAUDE_ARGS...> --session-id <uuid4>
CLAUDE_SESSION_ID_FLAG = "--session-id"
# 与 run_e2e.py 保持一致：屏蔽非白名单 MCP，避免被测会话被宿主的 MCP 配置干扰
CLAUDE_ENV_EXTRA = {"CLAUDE_CODE_DISABLE_NONWHITELISTED_MCP": "1"}

# data_id 用作目录名，禁止出现路径分隔符或跳转段
FORBIDDEN_CASE_ID_PARTS = ("/", "\\", "..")
