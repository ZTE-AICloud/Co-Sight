#!/usr/bin/env bash
# 把 skill-optimizer 安装到多个 runtime（Claude Code / Cosight / Codex / DSH）。
#
# 用法:
#   ./scripts/install.sh --from PKG.tar.gz          # 从 pack.sh 的制品装（分发主路径）
#   ./scripts/install.sh                            # 当前源码 → Claude Code（默认，向后兼容）
#   ./scripts/install.sh --runtime claude           # 仅 Claude Code（默认）
#   ./scripts/install.sh --runtime cosight          # 仅 Cosight：marketplace 注册 + .cosight 快照
#   ./scripts/install.sh --runtime codex            # 仅 Codex：market 即本仓库，只 add（不复制运行时）
#   ./scripts/install.sh --runtime dsh              # 仅 DSH：委托仓库根 install-dsh.sh 装成 dsh 插件
#   ./scripts/install.sh --runtime all              # 自动探测已装 CLI，分别安装
#   ./scripts/install.sh --dev                      # 开发机：marketplace 直指本仓库
#   ./scripts/install.sh --scope project            # 装到项目 scope（默认 user，仅 claude）
#   ./scripts/install.sh --no-pip                   # 跳过 python 依赖安装
#   DEST=/tmp/cache ./scripts/install.sh            # 离线 cp 到指定根（CI/测试场景，仅 claude）
#
# 四个 runtime 的安装语义：
#   claude  Claude Code 官方插件机制（/plugin marketplace add + /plugin install）。交互式斜杠命令。
#   cosight Cosight 原生宿主（~/.cosight/plugins/）。marketplace 注册 + 从顶层生成 .cosight/
#           组件快照 + .cosight-plugin/ manifest；子 Agent 经 `cosight -p` 驱动。
#   codex   market 即本仓库（仓库模式下）或 tarball 持久目录；作为 codex 插件安装
#           （.codex-plugin/skills/skill_*.md 注入 Available skills）+ $CODEX_HOME/prompts/skill_*.md
#           说明 + $CODEX_HOME/AGENTS.md 托管引导块。内容=调用 orchestrator.py。
#   dsh     委托仓库根 install-dsh.sh，把 skill-optimizer 装成一个 dsh 插件
#           （cosight-plugin-compat bundle，`dsh plugin --profile <p> add`）。
#           dsh 一切皆为插件：skills→dsh skills、commands/agents→dsh 原生表面挂载，
#           无需 CC 主 Agent，也无需快照+无头命令。
#
# 每个 runtime 的运行时组件都是同一套 RUNTIME_ITEMS（scripts/ 含 orchestrator.py 等无头入口）。
# codex/dsh 下无需 Claude Code 的插件打包/注册，仅需脚本可被 `python3 scripts/orchestrator.py` 运行。
#
# 安装后需重启 Claude Code 会话，命令才会出现在面板里。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

FROM_TARBALL=""
SCOPE="user"
DEV_MODE=""
CUSTOM_DEST="${DEST:-}"
DO_PIP="1"
RUNTIME="claude"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from)          FROM_TARBALL="$2"; shift 2 ;;
        --dev)           DEV_MODE="1"; shift ;;
        --scope)         SCOPE="$2"; shift 2 ;;
        --scope=*)       SCOPE="${1#--scope=}"; shift ;;
        --no-pip)        DO_PIP=""; shift ;;
        --runtime)       RUNTIME="$2"; shift 2 ;;
        --runtime=*)     RUNTIME="${1#--runtime=}"; shift ;;
        -h|--help)       sed -n '2,36p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *)               echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

case "$RUNTIME" in
    claude|cosight|codex|dsh|all) : ;;
    *) echo "--runtime 只接受 {claude,cosight,codex,dsh,all}，收到 '$RUNTIME'" >&2; exit 2 ;;
esac

if [[ -n "$DEV_MODE" && -n "$FROM_TARBALL" ]]; then
    echo "--dev 与 --from 互斥：--dev 指向本仓库，--from 装制品" >&2
    exit 2
fi


# ============================================================================
# 辅助（必须先于主流程定义）
# ============================================================================

# 运行时需要的组件目录/文件（tests / scripts 脚本 / dist 不进源目录）
RUNTIME_ITEMS=(.claude-plugin skills agents commands scripts rules references \
               framework_configs config docs README.md COSIGHT.md)

# 每个 runtime 的代码同步目标根（冗余给 RUNTIME 循环覆盖检测）
COSIGHT_HOME="${COSIGHT_HOME:-$HOME/.cosight}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"

cp_runtime_files() {
    local src="$1"
    local target="$2"
    for item in "${RUNTIME_ITEMS[@]}"; do
        [[ -e "$src/$item" ]] || continue
        rm -rf "$target/$item"
        cp -r "$src/$item" "$target/$item"
    done
    find "$target" -type d -name '__pycache__'    -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type d -name '.ruff_cache'    -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type d -name '.pytest_cache'  -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type d -name 'dist'           -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type f -name '*.py[co]' -delete 2>/dev/null || true
}

pip_deps() {
    # pip_deps <sync_root> —— 安装该 runtime 快照的 Python 依赖（失败只警告）
    local root="$1"
    if [[ -z "$DO_PIP" || ! -f "$root/scripts/requirements.txt" ]]; then
        return 0
    fi
    echo "安装 Python 依赖: $(basename "$root/scripts/requirements.txt")"
    if command -v python3 >/dev/null 2>&1; then
        python3 -m pip install -r "$root/scripts/requirements.txt" >/dev/null 2>&1 \
            && echo "  pip 依赖就绪" \
            || echo "  ⚠️ pip 安装失败（可稍后手动: pip install -r ./scripts/requirements.txt）"
    fi
}

json_field() {
    # json_field <file> <python 表达式，d 为已解析的 dict>
    python3 -c 'import json,sys
d = json.load(open(sys.argv[1]))
print(eval(sys.argv[2], {"d": d}))' "$1" "$2"
}

registered_marketplace_path() {
    python3 -c 'import json,os,sys
p = os.path.expanduser("~/.claude/plugins/known_marketplaces.json")
if not os.path.exists(p): sys.exit(0)
e = json.load(open(p)).get(sys.argv[1])
print(e.get("installLocation", "") if e else "")' "$1" 2>/dev/null || true
}

installed_plugin_version() {
    python3 -c 'import json,os,sys
p = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
if not os.path.exists(p): sys.exit(0)
e = json.load(open(p)).get("plugins", {}).get(sys.argv[1])
print(e[0].get("version", "") if e else "")' "$1" 2>/dev/null || true
}

content_hash() {
    # content_hash <root_dir>
    # 遍历运行时整树算 sha256（跳过缓存/日志）——同版本代码变更能检测到。
    python3 -c '
import hashlib, sys, os
root = sys.argv[1]
h = hashlib.sha256()
skip_dirs = {"__pycache__", ".git", "dist", ".pytest_cache", ".ruff_cache"}
files = []
for dp, ds, fn in os.walk(root):
    ds[:] = [d for d in ds if d not in skip_dirs]
    for name in sorted(fn):
        if name.endswith((".pyc", ".pyo")): continue
        p = os.path.join(dp, name)
        rel = os.path.relpath(p, root)
        files.append(rel)
for rel in sorted(files):
    p = os.path.join(root, rel)
    h.update(rel.encode() + b"\0")
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
print(h.hexdigest()[:16])
' "$1"
}

cache_root() {
    # cache_root <plugin_name> <marketplace_name> → cache dir path（可能有，也可能没有）
    python3 -c '
import json, os, sys
p = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
if not os.path.exists(p):
    sys.exit(0)
e = json.load(open(p)).get("plugins", {}).get(f"{sys.argv[1]}@{sys.argv[2]}")
if e:
    print(e[0].get("installPath", ""))
' "$1" "$2" 2>/dev/null
}


# ============================================================================
# 准备源：tarball 解包到 stage，否则直接用 repo
# ============================================================================

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if [[ -n "$FROM_TARBALL" ]]; then
    [[ -f "$FROM_TARBALL" ]] || { echo "找不到 $FROM_TARBALL" >&2; exit 1; }
    tar -xzf "$FROM_TARBALL" -C "$STAGE"
    SRC="$STAGE"
else
    SRC="$SCRIPT_DIR"
fi

# manifest 必须从 SRC 读 —— tarball 模式下脚本所在目录没有 .claude-plugin/
MANIFEST="$SRC/.claude-plugin/plugin.json"
MARKETPLACE="$SRC/.claude-plugin/marketplace.json"
[[ -f "$MANIFEST" ]]    || { echo "制品缺少 .claude-plugin/plugin.json"    >&2; exit 1; }
[[ -f "$MARKETPLACE" ]] || { echo "制品缺少 .claude-plugin/marketplace.json" >&2; exit 1; }

PLUGIN_NAME="$(json_field "$MANIFEST" 'd["name"]')"
MARKETPLACE_NAME="$(json_field "$MARKETPLACE" 'd["name"]')"
VERSION="$(json_field "$MANIFEST" 'd["version"][1:] if d["version"].startswith("v") else d["version"]')"


# ============================================================================
# Claude Code 安装（默认，向后兼容）
# ============================================================================

install_claude() {
    # DEST 模式：只 cp 不注册（CI / 测试；claude 特有）
    if [[ -n "$CUSTOM_DEST" ]]; then
        TARGET="$CUSTOM_DEST/$VERSION"
        mkdir -p "$TARGET"
        cp_runtime_files "$SRC" "$TARGET"
        echo "DEST 模式只 cp，未注册: $TARGET"
        echo "若要 Claude Code 索引到，调: claude plugin install ${PLUGIN_NAME}@${MARKETPLACE_NAME}"
        return 0
    fi

    local MARKETPLACE_HOME PREV_PATH INSTALL_ID PREV_VERSION
    local MARKETPLACE_HASH CACHE_PATH CACHE_HASH NEEDS_REINSTALL
    local ACTION_CMD ACTION_CMD2 SUCCESS

    if [[ -n "$DEV_MODE" ]]; then
        MARKETPLACE_HOME="$SCRIPT_DIR"
    else
        MARKETPLACE_HOME="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME"
    fi

    # 已注册到别的路径时先摘掉，否则 add 不改指向。
    PREV_PATH="$(registered_marketplace_path "$MARKETPLACE_NAME")"
    if [[ -n "$PREV_PATH" && "$PREV_PATH" != "$MARKETPLACE_HOME" ]]; then
        echo "marketplace '$MARKETPLACE_NAME' 原指向 $PREV_PATH，重新指向 $MARKETPLACE_HOME"
        claude plugin marketplace remove "$MARKETPLACE_NAME" >/dev/null 2>&1 || true
    fi

    if [[ -n "$DEV_MODE" ]]; then
        echo "dev 模式，marketplace 直指本仓库: $MARKETPLACE_HOME"
    else
        mkdir -p "$MARKETPLACE_HOME"
        cp_runtime_files "$SRC" "$MARKETPLACE_HOME"
        echo "marketplace 源已就位: $MARKETPLACE_HOME"
    fi

    claude plugin marketplace add "$MARKETPLACE_HOME" || {
        echo "marketplace 注册失败: $MARKETPLACE_HOME" >&2
        return 1
    }

    INSTALL_ID="${PLUGIN_NAME}@${MARKETPLACE_NAME}"
    PREV_VERSION="$(installed_plugin_version "$INSTALL_ID")"

    MARKETPLACE_HASH="$(content_hash "$MARKETPLACE_HOME")"
    CACHE_PATH="$(cache_root "$PLUGIN_NAME" "$MARKETPLACE_NAME")"
    CACHE_HASH=""
    if [[ -n "$CACHE_PATH" && -d "$CACHE_PATH" ]]; then
        CACHE_HASH="$(content_hash "$CACHE_PATH")"
    fi
    NEEDS_REINSTALL=""
    if [[ -n "$PREV_VERSION" && -n "$MARKETPLACE_HASH" && -n "$CACHE_HASH" && "$MARKETPLACE_HASH" != "$CACHE_HASH" ]]; then
        NEEDS_REINSTALL="1"
        echo "已装 $PREV_VERSION，但 cache 与 marketplace 内容不一致："
        echo "  marketplace hash: $MARKETPLACE_HASH"
        echo "  cache hash:       $CACHE_HASH"
        echo "→ 走 uninstall + install 强制刷新 cache（update 不会复制内容）"
    fi

    ACTION_CMD=()
    ACTION_CMD2=()
    if [[ -n "$PREV_VERSION" ]]; then
        if [[ "$NEEDS_REINSTALL" == "1" ]]; then
            echo "已装 $PREV_VERSION，内容有变化"
            ACTION_CMD=(claude plugin uninstall "$INSTALL_ID")
            ACTION_CMD2=(claude plugin install "$INSTALL_ID" --scope "$SCOPE")
        else
            echo "已装 $PREV_VERSION，走 update 到 $VERSION"
            ACTION_CMD=(claude plugin update "$INSTALL_ID")
            ACTION_CMD2=()
        fi
    else
        ACTION_CMD=(claude plugin install "$INSTALL_ID" --scope "$SCOPE")
        ACTION_CMD2=()
    fi

    if [[ -n "${ACTION_CMD2[*]}" ]]; then
        if "${ACTION_CMD[@]}" && "${ACTION_CMD2[@]}"; then
            SUCCESS=1
        else
            SUCCESS=0
        fi
    else
        if "${ACTION_CMD[@]}"; then
            SUCCESS=1
        else
            SUCCESS=0
        fi
    fi

    if [[ "$SUCCESS" == "1" ]]; then
        pip_deps "$(cache_root "$PLUGIN_NAME" "$MARKETPLACE_NAME")" || true
        echo
        echo "Claude Code 安装完成:"
        echo "  scope:       $SCOPE"
        echo "  marketplace: $MARKETPLACE_HOME"
        echo "  version:     $VERSION"
        echo
        echo "在 Claude Code 会话里执行 /reload-plugins 刷新插件，"
        echo "即可使用 /skill_optimize /skill_evolve /skill_create。若组件未出现，重启会话。"
    else
        echo
        echo "失败。手动排查路径："
        echo "  claude plugin marketplace list       # 看 $MARKETPLACE_NAME 是否在已知源里"
        echo "  claude plugin list                   # 看 $INSTALL_ID 是否已注册"
        echo "  claude plugin details $INSTALL_ID    # 看组件是否被加载"
        return 1
    fi
}


# ============================================================================
# Cosight 安装：~/.cosight/plugins/marketplaces/ + .cosight 快照 + 注册表
#
# Cosight（@zte/cosight-cli）是独立宿主，在 ~/.cosight/plugins/ 下有自己的
# marketplace / installed / known_marketplaces / settings(enabledPlugins) 注册机制
# （与 Claude Code 的 registry 相互独立）。组件从顶层生成 .cosight/ 快照：
#   .cosight/agents|commands|rules|skills ← 顶层 agents|commands|rules|skills
# 并生成 .cosight-plugin/ manifest（路径指向 ./.cosight/…）。
# 子 Agent 由 agent_runner 的 CosightRunner 经 `cosight -p` 驱动。
# ============================================================================

# 用 python3 原子更新一个 Cosight 注册 json 文件的字段。
# json_assign <file> <python 赋值语句，用 d(已解析 dict) 与 val(值)>
# 例：json_assign "$KNOWN" "d.setdefault('$MKT', {})['installLocation']" "$INSTALL_LOC"
json_assign() {
    local file="$1" stmt="$2" val="$3"
    mkdir -p "$(dirname "$file")"
    if [[ ! -f "$file" ]]; then echo '{}' > "$file"; fi
    python3 -c '
import json, sys
p, stmt, val = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(p))
exec(stmt, {"d": d, "val": val})
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
' "$file" "$stmt" "$val"
}

install_cosight() {
    local MKT="$MARKETPLACE_NAME"      # skillx
    local PLUG="$PLUGIN_NAME"          # skill-optimizer
    local MARKETPLACE_HOME="$COSIGHT_HOME/plugins/marketplaces/$MKT"
    local KEY="${PLUG}@${MKT}"
    local INSTALL_LOC="$MARKETPLACE_HOME"
    local KM=known_marketplaces.json
    local INSTALLED="$COSIGHT_HOME/plugins/installed_plugins.json"
    local KNOWN="$COSIGHT_HOME/plugins/$KM"
    local SETTINGS="$COSIGHT_HOME/settings.json"

    echo "[Cosight] 同步运行时组件到 $MARKETPLACE_HOME …"
    mkdir -p "$MARKETPLACE_HOME"
    cp_runtime_files "$SRC" "$MARKETPLACE_HOME"

    echo "[Cosight] 从顶层生成 .cosight/ 组件快照 …"
    mkdir -p "$MARKETPLACE_HOME/.cosight"
    for c in agents commands rules skills; do
        if [[ -d "$MARKETPLACE_HOME/$c" ]]; then
            rm -rf "$MARKETPLACE_HOME/.cosight/$c"
            cp -r "$MARKETPLACE_HOME/$c" "$MARKETPLACE_HOME/.cosight/$c"
        fi
    done

    echo "[Cosight] 生成 .cosight-plugin/ manifest …"
    mkdir -p "$MARKETPLACE_HOME/.cosight-plugin"
    python3 -c '
import json, sys
root, mkt, plug = sys.argv[1], sys.argv[2], sys.argv[3]
# 复用 .claude-plugin 的 marketplace.json 清单，改写为 cosight 兼容形态。
# cosight 校验要求（参照 harness 的合法 manifest）：
#   1. 根节点不允许同时含 "$schema" / "description"（Unrecognized keys）；
#   2. 插件 source 必须以 "./" 开头；
#   3. 描述放 metadata.description（而非根 description）。
mp = json.load(open(f"{root}/.claude-plugin/marketplace.json"))
mp.pop("$schema", None)
desc = mp.pop("description", None)
if desc:
    mp.setdefault("metadata", {})["description"] = desc
for pl in mp["plugins"]:
    pl["source"] = "./"
    if pl["name"] == plug:
        pl["strict"] = False
json.dump(mp, open(f"{root}/.cosight-plugin/marketplace.json", "w"), indent=2, ensure_ascii=False)
' "$MARKETPLACE_HOME" "$MKT" "$PLUG"

    echo "[Cosight] 注册 marketplace / 插件 / 启用 …"
    # marketplace 源条目（Cosight 的 known_marketplaces 结构：key → {source,installLocation,lastUpdated}）
    # 注意：必须写 lastUpdated，否则 `cosight plugin marketplace remove` 会因缺该字段判 "corrupted" 失败。
    json_assign "$KNOWN" "d.setdefault('$MKT', {})['source'] = {'source': 'directory', 'path': '$INSTALL_LOC'}" ""
    json_assign "$KNOWN" "d.setdefault('$MKT', {})['installLocation'] = '$INSTALL_LOC'" ""
    json_assign "$KNOWN" "d.setdefault('$MKT', {})['lastUpdated'] = val" "$(date -u +%Y-%m-%dT%H:%M:%S.000000+00:00)"

    # 已装插件条目 installed_plugins[KEY] = [{scope,installPath,version,...}]
    python3 -c '
import json, os, sys, datetime
p = os.path.join(sys.argv[1], "plugins", "installed_plugins.json")
key = sys.argv[2]; loc = sys.argv[3]; ver = sys.argv[4]
d = json.load(open(p)) if os.path.exists(p) else {"version": 2, "plugins": {}}
d.setdefault("plugins", {})
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
d["plugins"][key] = [{"scope": "user", "installPath": loc, "version": ver,
                      "installedAt": now, "lastUpdated": now}]
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
' "$COSIGHT_HOME" "$KEY" "$INSTALL_LOC" "$VERSION"

    # settings.json enabledPlugins[key] = true
    json_assign "$SETTINGS" "d.setdefault('enabledPlugins', {})['$KEY'] = True" ""

    pip_deps "$MARKETPLACE_HOME"
    echo "[Cosight] 完成。验证:"
    echo "  ls $MARKETPLACE_HOME/.cosight/agents/            # .cosight 快照"
    echo "  cat $COSIGHT_HOME/plugins/known_marketplaces.json  # 含 $MKT"
    echo "  子 Agent 经 cosight -p（SKILLX_AGENT_CLI=cosight）驱动"
}


# ============================================================================
# 无头入口命令模板（codex / dsh 共用）
# /skill_* → orchestrator.py 的语义模式映射：
#   /skill_optimize → --mode static（内容优化）或 --mode refactor（结构重构）
#   /skill_create   → --mode create（Phase A-E 无头流水线）
#   /skill_evolve   → --mode eval（评测驱动迭代，需 --pipeline-eval-cmd）
# 注意 orchestrator 的真实模式不含 "optimize"/"evolve"，见 commands/skill_*.md 的映射。
# ============================================================================

# 给单个 skill 命令生成无头入口 prompt（写一个文件）
# $1=输出文件  $2=命令名  $3=SKILLX_HOME(同步根)  $4=模式行  $5=必填说明
write_headless_prompt() {
    local out="$1" name="$2" root="$3" mode_doc="$4" req_doc="$5"
    cat > "$out" <<EOF
# /${name} —— Cosight Skill 优化器（skill-optimizer，无头入口）

用户需求: \$ARGUMENTS

本命令是无头入口，**不需要 CC 主 Agent**。把用户需求翻译为 orchestrator.py
参数后，用 Bash 执行：

    ORCH="$root/scripts/orchestrator.py"
    python3 "\$ORCH"

$mode_doc
$req_doc

执行时把 orchestrator 的 stdout 结果如实汇报给用户（含分数/缺口/产物路径）。
若 orchestrator 退出码非 0，说明失败原因，不要掩盖。
EOF
}

headless_optimize_doc() {
    cat <<'EOF'
模式选择（把 "optimize"/"refactor" 语义翻译为真实 --mode）:
  - 用户要内容优化/评分改进  → 追加 `--mode static`
  - 用户要结构重构/拆分合并  → 追加 `--mode refactor`
EOF
}

headless_optimize_req() {
    cat <<'EOF'
必填参数（optimize/static）:
  --skill-path <SKILL.md> 或 --agent-path <Agent 根目录>（互斥，至少一个）
refactor 必填: --skill-path <SKILL.md> 和 --workspace <工作区目录>
可选: --expert-guidance "…"  --max-files N  --per-skill-rounds N  --no-revert  --score-mode {llm_direct|subagent}
若 用户给出绝对或相对路径，直接用；未给则让用户补充必要路径。
EOF
}

headless_create_req() {
    cat <<'EOF'
--mode create 必填:
  --create-skill-name <kebab-case 名>
  --create-requirement @文件.md 或 自然语言
可选: --create-output-dir <工作区>（默认 ./output/skills_create） --create-expert-guidance "…"
EOF
}

headless_evolve_req() {
    cat <<'EOF'
--mode eval 参数（评测驱动迭代）:
  常用: --pipeline-base-dir <目录> 与 --pipeline-eval-cmd <评测命令>
        （或 --pipeline-eval-sh <纯 shell 评测命令>）
        --max-rounds N  --candidates-per-round N  --eval-runs-per-candidate N
        --skill-paths P1,P2,P3  --consume-lib-path <目录>
EOF
}


# ============================================================================
# Codex 安装：快照 + 作为 codex 插件注册（skills/）+ prompts + AGENTS.md 托管块
#
# 注意（codex 0.16x 行为变化）：
#   codex CLI 0.16x 不再自动把 ~/.codex/prompts/*.md 注册为斜杠命令；命令/技能改由
#   插件机制提供（.codex-plugin + skills/，经 `codex plugin marketplace add` + `codex plugin add`
#   注册）。因此这里把 skill-optimizer 装成一个 codex 插件，把每个命令做成一个 SKILL.md，
#   注入 agent 会话的 "## Skills / Available skills"（等价于 Claude Code 的 /skill_* 斜杠入口）。
#   同时仍写入 prompts/ 与 AGENTS.md（对支持旧式自定义 prompt 的版本无副作用）。
# ============================================================================

# 给单个 codex 命令生成一个 SKILL.md（frontmatter + 无头执行指令）
# $1=输出文件  $2=skill 名  $3=SKILLX_HOME(同步根)  $4=模式行  $5=参数说明
write_codex_skill() {
    local out="$1" name="$2" root="$3" mode_doc="$4" req_doc="$5"
    cat > "$out" <<EOF
---
name: ${name}
description: "Cosight Skill 优化器（skill-optimizer）的 ${name} 入口：用户要求优化/创建/评测某个 Skill 时使用。"
---

# /${name} —— skill-optimizer 无头入口

用户给定了要优化的 Skill 及路径/意图。把用户需求翻译为 orchestrator.py 的参数后，
用 Bash 执行：

    ORCH="$root/scripts/orchestrator.py"
    python3 "\$ORCH"

$mode_doc
$req_doc

执行时把 orchestrator 的 stdout 结果如实汇报给用户（含分数/缺口/产物路径）。
若 orchestrator 退出码非 0，说明失败原因，不要掩盖。
EOF
}

# 复用在 prompts / dsh 里已有的模式行与必填说明（避免重复维护）
codex_optimize_doc() { headless_optimize_doc; }
codex_optimize_req() { headless_optimize_req; }

install_codex() {
    local MARKETPLACE_HOME AGENTS_MD BLOCK_BEGIN BLOCK_END INSTALL_ID
    BLOCK_BEGIN="<!-- skillx-optimizer:begin -->"
    BLOCK_END="<!-- skillx-optimizer:end -->"
    AGENTS_MD="$CODEX_HOME/AGENTS.md"
    INSTALL_ID="${PLUGIN_NAME}@${MARKETPLACE_NAME}"

    # codex 市场根：
    #   · 仓库/dev 模式 —— market 即本仓库，只 `codex plugin marketplace add`，不在 ~/.codex 复制运行时
    #   · tarball 制品  —— STAGE 是临时目录会被清，需解包到持久目录充当 market（单点落地，非去重复制）
    if [[ -n "$FROM_TARBALL" ]]; then
        MARKETPLACE_HOME="$CODEX_HOME/skillx-plugin"
        echo "[Codex] tarball 制品：解包市场到 $MARKETPLACE_HOME"
        rm -rf "$MARKETPLACE_HOME"; mkdir -p "$MARKETPLACE_HOME"
        cp_runtime_files "$SRC" "$MARKETPLACE_HOME"
        pip_deps "$MARKETPLACE_HOME"
    else
        MARKETPLACE_HOME="$SCRIPT_DIR"
        echo "[Codex] 仓库模式：marketplace 直指本仓库 $MARKETPLACE_HOME（只 add，不复制运行时）"
    fi

    # 生成 codex 插件 manifest + skills，令市场根自足。
    # 仓库模式下写入仓库的 .codex-plugin/（已在 .gitignore 忽略），仓库自身即成为可用的 codex 市场与插件。
    echo "[Codex] 生成 codex 插件 manifest + skills/ …"
    mkdir -p "$MARKETPLACE_HOME/.codex-plugin/skills/skill_optimize" \
             "$MARKETPLACE_HOME/.codex-plugin/skills/skill_evolve" \
             "$MARKETPLACE_HOME/.codex-plugin/skills/skill_create"

    # codex 从插件根读 .codex-plugin/plugin.json；skills 目录注入会话 Available skills
    # （marketplace 清单复用仓库已有的 .claude-plugin/marketplace.json，source="."，插件根=市场根）
    cat > "$MARKETPLACE_HOME/.codex-plugin/plugin.json" <<EOF
{
  "description": "Skill 评测-优化循环编排器（skillx 移植版）",
  "name": "$PLUGIN_NAME",
  "version": "$VERSION",
  "interface": {
    "displayName": "Skill Optimizer",
    "category": "Developer Tools"
  },
  "skills": "./.codex-plugin/skills/"
}
EOF

    # orchestrator 路径 = 市场根（仓库模式即本仓库，orchestrator 就地运行，无需快照）
    write_codex_skill "$MARKETPLACE_HOME/.codex-plugin/skills/skill_optimize/SKILL.md" "skill_optimize" "$MARKETPLACE_HOME" \
        "$(headless_optimize_doc)" "$(headless_optimize_req)"
    write_codex_skill "$MARKETPLACE_HOME/.codex-plugin/skills/skill_evolve/SKILL.md" "skill_evolve" "$MARKETPLACE_HOME" \
        "" "$(headless_evolve_req)"
    write_codex_skill "$MARKETPLACE_HOME/.codex-plugin/skills/skill_create/SKILL.md" "skill_create" "$MARKETPLACE_HOME" \
        "" "$(headless_create_req)"

    # --- 只 add：注册 marketplace + 安装/启用插件（不在 ~/.codex 复制） ---
    if command -v codex >/dev/null 2>&1; then
        echo "[Codex] 注册 marketplace '$MARKETPLACE_NAME' → $MARKETPLACE_HOME …"
        codex plugin marketplace add "$MARKETPLACE_HOME" >/dev/null 2>&1 \
            && echo "  marketplace 已注册" \
            || echo "  (已存在或失败，可手动: codex plugin marketplace add $MARKETPLACE_HOME)"
        echo "[Codex] 安装并启用插件 $INSTALL_ID …"
        codex plugin remove "$INSTALL_ID" >/dev/null 2>&1 || true
        codex plugin add "$INSTALL_ID" >/dev/null 2>&1 \
            && echo "  插件已安装并启用" \
            || echo "  ⚠️ codex plugin add 失败，可手动: codex plugin add $INSTALL_ID"
    else
        echo "[Codex] 未检测到 codex CLI，跳过插件注册（市场已就位: $MARKETPLACE_HOME）"
    fi

    # --- 仍写入 prompts/（0.16x 不注册为命令，仅作旧式说明备查）+ AGENTS.md 托管引导块 ---
    # 路径统一指向市场根（仓库模式下即本仓库），不再指向 ~/.codex/skillx-optimizer 快照
    mkdir -p "$CODEX_HOME/prompts"
    write_headless_prompt "$CODEX_HOME/prompts/skill_optimize.md" "skill_optimize" "$MARKETPLACE_HOME" \
        "$(headless_optimize_doc)" "$(headless_optimize_req)"
    write_headless_prompt "$CODEX_HOME/prompts/skill_create.md" "skill_create" "$MARKETPLACE_HOME" \
        "" "$(headless_create_req)"
    write_headless_prompt "$CODEX_HOME/prompts/skill_evolve.md" "skill_evolve" "$MARKETPLACE_HOME" \
        "" "$(headless_evolve_req)"

    mkdir -p "$CODEX_HOME"
    touch "$AGENTS_MD"
    sed -i "/$BLOCK_BEGIN/,/$BLOCK_END/d" "$AGENTS_MD"
    cat >> "$AGENTS_MD" <<EOF
$BLOCK_BEGIN
## Skill Optimizer (codex 插件；market 即本仓库)

已把 codex marketplace '$MARKETPLACE_NAME' 指到工作区仓库 $MARKETPLACE_HOME。
它将注入新会话的 \`## Skills / Available skills\`（全名带插件前缀）：
  - skill-optimizer:skill_optimize —— 内容优化(--mode static) / 结构重构(--mode refactor)
  - skill-optimizer:skill_evolve   —— 评测驱动迭代(--mode eval)
  - skill-optimizer:skill_create   —— 0→1 创建 Skill(--mode create)
调用方式：在会话里点名技能全名（例如「使用 skill-optimizer:skill_create」）并提供入参；
codex 没有斜杠命令，skilly 由模型依据描述自动匹配/你点名触发。
运行核心: \`python3 $MARKETPLACE_HOME/scripts/orchestrator.py --mode …\`。
验证: \`codex plugin list\` 应显示 $INSTALL_ID installed, enabled；
      \`codex plugin marketplace list\` 看 $MARKETPLACE_NAME 指向 $MARKETPLACE_HOME。
$BLOCK_END
EOF

    [[ -z "$FROM_TARBALL" ]] && echo "  （市场即本仓库，未在 ~/.codex 复制运行时；.codex-plugin/ 生成物已 gitignore）"
    echo "[Codex] 完成。验证: codex plugin list 看 $INSTALL_ID 为 installed, enabled；"
    echo "        新会话里应出现 Available skills: skill_optimize / skill_evolve / skill_create"
}


# ============================================================================
# DSH 安装：委托仓库根 install-dsh.sh，把 skill-optimizer 装成真正的 dsh 插件
#
# dsh 一切皆为插件。skill-optimizer 不再以「快照 + dev/commands 无头命令」的方式
# 装进 $DSH_HOME/skillx-optimizer/，而是交给仓库根的统一安装器 install-dsh.sh：
# 它用 `dsh plugin --profile <p> add` 把 cosight-plugin-compat bundle 做成 profile
# 常驻插件层，skill-optimizer 的 skills/commands/agents 经 dsh 原生表面挂载
# （skills→dsh skills、commands→user-invocable skill、agents→Task shim）。
# ============================================================================

install_dsh() {
    # 仓库根统一安装器（cosight-plugin-compat + drive 的编排）。dsh 一切皆为插件，
    # skill-optimizer 作为 dsh 插件（cosight-plugin-compat bundle 的成员之一）经
    # `dsh plugin --profile <p> add` 装进 profile，常驻为 profile 插件层。
    local ROOT_INSTALLER="$SCRIPT_DIR/../install-dsh.sh"

    if [[ ! -f "$ROOT_INSTALLER" ]]; then
        echo "[DSH] 未找到仓库根统一安装器: $ROOT_INSTALLER" >&2
        echo "[DSH] 请从 cosight-harness 仓库根（skill-optimizer/ 的上一级）运行本脚本，" >&2
        echo "[DSH] 或用 --from 的 DSH 场景需先在此仓库构建 dsh-compat 自包含包。" >&2
        return 1
    fi

    echo "[DSH] 委托: bash $ROOT_INSTALLER (profile=${PROFILE:-web})"
    echo "[DSH]   把 skill-optimizer 作为 dsh 插件（cosight-plugin-compat bundle）安装，"
    echo "[DSH]   skills→dsh skills、commands/agents→dsh 原生表面挂载。"

    # 把本脚本已解析的 profile / 源码路径透传给仓库根安装器，避免重复探测 dsh。
    local DSH_ARGS=()
    [[ -n "${DSH_SOURCE_DIR:-}" ]] && DSH_ARGS+=(--dsh-source "$DSH_SOURCE_DIR")
    [[ -n "${PROFILE:-}" ]] && DSH_ARGS+=(--profile "$PROFILE")

    if ! bash "$ROOT_INSTALLER" "${DSH_ARGS[@]}"; then
        echo "[DSH] 仓库根安装器失败。可重试：cd <cosight-harness> && PROFILE=… bash install-dsh.sh" >&2
        return 1
    fi

    echo "[DSH] 完成。skill-optimizer 已作为 dsh 插件安装，重启 dsh 后生效："
    echo "  /skill_optimize /skill_create /skill_evolve  （命令类 skill → dsh 用户可调入口）"
    echo "  验证：dsh --profile ${PROFILE:-web} --dump-config  | grep -i skillx"
}


# ============================================================================
# 主流程：按 --runtime 分发
# ============================================================================

setup_colors() {
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
    # 非 tty 时禁用颜色
    [[ -t 1 ]] || { GREEN=''; YELLOW=''; }
}
setup_colors

echo "=============================================="
echo " skill-optimizer v${VERSION} — Installer"
echo " runtime: ${RUNTIME}   scope: ${SCOPE}"
echo " source:  ${SRC}"
echo "=============================================="
echo ""

case "$RUNTIME" in
    claude)
        install_claude || exit 1
        ;;
    cosight)
        install_cosight
        ;;
    codex)
        install_codex
        ;;
    dsh)
        install_dsh
        ;;
    all)
        # auto-detect installed CLIs; install each present one
        [[ -z "$CUSTOM_DEST" ]] || { echo "DEST 模式仅用于 claude runtime" >&2; exit 2; }
        if command -v claude >/dev/null 2>&1; then
            echo -e "${GREEN}[all]${NC} 检测到 claude → 安装 Claude Code…"
            install_claude || echo -e "${YELLOW}[all]${NC} Claude Code 安装未完成"
        else
            echo -e "${YELLOW}[all]${NC} 未检测到 claude CLI，跳过"
        fi
        if { command -v codex >/dev/null 2>&1 || [[ -d "$CODEX_HOME" ]]; }; then
            echo -e "${GREEN}[all]${NC} 检测到 codex → 安装 Codex…"
            install_codex
        else
            echo -e "${YELLOW}[all]${NC} 未检测到 codex CLI / $CODEX_HOME，跳过"
        fi
        if command -v cosight >/dev/null 2>&1 || [[ -d "$COSIGHT_HOME" ]]; then
            echo -e "${GREEN}[all]${NC} 检测到 cosight → 安装 Cosight…"
            install_cosight
        else
            echo -e "${YELLOW}[all]${NC} 未检测到 cosight CLI / $COSIGHT_HOME，跳过"
        fi
        if [[ -n "$DSH_HOME" ]]; then
            echo -e "${GREEN}[all]${NC} 检测到 DSH → 安装 DSH…"
            install_dsh
        fi
        ;;
esac

echo ""
echo "=============================================="
echo " Done (runtime=${RUNTIME})"
echo "=============================================="
case "$RUNTIME" in
    claude) echo " Claude Code: claude plugin install ${PLUGIN_NAME}@${MARKETPLACE_NAME} --scope ${SCOPE}（或重启会话）" ;;
    cosight) echo " Cosight:     $COSIGHT_HOME/plugins/marketplaces/$MARKETPLACE_NAME/ （.cosight/ 快照 + 注册就位）" ;;
    codex)  echo " Codex:       market 即本仓库（.$SCRIPT_DIR）/ tarball 取 $CODEX_HOME/skillx-plugin，插件+skills/ → Available skills" ;;
    dsh)    echo " DSH:         委托仓库根 install-dsh.sh → skill-optimizer 作为 dsh 插件（cosight-plugin-compat bundle）就位" ;;
    all)    echo " 各 runtime 见上方安装片段" ;;
esac
echo ""