#!/usr/bin/env bash
# ============================================================
# AgentGenesis — 双平台安装脚本
#
# Claude Code（官方插件机制）:
#   本仓库即 marketplace（.claude-plugin/marketplace.json），
#   脚本执行: claude plugin marketplace add <repo>
#            claude plugin install agent-genesis@agent-genesis --scope user
#   本地 marketplace 原地加载，源码改动下次会话即生效。
#
# Codex（prompts + AGENTS.md 标准）:
#   内容同步到 $CODEX_HOME/agent-genesis/，
#   命令提示安装到 $CODEX_HOME/prompts/ag-*.md（斜杠命令），
#   并在 $CODEX_HOME/AGENTS.md 写入托管引导块。
#
# 用法:
#   bash install.sh                    # 自动检测并安装到所有可用平台
#   bash install.sh --claude           # 仅 Claude Code
#   bash install.sh --codex            # 仅 Codex
#   bash install.sh --uninstall        # 从所有平台卸载
#   bash install.sh --dry-run          # 预览，不执行
#   bash install.sh --scope project    # Claude Code 安装范围 (user|project|local)
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
PLUGIN_NAME="agent-genesis"
MARKETPLACE_NAME="agent-genesis"
SCOPE="user"

DO_CLAUDE=0
DO_CODEX=0
MODE="install"   # install | uninstall | dry-run

# ---- Parse args ----
for arg in "$@"; do
  case "$arg" in
    --claude)    DO_CLAUDE=1 ;;
    --codex)     DO_CODEX=1 ;;
    --all)       DO_CLAUDE=1; DO_CODEX=1 ;;
    --uninstall) MODE="uninstall" ;;
    --dry-run)   MODE="dry-run" ;;
    --scope=*)   SCOPE="${arg#--scope=}" ;;
    --help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg（--help 查看用法）"; exit 1 ;;
  esac
done

# 默认：自动检测两个平台
if [ "$DO_CLAUDE" -eq 0 ] && [ "$DO_CODEX" -eq 0 ]; then
  command -v claude >/dev/null 2>&1 && DO_CLAUDE=1
  { command -v codex >/dev/null 2>&1 || [ -d "$CODEX_HOME" ]; } && DO_CODEX=1
  # 都检测不到时默认尝试 Claude Code
  [ "$DO_CLAUDE" -eq 0 ] && [ "$DO_CODEX" -eq 0 ] && DO_CLAUDE=1
fi

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[AG]${NC} $*"; }
warn() { echo -e "${YELLOW}[AG]${NC} $*"; }
err()  { echo -e "${RED}[AG]${NC} $*"; }
run()  { if [ "$MODE" = "dry-run" ]; then echo "  [dry-run] $*"; else eval "$@"; fi; }

echo ""
echo "=============================================="
echo " AgentGenesis v0.17.5 — Installer"
echo " Mode: ${MODE}   Scope: ${SCOPE}"
echo " Repo: ${REPO_ROOT}"
echo " Platforms: claude=${DO_CLAUDE} codex=${DO_CODEX}"
echo "=============================================="
echo ""

# ============================================================
# Claude Code — 官方插件机制
# ============================================================
claude_install() {
  log "[Claude Code] 校验插件清单…"
  [ -f "$REPO_ROOT/.claude-plugin/plugin.json" ]      || { err "缺 .claude-plugin/plugin.json"; return 1; }
  [ -f "$REPO_ROOT/.claude-plugin/marketplace.json" ] || { err "缺 .claude-plugin/marketplace.json"; return 1; }

  if ! command -v claude >/dev/null 2>&1; then
    warn "未找到 claude CLI，请手动在 Claude Code 会话中执行："
    echo "    /plugin marketplace add $REPO_ROOT"
    echo "    /plugin install ${PLUGIN_NAME}@${MARKETPLACE_NAME}"
    return 0
  fi

  run "claude plugin validate \"$REPO_ROOT\"" || warn "validate 未通过或有警告，继续安装"

  log "[Claude Code] 注册本地 marketplace（原地加载，源码改动即生效）…"
  run "claude plugin marketplace add \"$REPO_ROOT\"" || warn "marketplace 可能已注册，继续"

  log "[Claude Code] 安装插件 (scope=$SCOPE)…"
  run "claude plugin install ${PLUGIN_NAME}@${MARKETPLACE_NAME} --scope $SCOPE"

  log "[Claude Code] 完成。验证: 重启会话后运行 /plugin 查看 ${PLUGIN_NAME}"
}

claude_uninstall() {
  if command -v claude >/dev/null 2>&1; then
    run "claude plugin uninstall ${PLUGIN_NAME}@${MARKETPLACE_NAME}" || warn "插件可能未安装"
    run "claude plugin marketplace remove ${MARKETPLACE_NAME}" || warn "marketplace 可能未注册"
  else
    warn "未找到 claude CLI，请手动执行: /plugin uninstall ${PLUGIN_NAME}@${MARKETPLACE_NAME}"
  fi
}

# ============================================================
# Codex — prompts + AGENTS.md 标准
# ============================================================
CODEX_AG_HOME="$CODEX_HOME/agent-genesis"
AGENTS_MD="$CODEX_HOME/AGENTS.md"
BLOCK_BEGIN="<!-- agent-genesis:begin -->"
BLOCK_END="<!-- agent-genesis:end -->"

codex_prompt_file() {
  # $1=命令名 $2=对应 workflow 文件 $3=一句话描述
  cat <<EOF
# /$1 — $3（AgentGenesis）

用户需求: \$ARGUMENTS

1. 设定 AGENTGENESIS_ROOT="$CODEX_AG_HOME"
2. Read \$AGENTGENESIS_ROOT/$2，按其中的步骤序列执行。
3. 平台适配约定：
   - 步骤标注 subagent/skill 时，若平台无对应调度能力，由主 Agent 顺序执行该步骤（先 Read 对应 agents/*.md 或 skills/*/SKILL.md 获取指令，再执行）。
   - Gate 引用 → 查 \$AGENTGENESIS_ROOT/phase/gates/gates.yaml → 执行对应 gate 脚本 → PASS/FAIL。
   - human_approval 节点 → 暂停等待用户确认。
4. 所有产物直接写入 output/，过程产物写入 .agent-genesis/work/。
EOF
}

codex_install() {
  log "[Codex] 同步插件内容到 $CODEX_AG_HOME …"
  run "mkdir -p \"$CODEX_AG_HOME\" \"$CODEX_HOME/prompts\""
  run "rsync -a --delete \
    --exclude='.git' --exclude='.claude' --exclude='docs' --exclude='design' \
    --exclude='work' --exclude='output' --exclude='.agent-genesis' \
    --exclude='node_modules' --exclude='__pycache__' --exclude='*.pyc' \
    \"$REPO_ROOT/\" \"$CODEX_AG_HOME/\""

  log "[Codex] 生成斜杠命令提示 (prompts/ag-*.md)…"
  [ "$MODE" = "dry-run" ] && echo "  [dry-run] write 2 prompt files"
  if [ "$MODE" != "dry-run" ]; then
    codex_prompt_file "harness-create"  "skills/harness-create/references/workflow.md"     "创建 Agent"      > "$CODEX_HOME/prompts/harness-create.md"
    codex_prompt_file "ag-skill-foundry" "skills/skill-foundry/references/workflow.md"      "创建/优化/诊断 Skill" > "$CODEX_HOME/prompts/ag-skill-foundry.md"
  fi

  log "[Codex] 写入 AGENTS.md 托管引导块…"
  if [ "$MODE" != "dry-run" ]; then
    mkdir -p "$CODEX_HOME"
    touch "$AGENTS_MD"
    # 幂等：先删旧块再追加
    sed -i "/$BLOCK_BEGIN/,/$BLOCK_END/d" "$AGENTS_MD"
    cat >> "$AGENTS_MD" <<EOF
$BLOCK_BEGIN
## AgentGenesis

AgentGenesis（Agent 工厂）已安装到 \`$CODEX_AG_HOME\`。
可用斜杠命令: /harness-create、/ag-skill-foundry。
工作流定义: \`$CODEX_AG_HOME/skills/harness-create/references/workflow.md\` 与
\`$CODEX_AG_HOME/skills/skill-foundry/references/workflow.md\`，产物写入 output/。
$BLOCK_END
EOF
  else
    echo "  [dry-run] append managed block to $AGENTS_MD"
  fi

  log "[Codex] 完成。验证: codex 会话中输入 /harness-create"
}

codex_uninstall() {
  log "[Codex] 移除 $CODEX_AG_HOME 与 prompts…"
  run "rm -rf \"$CODEX_AG_HOME\""
  run "rm -f \"$CODEX_HOME/prompts/harness-create.md\" \"$CODEX_HOME/prompts/ag-skill-foundry.md\""
  if [ -f "$AGENTS_MD" ] && [ "$MODE" != "dry-run" ]; then
    sed -i "/$BLOCK_BEGIN/,/$BLOCK_END/d" "$AGENTS_MD"
    log "[Codex] AGENTS.md 托管块已移除"
  fi
}

# ============================================================
# Main
# ============================================================
case "$MODE" in
  install|dry-run)
    [ "$DO_CLAUDE" -eq 1 ] && claude_install
    [ "$DO_CODEX" -eq 1 ] && codex_install
    ;;
  uninstall)
    [ "$DO_CLAUDE" -eq 1 ] && claude_uninstall
    [ "$DO_CODEX" -eq 1 ] && codex_uninstall
    ;;
esac

echo ""
echo "=============================================="
echo " Done (${MODE})"
echo "=============================================="
[ "$DO_CLAUDE" -eq 1 ] && echo " Claude Code: claude plugin install ${PLUGIN_NAME}@${MARKETPLACE_NAME} --scope ${SCOPE}"
[ "$DO_CODEX" -eq 1 ] && echo " Codex:       $CODEX_HOME/prompts/harness-create.md → /harness-create"
echo ""
