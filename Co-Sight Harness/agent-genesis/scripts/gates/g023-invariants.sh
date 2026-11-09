#!/bin/bash
# G023: invariants 执行器（executor-generation-quality 方案 S4）
#
# 消费 build-plan v2 各文件块的 invariants[]（6 型 DSL），确定性校验生成产物。
#   file 模式: 由 agent-executor 逐文件调用（白名单 Bash），FAIL 输出 failed_invariants[] 供就地修订
#   batch 模式: 由 agent-executor 经 g026 批跑（提速方案 OPT-1.1）——g026 将完整 INPUT 原样
#     pipe 给子 gate，本模式从 stdin JSON（或 --input '<json>' 直传, 同 g017/g026 先例）
#     按键读取 build_plan/output_dir/files，一次进程跑整批，
#     输出统一 failures: [{file, invariant, reason}]（对齐 g026 收集契约）
#   cross 模式: 由 orchestrator 在 step-4 后跑第二趟（跨文件一致性，只定点重写 flagged 文件）
#
# 协议: stdout JSON {gate_id, mode, verdict, ...}；退出码 0=PASS / 2=FAIL
# stdin 捕获须在 bash 侧完成（python heredoc 会占用 stdin，见 g026 同款 G026_INPUT 模式）;
#   stdin 读取有界（timeout 10s）——开放 stdin 的后台场景不再无界挂死, 超时按空输入 fail-closed
set -uo pipefail

# stdin 捕获（--input argv 为 canonical, 同 g017/g026 先例）:
#   --input 直传（executor 白名单/后台模式唯一可行方式, argv 任意位置均可）>
#   有界 stdin 读（timeout 10s, 开放 stdin 的后台场景不再无界挂死,
#   超时按空输入 fail-closed）> tty 无输入
G023_STDIN=""
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --input) G023_STDIN="${2:-}"; shift 2;;
    *) ARGS+=("$1"); shift;;
  esac
done
if [ -z "$G023_STDIN" ] && [ ! -t 0 ]; then
  G023_STDIN="$(timeout 10 cat 2>/dev/null || true)"
fi
export G023_STDIN

python3 - ${ARGS[@]+"${ARGS[@]}"} << 'PYEOF'
import json, os, re, sys, json as _json

# 批量模式输入: bash 侧已捕获 stdin（g026 pipe / 直调空）
stdin_data = None
raw = os.environ.get("G023_STDIN", "")
if raw.strip():
    try:
        stdin_data = json.loads(raw)
    except Exception:
        stdin_data = None

args = sys.argv[1:]
kv = {}
i = 0
while i < len(args):
    if args[i].startswith("--"):
        kv[args[i][2:]] = args[i+1] if i+1 < len(args) else ""
        i += 2
    else:
        i += 1
mode = kv.get("mode", "")
if not mode and isinstance(stdin_data, dict) and stdin_data.get("files") is not None:
    mode = "batch"

def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)

def fail(msg):
    emit({"gate_id": "gate.build.invariants", "mode": mode, "verdict": "FAIL", "error": msg}, 2)

def parse_build_plan(path):
    """返回文件块 dict 列表（统一 path 键）。

    双形态归一: 平铺 path: 为权威形态（schemas/build-plan.schema.yaml），
    嵌套 file: 包裹取内层 dict；旧 v1 的 file: 字符串键沿用为 path。
    （历史教训: 旧实现把嵌套 dict 误赋值给 path，与下游 f.get('path') == fp 的
    字符串语义矛盾 —— 平铺格式下解析恒空转，file 模式 24 次调用全部
    "不在 build-plan 中，跳过"却记 PASS，demo/test11 运行留痕实证，
    见 docs/plan/gate-toolchain-hotfix-implementation.md P0-1）
    """
    text = open(path, encoding="utf-8").read()
    blocks = []
    for bm in re.finditer(r"```yaml\n(.*?)```", text, re.DOTALL):
        try:
            b = __import__("yaml").safe_load(bm.group(1))
        except Exception:
            continue
        if not isinstance(b, dict):
            continue
        nested = b.get("file")
        if isinstance(nested, dict):
            blocks.append(nested)
            continue
        p = b.get("path") or nested
        if p and isinstance(p, str):
            b["path"] = p
            blocks.append(b)
    return blocks

# pre_staged 文件由 Step 1b 注入, 内容审计归 G029; 本 gate 只跑与"生成内容"无关的
# 确定性不变量（py_compile / 引用存在）, 避免 planner 为该文件写质量语义断言后
# 反过来逼 executor 重写预置资产（红线 6 禁双轨）。
PRE_STAGED_INVARIANTS = {"py_compile", "file_reference_exists"}


def applicable_invariants(block):
    invs = block.get("invariants") or []
    if block.get("generation") == "pre_staged":
        return [i for i in invs if i.get("type") in PRE_STAGED_INVARIANTS]
    return invs


def check_invariant(inv, fpath, output_dir):
    """返回 None=PASS 或 str=失败原因"""
    t = inv.get("type")
    target = os.path.join(output_dir, fpath)
    if t == "py_compile":
        import py_compile
        try:
            py_compile.compile(target, doraise=True)
        except Exception as e:
            return f"py_compile: {e}"
        return None
    if t == "json_schema_valid":
        try:
            d = json.load(open(target, encoding="utf-8"))
            if not isinstance(d, dict) or "$schema" not in d:
                return "缺 $schema 字段或非对象"
        except Exception as e:
            return f"JSON 解析: {e}"
        return None
    if not os.path.isfile(target):
        return f"产物不存在: {fpath}"
    content = open(target, encoding="utf-8").read()
    if t in ("frontmatter_field_nonempty", "frontmatter_field_absent"):
        field = inv.get("field", "")
        m = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        fm = {}
        if m:
            try:
                fm = __import__("yaml").safe_load(m.group(1)) or {}
            except Exception:
                fm = {}
        # 点分字段(tools.Write)沿路径导航; 普通字段顶层查
        if "." in field:
            parts, cur, ok = field.split("."), fm, True
            for pp in parts:
                if isinstance(cur, dict) and pp in cur:
                    cur = cur[pp]
                else:
                    ok, cur = False, None
                    break
            present = ok
        else:
            present = field in fm and fm.get(field) not in (None, "", [])
        if t == "frontmatter_field_nonempty" and not present:
            return f"frontmatter 缺字段或非空: {field}"
        if t == "frontmatter_field_absent" and present:
            return f"不应存在的字段存在: {field}"
        return None
    if t == "file_reference_exists":
        pat = inv.get("pattern", "")
        refs = re.findall(pat, content)
        for r in set(refs):
            r = (r or "").strip().strip("`,.)）")
            if not re.search(r"[\w.-]+\.[\w]+", r):
                continue
            # 命中 = 同目录 / output_dir 根 / output_dir 递归（按 basename 全库寻址）
            hit = os.path.isfile(os.path.join(os.path.dirname(target), r)) \
                or os.path.isfile(os.path.join(output_dir, r))
            if not hit:
                bn = os.path.basename(r)
                for root, _dirs, fs in os.walk(output_dir):
                    if bn in fs:
                        hit = True
                        break
            if not hit:
                return f"引用不存在: {r}"
        return None
    if t == "content_contains":
        if not re.search(inv.get("pattern", ""), content):
            return f"内容缺模式: {inv.get('pattern')}"
        return None
    return f"未知 invariant 类型: {t}"

if mode == "batch":
    # 批量协议（提速方案 OPT-1.1/1.8）: fail-closed 缺键，输出键对齐 g026 收集契约
    bp = (stdin_data or {}).get("build_plan")
    od = (stdin_data or {}).get("output_dir")
    batch_files = (stdin_data or {}).get("files")
    if not (bp and od):
        emit({"gate_id": "gate.build.invariants", "mode": "batch", "verdict": "FAIL",
              "failures": [{"type": "input_error",
                            "reason": "batch 模式需 INPUT 含 build_plan/output_dir"}]}, 2)
    if batch_files is not None and (not isinstance(batch_files, list) or not batch_files):
        emit({"gate_id": "gate.build.invariants", "mode": "batch", "verdict": "FAIL",
              "failures": [{"type": "input_error",
                            "reason": "files 须为非空字符串数组, 或省略（省略 = 全量声明文件——executor v2 末置校验）"}]}, 2)
    if not os.path.isfile(bp):
        emit({"gate_id": "gate.build.invariants", "mode": "batch", "verdict": "FAIL",
              "failures": [{"type": "input_error", "reason": f"build_plan 不存在: {bp}"}]}, 2)
    files = parse_build_plan(bp)
    if not files:
        emit({"gate_id": "gate.build.invariants", "mode": "batch", "verdict": "FAIL",
              "failures": [{"type": "input_error", "reason": "build-plan 未解析出任何 file:/path: 条目"}]}, 2)
    if batch_files is None:  # executor v2 末置校验: 省略 files = 全量声明文件
        batch_files = [b.get("path") for b in files if b.get("path")]
    flat = []  # [{file, invariant, reason}] —— 对齐 g026 收集契约
    for fp in batch_files:
        block = next((f for f in files if f.get("path") == fp), None)
        if block is None:
            flat.append({"file": fp, "invariant": None,
                         "reason": "文件不在 build-plan 声明中——未声明的产物不得进入 gate 循环"})
            continue
        for inv in applicable_invariants(block):
            r = check_invariant(inv, fp, od)
            if r:
                flat.append({"file": fp, "invariant": inv.get("type"), "reason": r})
    if flat:
        emit({"gate_id": "gate.build.invariants", "mode": "batch", "verdict": "FAIL", "failures": flat}, 2)
    emit({"gate_id": "gate.build.invariants", "mode": "batch", "verdict": "PASS",
          "checked_files": len(batch_files)}, 0)

elif mode == "file":
    bp, od, fp = kv.get("build-plan"), kv.get("output-dir"), kv.get("file")
    if not (bp and od and fp):
        fail("file 模式需 --build-plan --output-dir --file")
    files = parse_build_plan(bp)
    if not files:
        fail("build-plan 未解析出任何 file:/path: 条目 —— 检查 build-plan 格式或 parse_build_plan 兼容性（拒绝静默空转 PASS）")
    block = next((f for f in files if f.get("path") == fp), None)
    if block is None:
        emit({"gate_id": "gate.build.invariants", "mode": "file", "file": fp, "verdict": "FAIL",
              "error": "文件不在 build-plan 声明中 —— 未声明的产物不得进入 gate 循环"}, 2)
    failed = []
    invs = applicable_invariants(block)
    for inv in invs:
        r = check_invariant(inv, fp, od)
        if r:
            failed.append({"invariant": inv, "reason": r})
    if failed:
        emit({"gate_id": "gate.build.invariants", "mode": "file", "file": fp, "verdict": "FAIL",
              "failed_invariants": failed}, 2)
    emit({"gate_id": "gate.build.invariants", "mode": "file", "file": fp, "verdict": "PASS",
          "checked": len(invs)}, 0)

elif mode == "cross":
    bp, od = kv.get("build-plan"), kv.get("output-dir")
    if not (bp and od):
        fail("cross 模式需 --build-plan --output-dir")
    files = parse_build_plan(bp)
    if not files:
        fail("build-plan 未解析出任何 file:/path: 条目 —— 检查 build-plan 格式或 parse_build_plan 兼容性（拒绝静默空转 PASS）")
    findings = []
    paths = {f.get("path") for f in files}
    # 0) build-plan 声明的每个文件都必须真实存在于产物目录（防"声明了却没人生产"，
    #    例: demo/test11 的 phase/01-proposal.md 声明后从未生产，旧空转逻辑下无人发现）
    for fp in sorted(paths):
        if fp and not os.path.isfile(os.path.join(od, fp)):
            findings.append(f"声明未生产: build-plan 声明 {fp} 但产物目录中不存在")
    # 1) 引用闭合: CLAUDE.md 中引用的仓库内路径存在
    for probe in ("CLAUDE.md",):
        p = os.path.join(od, probe)
        if not os.path.isfile(p):
            continue
        content = open(p, encoding="utf-8").read()
        for m in set(re.findall(r"\.claude/[\w./-]+|schemas/[\w./-]+|phase/[\w./-]+", content)):
            m = m.rstrip(".,)）")
            if not os.path.exists(os.path.join(od, m)):
                findings.append(f"引用闭合: {probe} → {m} 不存在")
    # 2) skill 引用链: SKILL.md 声明的 references/scripts/templates 存在
    for f in files:
        fp = f.get("path", "")
        if not fp.endswith("SKILL.md"):
            continue
        p = os.path.join(od, fp)
        if not os.path.isfile(p):
            continue
        base = os.path.dirname(p)
        content = open(p, encoding="utf-8").read()
        # 产物内约定: skill 引用可锚定 skill 目录（references/scripts/templates/）
        # 或产物根（如 knowledge/templates/... 跨域引用，见 ppt-assistant 实例）；
        # 故把 knowledge/ 也纳入可匹配前缀，与 base/od 两级解析配套
        for m in set(re.findall(r"(?:knowledge|references|scripts|templates)/[\w./-]+", content)):
            m = m.rstrip(".,)）`*")
            if not os.path.exists(os.path.join(base, m)) \
               and not os.path.exists(os.path.join(od, m)):
                findings.append(f"skill 引用链: {fp} → {m} 不存在")
    # 3) kebab 命名: 文件路径组件
    for f in files:
        fp = f.get("path", "")
        # skill 的名字是宿主目录（SKILL.md 的 stem 恒为 "SKILL"）; subagent 用文件名
        name = os.path.basename(os.path.dirname(fp)) if fp.endswith("SKILL.md") \
            else os.path.splitext(os.path.basename(fp))[0]
        if f.get("type") in ("subagent", "skill") and name and not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
            findings.append(f"命名: {fp} 非 kebab-case")
    # 4) 脚本内静态路径拼接字面量: 提取 os.path.join 链 / Path("…") / 含分隔符字符串字面量,
    #    按脚本目录 → 产物根两级锚点解析存在性（os.path.exists——目录引用不算断链,
    #    吸取 file_reference_exists isfile 误报教训）。防"运行时断链拖到验证器才被发现":
    #    sed 批量替换事故实证 join(dirname(__file__), "templates", "report.html.template")
    #    拼接全串 grep 不可见, 静态机检在此前置覆盖。动态段($ {} ` f-string 占位)不可静态
    #    解析, 跳过（已知局限, 非误报）。过滤: 绝对路径跳过; 须匹配产物内前缀
    #    (references|scripts|templates|knowledge|phase|schemas)/ 或含扩展名。
    PATHY_PREFIX = re.compile(r"^(?:references|scripts|templates|knowledge|phase|schemas)/")
    LIT_RE = re.compile(r"['\"]([^'\"]+)['\"]")
    DYNAMIC = re.compile(r"[$`]|\{[^}]*\}")

    def join_args(content):
        """括号计数截取 os.path.join(...) 实参——支持嵌套调用(dirname(__file__) 等),
        [^)]* 会在首个内层右括号截断（事故形态正是 join(dirname(__file__), ...)）"""
        out = []
        for m in re.finditer(r"os\.path\.join\(", content):
            depth, i = 1, m.end()
            start = i
            while i < len(content) and depth:
                if content[i] == "(":
                    depth += 1
                elif content[i] == ")":
                    depth -= 1
                i += 1
            if depth == 0:
                out.append(content[start:i - 1])
        return out
    for f in files:
        fp = f.get("path", "")
        if not (re.search(r"\.(py|sh)$", fp) or f.get("type") == "script"):
            continue
        p = os.path.join(od, fp)
        if not os.path.isfile(p):
            continue
        try:
            content = open(p, encoding="utf-8").read()
        except Exception:
            continue
        cands = set()
        for jargs in join_args(content):
            parts = LIT_RE.findall(jargs)
            if len(parts) >= 2:
                cands.add("/".join(parts))
        for lit in LIT_RE.findall(content):
            if "/" in lit:
                cands.add(lit)
        for pm in re.finditer(r"\bPath\(\s*['\"]([^'\"]+)['\"]", content):
            cands.add(pm.group(1))
        for c in cands:
            c = c.strip().strip("`,.)）\"'")
            if not c or os.path.isabs(c) or DYNAMIC.search(c):
                continue
            if not (PATHY_PREFIX.match(c) or re.search(r"\.\w{1,10}$", c)):
                continue
            if not os.path.exists(os.path.join(os.path.dirname(p), c)) \
               and not os.path.exists(os.path.join(od, c)):
                findings.append(f"脚本路径: {fp} → {c} 不存在")
    if findings:
        emit({"gate_id": "gate.build.invariants", "mode": "cross", "verdict": "FAIL", "findings": findings}, 2)
    emit({"gate_id": "gate.build.invariants", "mode": "cross", "verdict": "PASS", "checked_files": len(files)}, 0)

else:
    fail("用法: g023-invariants.sh --mode file --build-plan P --output-dir D --file F | --mode cross --build-plan P --output-dir D")
PYEOF
