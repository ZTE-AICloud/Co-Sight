#!/usr/bin/env bash
# G030: DSH 产物结构门禁（gate.dsh.output）
#
# 对象: output/agents/{name}/v1/dsh/（platform ∈ {dsh, both} 时）
# 目的: DSH 的 agent 只能是「bundle 包 → cordis.patch.yml 插入 preset 行」，
#       目录形态错误在 dsh 侧只会表现为"启动时跳过 bundle"，因此在构建期确定性拦截。
#       事实源: knowledge/agent-creation/platforms/dsh.yaml。
#
# 协议:
#   argv: --output-dir <产物根 v1/> [--build-plan <build-plan.md>]
#   stdin JSON 兜底: {"output_dir"|"target": ..., "build_plan": ...}（g026 批跑路径）
# stdout: {"gate_id":"gate.dsh.output","verdict":"PASS|FAIL","failures":[...],"concerns":[...]}
# 退出码: 0=PASS（可能带 concerns） / 2=FAIL
#
# platform 判定: build-plan frontmatter platforms[];
#   无 build-plan 时按 output_dir/dsh 是否存在推断（不存在 → 不适用，PASS）。
#
# 检查项:
#   1. dsh/package.json 合法 JSON，name/version 形态正确，dsh.bundle.patch 指向
#      dsh/ 内真实文件（禁止逃逸）
#   2. dsh/cordis.patch.yml 可解析（容忍 !!js 表达式），顶层为列表，
#      至少一行 @deepseek-ai/dsh-agent-preset
#   3. preset.config: id kebab-case 且非空、plugins 非空；行 id 全包唯一
#   4. 插件行 name 非空且形态合法；所有 toolName 在 preset 内唯一
#   5. tool-subagent 行必须有 provider + persona；
#      required_row_config 列出的包必须带齐必填 config（漏写 → 宿主 broken）
#   6. dsh/skills/*/SKILL.md frontmatter 含 name(kebab-case) + description；技能名唯一；
#      存在技能时必须用 createRequire(baseUrl) 挂载且解析本包 package.json
#   7. 禁止产物（纯 dsh）: .claude/settings.json / hooks / agents / skills
#   8. dsh 内容（README 除外）不得残留 .claude/ * 与 Claude 专有工具名
#   9. dsh/install.sh 存在、有 shebang、bash -n 通过；dsh/README.md 存在
#  10. concerns: README 缺「能力差异/限制」声明
set -uo pipefail

OUTPUT_DIR=""
BUILD_PLAN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --build-plan) BUILD_PLAN="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

# g026 批跑时把整个 batch JSON 放在本脚本 stdin；heredoc 会占用 python 的 stdin，
# 因此先读出来经 argv 传入（手动执行时 stdin 是 tty，跳过）。
STDIN_JSON=""
if [[ ! -t 0 ]]; then
  STDIN_JSON="$(cat)"
fi

python - "$OUTPUT_DIR" "$BUILD_PLAN" "$STDIN_JSON" <<'PYEOF'
import json
import os
import re
import subprocess
import sys

try:
    import yaml
except ImportError:
    print(json.dumps({"gate_id": "gate.dsh.output", "verdict": "FAIL",
                      "failures": [{"type": "input_error", "detail": "PyYAML 不可用"}]}))
    sys.exit(2)

arg_out, arg_plan = sys.argv[1], sys.argv[2]
stdin_data = {}
raw = sys.argv[3] if len(sys.argv) > 3 else ""
if raw.strip():
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            stdin_data = parsed
    except Exception:
        pass

output_dir = arg_out or stdin_data.get("output_dir") or stdin_data.get("target") or ""
build_plan = arg_plan or stdin_data.get("build_plan") or ""
output_dir = "" if output_dir == "null" else output_dir
build_plan = "" if build_plan == "null" else build_plan

failures = []
concerns = []


def fail(kind, detail, **extra):
    failures.append(dict({"type": kind, "detail": detail}, **extra))


def concern(kind, detail, **extra):
    concerns.append(dict({"type": kind, "detail": detail}, **extra))


def emit(code):
    out = {"gate_id": "gate.dsh.output", "verdict": "FAIL" if code else "PASS",
           "failures": failures, "concerns": concerns}
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(code)


if not output_dir:
    fail("input_error", "缺少 --output-dir（或 stdin 的 output_dir/target）")
    emit(2)
if not os.path.isdir(output_dir):
    fail("input_error", "output_dir 不存在", path=output_dir)
    emit(2)


# ── platform 判定 ──────────────────────────────────────────────
class DshLoader(yaml.SafeLoader):
    """容忍 cordis patch 里的 !!js / !include 表达式。"""


def _expr(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return "!!js " + loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


DshLoader.add_constructor("tag:yaml.org,2002:js", _expr)
DshLoader.add_constructor("!js", _expr)
DshLoader.add_multi_constructor("!", _expr)

platforms = []
if build_plan and os.path.isfile(build_plan):
    text = open(build_plan, encoding="utf-8").read()
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
            if isinstance(fm.get("platforms"), list):
                platforms = [str(p) for p in fm["platforms"]]
        except Exception as exc:
            fail("build_plan_invalid", f"build-plan frontmatter 解析失败: {exc}")
            emit(2)
dsh_dir = os.path.join(output_dir, "dsh")
dsh_applicable = bool(platforms and ({"dsh", "both"} & set(platforms))) or os.path.isdir(dsh_dir)
if not dsh_applicable:
    emit(0)
if not os.path.isdir(dsh_dir):
    fail("missing_dir", "platform 含 dsh 但产物目录 dsh/ 不存在", path=dsh_dir)
    emit(2)
pure_dsh = "dsh" in platforms and "claude-code" not in platforms and "both" not in platforms


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def frontmatter(text):
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return None
    try:
        loaded = yaml.safe_load(m.group(1))
        return loaded if isinstance(loaded, dict) else None
    except Exception:
        return None


# ── 1. package.json ────────────────────────────────────────────
pkg_path = os.path.join(dsh_dir, "package.json")
pkg = {}
if not os.path.isfile(pkg_path):
    fail("missing_file", "缺 dsh/package.json", path="dsh/package.json")
else:
    try:
        pkg = json.loads(read(pkg_path))
    except Exception as exc:
        fail("invalid_json", f"dsh/package.json 不是合法 JSON: {exc}", path="dsh/package.json")
        pkg = {}
    if pkg:
        name = pkg.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", name):
            fail("package_name_invalid", "package.json name 缺失或不是合法 npm 包名", name=name)
        if not isinstance(pkg.get("version"), str) or not re.fullmatch(r"\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?", str(pkg.get("version", ""))):
            fail("package_version_invalid", "package.json version 缺失或非 semver", version=pkg.get("version"))
        patch_rel = ((pkg.get("dsh") or {}).get("bundle") or {}).get("patch")
        if not isinstance(patch_rel, str) or not patch_rel:
            fail("bundle_patch_missing", "package.json 缺 dsh.bundle.patch")
        else:
            patch_abs = os.path.normpath(os.path.join(dsh_dir, patch_rel))
            if os.path.isabs(patch_rel) or not patch_abs.startswith(dsh_dir + os.sep):
                fail("bundle_patch_escape", "dsh.bundle.patch 必须指向 dsh/ 内的相对路径", patch=patch_rel)
            elif not os.path.isfile(patch_abs):
                fail("bundle_patch_target_missing", "dsh.bundle.patch 指向的文件不存在", patch=patch_rel)

# ── 2~5. cordis.patch.yml ─────────────────────────────────────
preset_rows = []
inserted_rows = []
patch_path = os.path.join(dsh_dir, "cordis.patch.yml")
if not os.path.isfile(patch_path):
    fail("missing_file", "缺 dsh/cordis.patch.yml", path="dsh/cordis.patch.yml")
else:
    try:
        doc = yaml.load(read(patch_path), Loader=DshLoader)
    except Exception as exc:
        fail("patch_yaml_invalid", f"cordis.patch.yml 解析失败: {exc}", path="dsh/cordis.patch.yml")
        doc = None
    if doc is not None:
        if not isinstance(doc, list):
            fail("patch_toplevel_invalid", "cordis.patch.yml 顶层必须是列表（- insert: [...]）")
            doc = []
        for entry in doc:
            if isinstance(entry, dict) and isinstance(entry.get("insert"), list):
                inserted_rows.extend(r for r in entry["insert"] if isinstance(r, dict))
        preset_rows = [r for r in inserted_rows
                       if r.get("name") == "@deepseek-ai/dsh-agent-preset"]
        if not preset_rows:
            fail("preset_missing", "未找到 @deepseek-ai/dsh-agent-preset 行——DSH 无法发现该 Agent")

pkg_name = pkg.get("name") if isinstance(pkg.get("name"), str) else ""
row_ids = [r.get("id") for r in inserted_rows if isinstance(r.get("id"), str) and r.get("id")]
dup_ids = sorted({i for i in row_ids if row_ids.count(i) > 1})
if dup_ids:
    fail("duplicate_row_id", "cordis.patch.yml 行 id 重复", ids=dup_ids)

all_tool_names = []


def collect_plugins(plugins, owner):
    """展平 preset plugins（group 的 config 也是行列表）。"""
    flat = []
    for row in plugins:
        if not isinstance(row, dict):
            fail("plugin_row_invalid", f"{owner}: 插件行必须是对象")
            continue
        flat.append(row)
        nested = row.get("config")
        if isinstance(nested, list):
            flat.extend(collect_plugins(nested, owner))
    return flat


# DSH 0.2 起下列插件的关键字段「必填、无默认值」：preset 漏写时宿主仍会注册该
# preset，但会把它标记为 broken（UI 下拉不可选）。事实源: platforms/dsh.yaml
# required_row_config。
REQUIRED_ROW_CONFIG = {
    "@deepseek-ai/dsh-agent-instructions": ("maxBytes",),
    "@deepseek-ai/dsh-tool-fs-search": ("sampleOverCapGlobResults",),
    "@deepseek-ai/dsh-tool-todo": ("allowParallelInProgress",),
}

for preset in preset_rows:
    cfg = preset.get("config")
    if not isinstance(cfg, dict):
        fail("preset_config_missing", "preset 行缺 config")
        continue
    pid = cfg.get("id")
    if not isinstance(pid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", pid or ""):
        fail("preset_id_invalid", "preset config.id 缺失或不是 kebab-case", id=pid)
    plugins = cfg.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        fail("preset_plugins_empty", "preset config.plugins 必须是非空列表", id=pid)
        continue
    preset_rows_flat = collect_plugins(plugins, f"preset {pid}")
    # 行 id 在 preset 内必须唯一（不同 preset 可复用同名 id）
    preset_row_ids = [r.get("id") for r in preset_rows_flat
                      if isinstance(r.get("id"), str) and r.get("id")]
    dup_preset_ids = sorted({i for i in preset_row_ids if preset_row_ids.count(i) > 1})
    if dup_preset_ids:
        fail("duplicate_row_id", f"preset {pid}: 插件行 id 重复", ids=dup_preset_ids)
    for row in preset_rows_flat:
        pname = row.get("name")
        if not isinstance(pname, str) or not pname.strip():
            fail("plugin_name_missing", f"preset {pid}: 插件行缺 name", row=row.get("id"))
            continue
        if not (pname.startswith("@") or pname.startswith("cordis:") or pname.startswith(".")):
            fail("plugin_name_invalid", f"preset {pid}: 插件名形态可疑", name=pname)
        rcfg = row.get("config")
        if pname in REQUIRED_ROW_CONFIG:
            missing = [k for k in REQUIRED_ROW_CONFIG[pname]
                       if not isinstance(rcfg, dict) or k not in rcfg]
            if missing:
                fail("required_row_config_missing",
                     f"preset {pid}: {pname} 缺必填 config（宿主会标记 broken，UI 不可选）",
                     row=row.get("id"), missing=missing)
        if isinstance(rcfg, dict) and isinstance(rcfg.get("toolName"), str):
            all_tool_names.append(rcfg["toolName"])
        if pname == "@deepseek-ai/dsh-tool-subagent":
            if not isinstance(rcfg, dict):
                fail("subagent_config_missing", f"preset {pid}: tool-subagent 行缺 config", row=row.get("id"))
                continue
            for key in ("provider", "persona"):
                if not isinstance(rcfg.get(key), str) or not rcfg.get(key).strip():
                    fail("subagent_field_missing", f"preset {pid}: tool-subagent 缺 {key}", row=row.get("id"))
            tn = rcfg.get("toolName")
            if not isinstance(tn, str) or not tn.strip():
                fail("subagent_toolname_missing", f"preset {pid}: tool-subagent 缺 toolName", row=row.get("id"))
            elif not tn.startswith("subagent"):
                concern("subagent_toolname_convention",
                        f"toolName '{tn}' 未按 subagent_<role> 约定命名（可用但易与宿主工具混淆）")
    # 技能挂载: 有技能目录时必须用 createRequire(baseUrl) 解析本包
    skills_dir = os.path.join(dsh_dir, "skills")
    has_skills = os.path.isdir(skills_dir) and any(
        os.path.isfile(os.path.join(skills_dir, d, "SKILL.md")) for d in os.listdir(skills_dir))
    blob = json.dumps(cfg, ensure_ascii=False)
    mounts = re.findall(r"createRequire\(baseUrl\)\.resolve\(\s*['\"]([^'\"]+)['\"]", blob)
    if has_skills:
        if not mounts:
            fail("skills_not_mounted", "dsh/skills/ 存在技能，但 preset 没有 createRequire(baseUrl) 挂载 customSkillDirs")
        elif pkg_name:
            # snippet 形态为 resolve('<pkg>/package.json')；容忍裸包名写法
            mounted_pkgs = [m[: -len("/package.json")] if m.endswith("/package.json") else m
                            for m in mounts]
            if pkg_name not in mounted_pkgs:
                fail("skills_mount_wrong_package",
                     "customSkillDirs 解析的包与 package.json name 不一致",
                     expected=pkg_name, found=mounts)
    elif mounts:
        concern("skills_mount_without_skills", "preset 挂载了 customSkillDirs，但 dsh/skills/ 下没有技能")

dup_tools = sorted({t for t in all_tool_names if all_tool_names.count(t) > 1})
if dup_tools:
    fail("duplicate_tool_name", "preset 内 toolName 重复", toolNames=dup_tools)

# ── 6. skills frontmatter ────────────────────────────────────
skills_dir = os.path.join(dsh_dir, "skills")
seen_skills = {}
if os.path.isdir(skills_dir):
    for entry in sorted(os.listdir(skills_dir)):
        skill_md = os.path.join(skills_dir, entry, "SKILL.md")
        if not os.path.isfile(skill_md):
            concern("skill_md_missing", f"dsh/skills/{entry}/ 缺 SKILL.md")
            continue
        fm = frontmatter(read(skill_md))
        if fm is None:
            fail("skill_frontmatter_invalid", f"dsh/skills/{entry}/SKILL.md frontmatter 缺失或不可解析")
            continue
        sname = fm.get("name")
        desc = fm.get("description")
        if not isinstance(sname, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", sname or ""):
            fail("skill_name_invalid", f"dsh/skills/{entry}/SKILL.md name 缺失或非 kebab-case", name=sname)
        elif sname in seen_skills:
            fail("skill_name_duplicate", "技能名重复", name=sname, files=[seen_skills[sname], entry])
        else:
            seen_skills[sname] = entry
        if not isinstance(desc, str) or not desc.strip():
            fail("skill_description_missing", f"dsh/skills/{entry}/SKILL.md 缺 description")

# ── 7. 禁止产物（纯 dsh）──────────────────────────────────────
FORBIDDEN_PATHS = [".claude/settings.json", ".claude/hooks/hooks.json"]
if pure_dsh:
    for rel in FORBIDDEN_PATHS:
        if os.path.exists(os.path.join(output_dir, rel)):
            fail("forbidden_artifact", f"platform=dsh 不应生成 {rel}", path=rel)
    for rel in (".claude/agents", ".claude/skills"):
        if os.path.isdir(os.path.join(output_dir, rel)):
            fail("forbidden_artifact", f"platform=dsh 不应生成 {rel}/", path=rel)

# ── 8. Claude 残留引用（README 是能力差异声明处，豁免）──────────
CLAUDE_MARKS = [".claude/skills/", ".claude/agents/", ".claude/settings.json",
                "AskUserQuestion", "TodoWrite"]
scan_roots = [os.path.join(dsh_dir, "skills"), os.path.join(dsh_dir, "rules")]
scan_files = [os.path.join(dsh_dir, "cordis.patch.yml"), os.path.join(dsh_dir, "install.sh")]
for root in scan_roots:
    for base, _dirs, files in os.walk(root):
        scan_files.extend(os.path.join(base, f) for f in files if f.endswith((".md", ".yaml", ".yml")))
for path in scan_files:
    if not os.path.isfile(path):
        continue
    try:
        text = read(path)
    except Exception:
        continue
    hits = [m for m in CLAUDE_MARKS if m in text]
    if hits:
        fail("claude_reference", "DSH 产物内残留 Claude 专有引用", path=os.path.relpath(path, output_dir), marks=hits)

# ── 9. install.sh / README.md ────────────────────────────────
install_path = os.path.join(dsh_dir, "install.sh")
if not os.path.isfile(install_path):
    fail("missing_file", "缺 dsh/install.sh", path="dsh/install.sh")
else:
    text = read(install_path)
    if not text.startswith("#!"):
        fail("install_script_invalid", "dsh/install.sh 缺 shebang")
    proc = subprocess.run(["bash", "-n", install_path], capture_output=True, text=True)
    if proc.returncode != 0:
        fail("install_script_invalid", "dsh/install.sh 语法错误", error=proc.stderr.strip()[:500])

readme_path = os.path.join(dsh_dir, "README.md")
if not os.path.isfile(readme_path):
    fail("missing_file", "缺 dsh/README.md", path="dsh/README.md")
else:
    text = read(readme_path)
    if len(text.strip()) < 200:
        concern("readme_too_thin", "dsh/README.md 过短，难以说明安装与使用")
    if not re.search(r"能力差异|限制|limitation", text, re.IGNORECASE):
        concern("readme_capability_section_missing",
                "dsh/README.md 未见「能力差异/限制」节（settings/hooks 无等价物必须显式声明）")

if not os.path.isfile(os.path.join(output_dir, "CLAUDE.md")):
    fail("missing_file", "缺 CLAUDE.md（DSH 由 agent-instructions 在 agent 目录内读取）", path="CLAUDE.md")

emit(2 if failures else 0)
PYEOF
