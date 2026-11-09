#!/usr/bin/env bash
# check-gate-registry — 注册表↔实现↔调用点 闭合机检（两段式: gates 防护门 + runners 运行器）
#
# 检查:
#   1. gates:/runners: 每条目——语义键语法（gate.<boundary>.<subject> / runner.<purpose>）、
#      script 存在、invoked_by 非空、scope 非空
#      （legacy sunset 2026-10-15: legacy 别名检查已删）
#   2. triggers[].gates 引用闭合: 语义键直查
#   3. scripts/gates/*.sh 每个脚本都被注册（无孤儿; internal_modules 豁免）
#   4. `blocking` 字段禁止回归（死元数据; 拦截语义内化于 gates 段成员资格）
#   5. YAML 重复键检测
#   6. 语义键幽灵检查 + 编号调用写法禁令（sunset 翻转, 承接原 check-legacy-names）:
#      - 活跃面（scripts/ skills/ agents/ phase/ schemas/, 非 tests 非 docs）出现的
#        gate.*/runner.* 形态词须为注册键或 module.* 内部模块名（防幽灵语义键）
#      - 活跃面出现引号包裹的 "G0xx" 调用写法即 FAIL（编号写法已作废; 纯文本历史注记不带引号形态, 不误报）（PyYAML safe_load 静默取后值——曾致 gate.plan.sanity 被
#      G022 残留重复键污染而机检无感, 2026-10-14 批 0 清障后加防回归）
#
# 用法: bash scripts/check-gate-registry.sh   （exit 0=PASS / 1=FAIL，failures 打印 stderr）
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$REPO_ROOT" <<'PYEOF'
import glob
import os
import re
import sys

import yaml

repo = sys.argv[1]
gates_yaml = os.path.join(repo, "phase", "gates", "gates.yaml")
failures = []

GATE_KEY_RE = re.compile(r"^gate\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*$")
RUNNER_KEY_RE = re.compile(r"^runner\.[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*$")

class StrictSafeLoader(yaml.SafeLoader):
    """safe_load 语义 + 重复映射键即抛错（safe_load 默认静默取后值）"""

def _construct_mapping(loader, node):
    loader.flatten_mapping(node)
    mapping = {}
    for k_node, v_node in node.value:
        key = loader.construct_object(k_node, deep=True)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"gates.yaml 重复键: {key}", node.start_mark)
        mapping[key] = loader.construct_object(v_node, deep=True)
    return mapping

StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)

try:
    with open(gates_yaml, encoding="utf-8") as f:
        d = yaml.load(f, Loader=StrictSafeLoader) or {}
except yaml.constructor.ConstructorError as e:
    print(f"FAIL: {e.problem}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"FAIL: gates.yaml 不可解析: {e}", file=sys.stderr)
    sys.exit(1)

sections = {"gates": GATE_KEY_RE, "runners": RUNNER_KEY_RE}
semantic_keys = set()
entries = {}         # 语义键 -> entry

# 1. 两段注册条目: 语义键语法 + 实现 + owner + scope + legacy 别名
for sec, key_re in sections.items():
    for key, entry in (d.get(sec) or {}).items():
        entries[key] = entry or {}
        semantic_keys.add(key)
        if not key_re.match(key):
            shape = "gate.<boundary>.<subject>" if sec == "gates" else "runner.<purpose>"
            failures.append(f"{sec}.{key}: 语义键不合语法（期望 {shape}）")
        e = entry or {}
        script = e.get("script", "")
        if not script:
            failures.append(f"{key}: 缺 script 字段")
        elif not os.path.isfile(os.path.join(repo, script)):
            failures.append(f"{key}: script 不存在: {script}")
        if not str(e.get("invoked_by", "")).strip():
            failures.append(f"{key}: 缺 invoked_by（每个条目必须有 owner）")
        if not str(e.get("scope", "")).strip():
            failures.append(f"{key}: 缺 scope（定位/作用范围/拦截与否三问须由 ID+registry 行自答）")
# 2. trigger gates 引用闭合（语义键直查——sunset 后唯一形态）
for tid, trig in (d.get("triggers") or {}).items():
    for name in (trig or {}).get("gates") or []:
        name = str(name)
        if name in semantic_keys:
            continue
        failures.append(f"trigger {tid}: 引用未注册 gate/runner: {name}（语义键直查未命中; 编号写法已随 sunset 作废）")

# 3. 无孤儿脚本
internal = set(d.get("internal_modules") or [])
registered_scripts = {str((e or {}).get("script", "")) for e in entries.values()}
for path in sorted(glob.glob(os.path.join(repo, "scripts", "gates", "g*.sh"))):
    rel = "scripts/gates/" + os.path.basename(path)
    if rel in registered_scripts or rel in internal:
        continue
    failures.append(f"孤儿脚本未注册: {rel}（gates/runners 注册或 internal_modules 豁免）")

# 4. blocking 字段禁止回归（死元数据——递归扫全结构, 注释不误报）
def walk_blocking(node, path):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "blocking":
                failures.append(f"gates.yaml {path}: blocking 字段禁止出现（死元数据已删, 拦截语义内化于 gates 段成员资格）")
            walk_blocking(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk_blocking(v, f"{path}[{i}]")
walk_blocking(d, "")

# 6. 语义键幽灵检查 + 编号调用写法禁令（sunset 翻转）
import io
scan_roots = ["scripts", "skills", "agents", "phase", "schemas"]
text_exts = (".sh", ".py", ".md", ".yaml", ".yml", ".json", ".jq")
ghost_re = re.compile(r"\b((?:gate|runner)\.[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*)\b")
quoted_gate_re = re.compile(r'["\']G[0-9]{3}["\']')
skip_tokens = {"gate.deliver.placeholder", "gate.skill.quality",  # 内部模块语义名（g005/g014, §1.3）
               "gate.deliver.completeness",                       # 内部模块语义名（g021）
               "gate.report.valid"}                               # 已裁撤键, 仅存历史注记文本
skip_prefixes = ("module.", "runner.review.assemble")  # 内部模块名（§1.3 module.* 形态）
for root_dir in scan_roots:
    base = os.path.join(repo, root_dir)
    for dp, _, fns in os.walk(base):
        for fn in fns:
            if not fn.endswith(text_exts):
                continue
            fp = os.path.join(dp, fn)
            rel = os.path.relpath(fp, repo)
            try:
                text = open(fp, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for m in ghost_re.finditer(text):
                token = m.group(1)
                if ".md" in token:  # 文件名引用（如 *.gate.template.md）, 非语义键
                    continue
                if token in semantic_keys or token in skip_tokens or any(token.startswith(p) for p in skip_prefixes):
                    continue
                failures.append(f"{rel}: 幽灵语义键未注册: {token}")
            if quoted_gate_re.search(text):
                failures.append(f"{rel}: 编号调用写法 \"G0xx\" 已随 sunset 作废（gates[]/JSON 请用语义键; 纯文本历史注记不带引号形态）")

if failures:
    for x in failures:
        print(f"FAIL: {x}", file=sys.stderr)
    sys.exit(1)

print(f"gate registry OK: {len(d.get('gates') or {})} gates, {len(d.get('runners') or {})} runners, "
      f"{len(d.get('triggers') or {})} triggers, 语义键闭合通过（legacy sunset 2026-10-15）")
PYEOF
