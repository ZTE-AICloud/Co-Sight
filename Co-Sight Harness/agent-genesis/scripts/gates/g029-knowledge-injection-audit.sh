#!/usr/bin/env bash
# G029: 知识库注入审计（gate.knowledge.injection）
#
# 对象: Step 1b 注入的技能目录（claude-code: .claude/skills/rag-knowledge-search/；
#       dsh: dsh/skills/rag-knowledge-search/；both: 两处）与 injected-assets.yaml。
#       落点以 manifest.knowledge.relative_dirs 为准（旧清单回退 relative_dir），
#       逐项白名单校验。
# 目的: 预置资产不走 LLM 生成循环, 质量靠"注入内容 = 内置资产 + 工作流 id 一一对应"保证;
#       本 gate 用确定性检查证明该等价关系未被破坏。
#
# 协议:
#   argv: --manifest <injected-assets.yaml> --output-dir <产物目录> [--build-plan <build-plan>]
#   stdin JSON 兜底: {"manifest": ..., "output_dir": ..., "build_plan": ...}
# stdout: 合并 JSON {"gate_id":"gate.knowledge.injection","verdict":"PASS|FAIL","failures":[...]}
# 退出码: 0=PASS / 2=FAIL（含输入缺失, fail-closed）
#
# 检查项:
#   1. manifest status ∈ {injected, noop} 且 knowledge.injected=true
#   2. workflow_id 字面量合法, 且与分析结果一致（客户端 DEFAULT_WORKFLOW_ID 恰好赋值 1 次）
#   3. 端点固定: query_path=/api/co-knowledge/v1/agent/query; 客户端
#      DEFAULT_BASE_URL=http://localhost:4910（框架路由 / CO_KNOWLEDGE_BASE_URL 运行时可覆盖,
#      但默认值必须是本地固定端口）, 且请求带 conversation_id + Authorization
#   4. files[] 逐条存在、位于 relative_dirs 声明的某个技能目录内、无路径逃逸
#   5. 每个技能目录的 SKILL.md frontmatter 含 name: rag-knowledge-search + 非空 description
#   6. 无历史实现残留（旧服务发现/旧服务名）, 无 MCP 残留
#   7. 全部 .py 可 py_compile（编译产物写临时目录, 不污染产物）
#   8. 提供 build-plan 时: 每个 manifest 文件都有且仅有 generation: pre_staged 条目
set -uo pipefail

MANIFEST=""
OUTPUT_DIR=""
BUILD_PLAN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)   MANIFEST="${2:-}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --build-plan) BUILD_PLAN="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$MANIFEST" || -z "$OUTPUT_DIR" ]]; then
  INPUT=$(cat)
  [[ -z "$MANIFEST" ]] && MANIFEST=$(echo "$INPUT" | jq -r '.manifest // ""' 2>/dev/null || echo "")
  [[ -z "$OUTPUT_DIR" ]] && OUTPUT_DIR=$(echo "$INPUT" | jq -r '.output_dir // .target // ""' 2>/dev/null || echo "")
  [[ -z "$BUILD_PLAN" ]] && BUILD_PLAN=$(echo "$INPUT" | jq -r '.build_plan // ""' 2>/dev/null || echo "")
fi

[[ "$MANIFEST" == "null" ]] && MANIFEST=""
[[ "$OUTPUT_DIR" == "null" ]] && OUTPUT_DIR=""
[[ "$BUILD_PLAN" == "null" ]] && BUILD_PLAN=""

if [[ -z "$MANIFEST" || -z "$OUTPUT_DIR" ]]; then
  echo '{"gate_id":"gate.knowledge.injection","verdict":"FAIL","failures":[{"type":"input_error","detail":"缺少 --manifest 或 --output-dir"}]}'
  exit 2
fi
if [[ ! -f "$MANIFEST" || ! -d "$OUTPUT_DIR" ]]; then
  echo "{\"gate_id\":\"gate.knowledge.injection\",\"verdict\":\"FAIL\",\"failures\":[{\"type\":\"input_error\",\"detail\":\"manifest 或 output_dir 不存在\",\"manifest\":\"$MANIFEST\",\"output_dir\":\"$OUTPUT_DIR\"}]}"
  exit 2
fi

# 解析 YAML 需要 PyYAML: 依次尝试 python3/python, 取第一个可用的（无则 fail-closed）
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import yaml' >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
if [[ -z "$PY" ]]; then
  echo '{"gate_id":"gate.knowledge.injection","verdict":"FAIL","failures":[{"type":"input_error","detail":"未找到带 PyYAML 的 python 解释器"}]}'
  exit 2
fi

"$PY" - "$MANIFEST" "$OUTPUT_DIR" "$BUILD_PLAN" <<'PY'
import json
import os
import py_compile
import re
import sys
import tempfile

import yaml

# 技能落点按平台: claude-code=.claude/skills/; dsh=dsh/skills/; both=两处
# （platforms/dsh.yaml）。权威取 manifest.knowledge.relative_dirs，这里只做白名单校验。
DEFAULT_SKILL_REL_DIR = ".claude/skills/rag-knowledge-search"
ALLOWED_SKILL_REL_DIRS = (
    DEFAULT_SKILL_REL_DIR,
    "dsh/skills/rag-knowledge-search",
)
QUERY_PATH = "/api/co-knowledge/v1/agent/query"
DEFAULT_BASE_URL = "http://localhost:4910"
WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
WORKFLOW_ID_ASSIGN_RE = re.compile(r"DEFAULT_WORKFLOW_ID\s*=\s*(['\"])(.*?)\1")
BASE_URL_ASSIGN_RE = re.compile(r"DEFAULT_BASE_URL\s*=\s*(['\"])(.*?)\1")
AUTH_HEADER_RE = re.compile(r"Authorization['\"]?\s*[:=]\s*f?['\"]Bearer ", re.I)
# 旧实现的残留标记（新实现不得再出现旧服务发现/服务名/旧查询链路）
LEGACY_PATTERNS = [
    re.compile(r"openpalette", re.I),
    re.compile(r"\bmsb\b", re.I),
    re.compile(r"zae-ragcomponentservice", re.I),
    re.compile(r"/api/rkb/v1/query", re.I),
    re.compile(r"CO_KNOWLEDGE_AUTH_TOKEN"),
]
MCP_PATTERN = re.compile(r"\bmcp\b", re.I)
MAX_FAILURES = 50

manifest_path, output_dir, build_plan = sys.argv[1], sys.argv[2], sys.argv[3]

failures = []


def fail(ftype, **kw):
    item = {"type": ftype}
    item.update(kw)
    failures.append(item)


def is_within(child, parent):
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def load_text(path):
    try:
        with open(path, encoding="utf-8", errors="strict") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


# ── 1. manifest 结构与状态 ──
try:
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh) or {}
except Exception as exc:  # noqa: BLE001 - 任何解析失败都要落成可读 failure
    print(json.dumps({"gate_id": "gate.knowledge.injection", "verdict": "FAIL",
                      "failures": [{"type": "manifest_unreadable",
                                    "detail": str(exc), "manifest": manifest_path}]},
                     ensure_ascii=False))
    sys.exit(2)

if not isinstance(manifest, dict):
    fail("manifest_invalid", detail="顶层必须是映射")
    manifest = {}

status = manifest.get("status")
if status not in ("injected", "noop"):
    fail("manifest_status_invalid", status=status,
         detail="status 须为 injected/noop（error 状态说明注入失败, 不应进入构建）")

knowledge = manifest.get("knowledge")
if not isinstance(knowledge, dict):
    fail("manifest_invalid", detail="knowledge 段缺失或非映射")
    knowledge = {}
elif knowledge.get("injected") is not True:
    fail("manifest_status_invalid", detail="knowledge.injected 必须为 true")

workflow_id = knowledge.get("workflow_id")
if not isinstance(workflow_id, str) or not WORKFLOW_ID_RE.match(workflow_id):
    fail("workflow_id_invalid", workflow_id=workflow_id,
         detail="workflow_id 须匹配 ^[A-Za-z0-9_-]{1,128}$")

if knowledge.get("query_path") != QUERY_PATH:
    fail("endpoint_invalid", field="query_path", got=knowledge.get("query_path"),
         expected=QUERY_PATH)

base_url = knowledge.get("base_url")
if not isinstance(base_url, str) or not re.match(r"^https?://", base_url):
    fail("endpoint_invalid", field="base_url", got=base_url,
         detail="base_url 须为 http(s) 绝对地址")

skill_rel_dirs = knowledge.get("relative_dirs")
if skill_rel_dirs is None:  # 旧清单：只有 relative_dir
    skill_rel_dirs = [knowledge.get("relative_dir")]
if not isinstance(skill_rel_dirs, list) or not skill_rel_dirs:
    fail("relative_dir_invalid", got=skill_rel_dirs,
         detail="relative_dirs 必须是非空数组（或提供兼容字段 relative_dir）")
    skill_rel_dirs = [DEFAULT_SKILL_REL_DIR]
# 保序去重，并逐项白名单校验
skill_rel_dirs = list(dict.fromkeys(
    d for d in skill_rel_dirs if isinstance(d, str) and d
))
for rel_dir in skill_rel_dirs:
    if rel_dir not in ALLOWED_SKILL_REL_DIRS:
        fail("relative_dir_invalid", got=rel_dir,
             expected=list(ALLOWED_SKILL_REL_DIRS))
skill_rel_dirs = [d for d in skill_rel_dirs if d in ALLOWED_SKILL_REL_DIRS]
if not skill_rel_dirs:
    skill_rel_dirs = [DEFAULT_SKILL_REL_DIR]

files = knowledge.get("files")
if not isinstance(files, list) or not files:
    fail("manifest_invalid", detail="knowledge.files 须为非空数组")
    files = []

# ── 2. 路径存在性 + 逃逸检查 ──
output_abs = os.path.realpath(output_dir)
skill_abs_by_dir = {}
for rel_dir in skill_rel_dirs:
    skill_abs = os.path.realpath(os.path.join(output_dir, rel_dir))
    if not is_within(skill_abs, output_abs):
        fail("path_escape", path=rel_dir, detail="skill 目录逃出产物目录")
    skill_abs_by_dir[rel_dir] = skill_abs


def owning_dir(posix_rel):
    for rel_dir in skill_rel_dirs:
        if posix_rel == rel_dir or posix_rel.startswith(rel_dir + "/"):
            return rel_dir
    return None


checked_files = []
for rel in files:
    if not isinstance(rel, str) or not rel:
        fail("file_entry_invalid", entry=rel)
        continue
    posix_rel = rel.replace("\\", "/")
    if posix_rel.startswith("/") or ".." in posix_rel.split("/"):
        fail("path_escape", path=rel)
        continue
    rel_dir = owning_dir(posix_rel)
    if rel_dir is None:
        fail("file_outside_skill_dir", path=rel, allowed_dirs=skill_rel_dirs)
        continue
    abs_path = os.path.realpath(os.path.join(output_dir, posix_rel))
    if not is_within(abs_path, skill_abs_by_dir[rel_dir]):
        fail("path_escape", path=rel, detail="解析后不在 skill 目录内")
        continue
    if not os.path.isfile(abs_path):
        fail("file_missing", path=rel)
        continue
    checked_files.append((posix_rel, abs_path))

if not checked_files and not failures:
    fail("manifest_invalid", detail="没有可校验的注入文件")

# ── 3. SKILL.md frontmatter（每个落点目录各校验一次）──
for rel_dir in skill_rel_dirs:
    skill_md = os.path.join(skill_abs_by_dir[rel_dir], "SKILL.md")
    skill_text = load_text(skill_md)
    if skill_text is None:
        fail("file_missing", path=rel_dir + "/SKILL.md")
        continue
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", skill_text, re.DOTALL)
    if not fm_match:
        fail("skill_frontmatter_invalid", path=rel_dir + "/SKILL.md",
             detail="缺少 YAML frontmatter")
        continue
    try:
        fm = yaml.safe_load(fm_match.group(1)) or {}
    except yaml.YAMLError as exc:
        fail("skill_frontmatter_invalid", path=rel_dir + "/SKILL.md",
             detail=f"frontmatter 解析失败: {exc}")
        fm = {}
    if not isinstance(fm, dict):
        fail("skill_frontmatter_invalid", path=rel_dir + "/SKILL.md",
             detail="frontmatter 非映射")
        fm = {}
    if fm.get("name") != "rag-knowledge-search":
        fail("skill_frontmatter_invalid", path=rel_dir + "/SKILL.md",
             field="name", got=fm.get("name"), expected="rag-knowledge-search")
    if not isinstance(fm.get("description"), str) or not fm.get("description").strip():
        fail("skill_frontmatter_invalid", path=rel_dir + "/SKILL.md",
             field="description", detail="必须非空")

# ── 4. 客户端常量（每个落点目录各校验一次）──
for rel_dir in skill_rel_dirs:
    client_rel = rel_dir + "/scripts/rag_knowledge_search.py"
    client_text = load_text(os.path.join(output_dir, client_rel))
    if client_text is None:
        fail("file_missing", path=client_rel)
        continue
    wf_matches = WORKFLOW_ID_ASSIGN_RE.findall(client_text)
    if len(wf_matches) != 1:
        fail("workflow_id_render_invalid", path=client_rel,
             detail=f"DEFAULT_WORKFLOW_ID 赋值应恰好 1 次, 实际 {len(wf_matches)} 次")
    elif workflow_id and wf_matches[0][1] != workflow_id:
        fail("workflow_id_mismatch", path=client_rel,
             expected=workflow_id, actual=wf_matches[0][1])

    base_matches = BASE_URL_ASSIGN_RE.findall(client_text)
    if len(base_matches) != 1 or base_matches[0][1] != DEFAULT_BASE_URL:
        fail("endpoint_invalid", field="DEFAULT_BASE_URL", path=client_rel,
             expected=DEFAULT_BASE_URL,
             actual=base_matches[0][1] if base_matches else None)

    if QUERY_PATH not in client_text:
        fail("endpoint_invalid", field="query_path", path=client_rel,
             expected=QUERY_PATH, detail="客户端未引用固定查询路径")

    # Agent API 契约: 会话标识用 conversation_id（dialogue_id 仅旧字段兼容）,
    # 鉴权用 Authorization: Bearer <apiKey>
    if "conversation_id" not in client_text:
        fail("endpoint_invalid", field="conversation_id", path=client_rel,
             detail="客户端未使用 conversation_id 作为会话标识")
    if not AUTH_HEADER_RE.search(client_text):
        fail("endpoint_invalid", field="authorization", path=client_rel,
             detail="客户端未使用 Authorization: Bearer 鉴权")

# ── 5. 残留扫描（历史实现 / MCP）──
scanned = 0
for posix_rel, abs_path in checked_files:
    text = load_text(abs_path)
    if text is None:
        continue  # 非 UTF-8 视为二进制, 跳过（注入资产应为纯文本）
    scanned += 1
    for pat in LEGACY_PATTERNS:
        if pat.search(text):
            fail("legacy_marker_found", path=posix_rel, marker=pat.pattern)
    if MCP_PATTERN.search(text):
        fail("mcp_residue_found", path=posix_rel)

for rel_dir in skill_rel_dirs:
    for root, _dirs, names in os.walk(skill_abs_by_dir[rel_dir]):
        for name in names:
            if name.lower() in ("mcp.json", ".mcp.json"):
                fail("mcp_residue_found",
                     path=os.path.relpath(os.path.join(root, name), output_dir))

# ── 6. py_compile（编译产物写临时目录）──
with tempfile.TemporaryDirectory() as tmp:
    for posix_rel, abs_path in checked_files:
        if not posix_rel.endswith(".py"):
            continue
        cfile = os.path.join(tmp, posix_rel.replace("/", "__") + "c")
        try:
            py_compile.compile(abs_path, cfile=cfile, doraise=True)
        except py_compile.PyCompileError as exc:
            fail("py_compile_failed", path=posix_rel, detail=str(exc)[:300])

# ── 7. build-plan 对账（可选）──
if build_plan:
    if not os.path.isfile(build_plan):
        fail("input_error", detail=f"build_plan 不存在: {build_plan}")
    else:
        plan_text = load_text(build_plan) or ""
        blocks = []
        for bm in re.finditer(r"```yaml\n(.*?)```", plan_text, re.DOTALL):
            try:
                b = yaml.safe_load(bm.group(1))
            except yaml.YAMLError:
                continue
            if not isinstance(b, dict):
                continue
            nested = b.get("file")
            if isinstance(nested, dict):
                b = nested
            p = b.get("path") or nested
            if isinstance(p, str) and p:
                block = dict(b)
                block["path"] = p
                blocks.append(block)
        by_path = {}
        for b in blocks:
            by_path.setdefault(b["path"], []).append(b.get("generation") or "generate")
        for rel in files:
            if not isinstance(rel, str):
                continue
            gens = by_path.get(rel)
            if not gens:
                fail("build_plan_entry_missing", path=rel,
                     detail="注入文件必须在 build-plan 中声明")
            elif any(g != "pre_staged" for g in gens):
                fail("build_plan_generation_mismatch", path=rel, generations=gens,
                     detail="注入文件只能声明 generation: pre_staged（禁止双轨）")

total = len(failures)
payload = {
    "gate_id": "gate.knowledge.injection",
    "verdict": "FAIL" if failures else "PASS",
    "checked_files": len(checked_files),
    "scanned_text_files": scanned,
    "workflow_id": workflow_id,
    "failures": failures[:MAX_FAILURES],
}
if total > MAX_FAILURES:
    payload["failures_truncated"] = total - MAX_FAILURES
if not failures:
    payload["summary"] = "injected assets consistent with manifest and client constants"
print(json.dumps(payload, ensure_ascii=False))
sys.exit(2 if failures else 0)
PY
