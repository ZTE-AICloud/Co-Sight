#!/bin/bash
# G025 / runner.assets: 确定性资产执行（P1-2 直拷 + 步1.4 模板物化）+ hooks.json 引用完整性（P1-3）
#
# 背景: build-plan 中 generation: copy 条目为逐字拷贝（通用规则等），generation: template
# 条目为模板物化（高模板率文件如 gate 文档/settings，零 LLM）；两者均无需 LLM 生成；
# executor 的 Bash 白名单仅放行 scripts/gates/g*.sh 形式 —— 资产执行以 gate 脚本形态执行，
# 白名单零改动。
#
# 协议: --build-plan <plan> --output-dir <dir> → stdout JSON → exit 0(PASS)/2(FAIL)
# 阶段1a: 拷贝 —— 遍历 generation: copy 条目，cp source（插件内，相对 REPO_ROOT）→ path
# 阶段1b: 模板物化 —— 遍历 generation: template 条目，source（assets/templates/ 下模板，
#   相对 REPO_ROOT）经 build-plan frontmatter template_variables 渲染（{{var}} 替换）→ path。
#   变量唯一来源 = frontmatter template_variables 映射（数据驱动，加变量不改脚本）。
#   fail-closed: 条目缺 source / 模板文件缺失 / template_variables 非映射 / 模板含未声明
#   变量 → type:input_error FAIL（畸形输入不产出半成品）。
# 阶段2: 引用完整性 —— 产物内 hooks.json 的 command 路径 token 必须真实存在（相对 output_dir）
#   事故实证（demo/test11）: 逐字拷贝的 hooks.json 引用 4 个未随附脚本，拖到 Step 5
#   readiness-verifier 才被 LLM 发现 —— 本阶段在构建期确定性拦截。
#   范围克制: 只查 hooks.json command 中的相对路径 token（含 / 且 .py/.sh/.js 结尾），
#   不做通用 markdown 引用校验（那是 G023 cross 的职责，不重叠）。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PLAN="" && OD=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-plan) PLAN="$2"; shift 2;;
    --output-dir) OD="$2"; shift 2;;
    *) shift;;
  esac
done

python3 - "$PLAN" "$OD" "$REPO_ROOT" <<'PYEOF'
import json, os, re, shutil, sys

try:
    import yaml
except ImportError:
    yaml = None

plan_path, output_dir, repo_root = sys.argv[1], sys.argv[2], sys.argv[3]

VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)

def input_error(detail, **extra):
    emit({"gate_id": "runner.assets", "verdict": "FAIL",
          "failures": [dict({"type": "input_error", "detail": detail}, **extra)]}, 2)

if yaml is None:
    input_error("PyYAML 不可用，无法解析 build-plan yaml 块")

if not plan_path or not os.path.isfile(plan_path):
    input_error("build-plan 不存在或未传 --build-plan", path=plan_path)
if not output_dir or not os.path.isdir(output_dir):
    input_error("output-dir 不存在或未传 --output-dir", path=output_dir)

text = open(plan_path, encoding="utf-8").read()

# frontmatter（首个 --- 对）: template_variables 唯一来源
fm = {}
m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
if m:
    try:
        loaded = yaml.safe_load(m.group(1))
        if isinstance(loaded, dict):
            fm = loaded
    except Exception as e:
        input_error(f"build-plan frontmatter yaml 解析失败: {e}")

tvars = fm.get("template_variables")

blocks = []
for bm in re.finditer(r"```yaml\n(.*?)```", text, re.DOTALL):
    try:
        b = yaml.safe_load(bm.group(1))
    except Exception:
        continue
    if not isinstance(b, dict):
        continue
    # 双形态归一: 平铺 path: 为权威形态（schemas/build-plan.schema.yaml），嵌套 file: 包裹取内层；
    # 旧 v1 的 file: 字符串键沿用为 path（此前嵌套 dict 被误当 path 赋值，copy/template 条目静默跳过）
    nested = b.get("file")
    if isinstance(nested, dict):
        b = nested
    if b.get("path") or isinstance(nested, str):
        b["path"] = b.get("path") or nested
        blocks.append(b)

template_entries = [b for b in blocks if b.get("generation") == "template"]
if template_entries:
    if tvars is None:
        tvars = {}
    if not isinstance(tvars, dict):
        input_error("frontmatter template_variables 非映射（须为 var: value 形式）",
                    got=type(tvars).__name__)

copied, materialized, pre_staged, failures = [], [], [], []
for b in blocks:
    gen = b.get("generation")
    if gen not in ("copy", "template", "pre_staged"):
        continue
    fp, src = b["path"], b.get("source")

    # 预置资产（Step 1b 注入）: 只查存在, 绝不复制/覆盖——内容是注入器的产物,
    # 覆盖即破坏注入审计链（G029）。缺失交 orchestrator 回退注入步骤。
    if gen == "pre_staged":
        if os.path.isfile(os.path.join(output_dir, fp)):
            pre_staged.append(fp)
        else:
            failures.append({"type": "pre_staged_missing", "path": fp, "source": src})
        continue
    mode = "copy" if gen == "copy" else "template"
    if not src:
        failures.append({"type": "input_error",
                         "detail": f"generation: {mode} 条目缺 source（必填，插件内路径，相对 REPO_ROOT）",
                         "path": fp})
        continue
    src_abs = src if os.path.isabs(src) else os.path.join(repo_root, src)
    if not os.path.isfile(src_abs):
        ftype = "copy_source_missing" if gen == "copy" else "template_source_missing"
        failures.append({"type": ftype, "path": fp, "source": src})
        continue
    if gen == "copy":
        dst = os.path.join(output_dir, fp)
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        shutil.copyfile(src_abs, dst)
        copied.append(fp)
    else:
        tpl = open(src_abs, encoding="utf-8").read()
        names = set(VAR_RE.findall(tpl))
        unknown = sorted(n for n in names if n not in tvars)
        if unknown:
            failures.append({"type": "input_error",
                             "detail": f"模板含未声明变量 {unknown}（frontmatter template_variables 须逐个给出）",
                             "path": fp, "source": src, "undeclared": unknown})
            continue
        rendered = VAR_RE.sub(lambda mm: str(tvars[mm.group(1)]), tpl)
        dst = os.path.join(output_dir, fp)
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        materialized.append(fp)

if failures:
    emit({"gate_id": "runner.assets", "phase": "assets", "verdict": "FAIL",
          "copied": copied, "materialized": materialized,
          "pre_staged": pre_staged, "failures": failures}, 2)

# ─── 阶段2: hooks.json 引用完整性（独立于资产执行结果，FAIL 合并上报）───
hook_missing = []
for root, _dirs, fs in os.walk(output_dir):
    if "hooks.json" not in fs:
        continue
    hj = os.path.join(root, "hooks.json")
    try:
        spec = json.load(open(hj, encoding="utf-8"))
    except Exception as e:
        hook_missing.append({"type": "hook_json_invalid", "hook": os.path.relpath(hj, output_dir),
                             "error": str(e)})
        continue
    cmds = []
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "command" and isinstance(v, str):
                    cmds.append(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(spec)
    for cmd in cmds:
        for tok in set(re.findall(r"[\w./-]+/[\w./-]*\.(?:py|sh|js)\b", cmd)):
            if tok.startswith(("http://", "https://")):
                continue
            if not os.path.isfile(os.path.join(output_dir, tok)):
                hook_missing.append({"type": "hook_ref_missing",
                                     "hook": os.path.relpath(hj, output_dir),
                                     "ref": tok})

all_failures = failures + hook_missing
if all_failures:
    emit({"gate_id": "runner.assets", "phase": "assets+ref-integrity", "verdict": "FAIL",
          "copied": copied, "materialized": materialized,
          "pre_staged": pre_staged, "failures": all_failures}, 2)
emit({"gate_id": "runner.assets", "phase": "assets+ref-integrity", "verdict": "PASS",
      "copied": copied, "copied_count": len(copied),
      "materialized": materialized, "materialized_count": len(materialized),
      "pre_staged": pre_staged, "pre_staged_count": len(pre_staged)}, 0)
PYEOF
