---
description: "工厂自检：用 golden-cases/ 固定用例测试 AgentGenesis 自身流水线。V7 隔离约定—在专用空目录执行（副作用落 cwd）。"
argument-hint: "[--ids <ids>] [--domain <letter>] [--keep-runs <n>]"
allowed-tools: Read, Bash, AskUserQuestion
---

# /selftest — AgentGenesis 工厂自检

**做什么**: 用 `golden-cases/` 中的 23 个固定用例，端到端测试 AgentGenesis 自身（意图路由 / 模式匹配 / 两条 pipeline 推进）。
**何时触发**: 用户想验证 AgentGenesis 本体行为，或发布前的工厂级回归。
**输入**: 可选 `--ids`（逗号分隔用例 ID）/ `--domain`（A-K 字母）过滤；`--keep-runs` 报告保留数（默认 5）。
**输出**: `work/e2e-test-ci/latest/report.md` + 每用例会话数据；副作用清单 + 清理指引。

## 第零步：V7 隔离前置检查

被测会话会把 `.agent-genesis/work/` 和 `output/` 写进**你执行命令时的 cwd**。

```bash
if [[ -n "$(ls -A .agent-genesis 2>/dev/null)" || -n "$(ls -A output 2>/dev/null)" ]]; then
    echo "⚠️  当前目录已有 .agent-genesis/ 或 output/ 内容——自检副作用将混入其中。"
    # AskUserQuestion: 继续在当前目录 / 换专用空目录（如 mkdir /tmp/ag-selftest && cd）后重试
fi
```

推荐做法（专用空目录执行）:

```bash
mkdir -p /tmp/ag-selftest && cd /tmp/ag-selftest
```

## 第一步：执行自检

```bash
AGENTGENESIS_ROOT="${CLAUDE_PLUGIN_ROOT:?未检测到 CLAUDE_PLUGIN_ROOT — 请通过官方插件方式安装（见 README.md 安装章节）}"
ENGINE="$AGENTGENESIS_ROOT/skills/e2e-test-runner/scripts/run_e2e.py"

# $ARGUMENTS 直接透传 --ids / --domain / --keep-runs（引擎原生支持）
AGENTGENESIS_TARGET="$PWD" python3 "$ENGINE" --config "$AGENTGENESIS_ROOT/skills/e2e-test-runner/task/suite.yaml" $ARGUMENTS
```

`target_path: "."` 即 `$PWD`：每个用例 spawn 独立 `claude -p` 子进程，cwd = 本目录，进程与 transcript 完全隔离（不会触碰执行者会话），文件系统副作用全部落本目录。

## 第二步：报告 + 副作用治理

```bash
REPORT="work/e2e-test-ci/latest/report.md"
cat "$REPORT"   # 含 "## 副作用清单（V6c）" 段：非报告新增的 .agent-genesis/ output/ 文件

# V6d 清理指引（用户手动执行，先 dry-run 再实删）:
git clean -nfd .agent-genesis output
```

证据（`work/e2e-test-ci/run-<ts>/`）默认保留最近 5 次（`--keep-runs`），轮转自动删超龄目录；被测会话副作用不自动删——按清单自行决定。

详细执行契约见 `skills/e2e-test-runner/references/execution.md`。
