#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engine_probe.py — 从被测 agent 的引擎实现文件里抽取结构化声明。

只抽"行为契约"，不整文件入上下文：CLI 参数、退出码、规则表、排除表、
严重度分级、self-test 场景数。Python 引擎走 AST，其余语言走正则兜底。
"""

import ast
import re
from pathlib import Path

import config
from common import read_text

# 只抽这些名字形态的模块级常量（规则表 / 排除表 / 严重度表等）。
# 允许前导下划线（如 _RULE_SPECS / _X03_LITERALS），允许后缀变形。
# 允许任意数量的前导分段（_X03_LITERALS / _RULE_SPECS / SCANNABLE_EXTS）
DECLARATION_NAME_RE = re.compile(
    r"^_?(?:[A-Z0-9]+_)*(RULES?|RULE_?SPECS?|RULESET|EXCLUDES?|EXCLUDE_\w+|"
    r"DENY\w*|ALLOW\w*|BLOCK\w*|SEVERITY\w*|PATTERNS?|LITERALS?|"
    r"SCANNABLE\w*|IGNORE\w*|SKIP\w*)$",
    re.IGNORECASE,
)

EXIT_CODE_RE = re.compile(r"(?:sys\.exit|process\.exit|exit)\(\s*(\d+)\s*\)")
# 文档串里的退出码契约，如 "0 = 扫描完成；1 = 自检失败；2 = 参数错误"
EXIT_DOC_RE = re.compile(r"(?:^|[；;，,\s])(\d+)\s*[=:：]\s*([^；;，,\n]{2,40})")
CLI_ARG_RE = re.compile(r"""(?:add_argument|option)\(\s*['"]([^'"]+)['"]""")
SELFTEST_FLAG_RE = re.compile(r"""['"]--(self-test|selftest)['"]""")
CASE_MARKER_RE = re.compile(r"""['"](?:case|scenario|用例|场景)\s*\d+['"]""", re.I)


def _truncate(items, limit=40):
    """限制清单长度，防止巨型规则表撑爆上下文。"""
    items = [str(item) for item in items]
    if len(items) <= limit:
        return items
    return items[:limit] + [f"...（共 {len(items)} 项，已截断）"]


# ============================== Python AST 抽取 ==============================

def _literal_from_node(node):
    """把 AST 节点还原成 Python 字面量；失败返回 None。"""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _describe_tuple(item, limit=80):
    """把规则表里的一条元组压成一行描述。

    规则表常见形态：(id, 正则, 分组号, 严重度, 描述) —— 正则部分极长且对画像无用，
    只保留 id / 严重度 / 描述这类短字段。
    """
    if isinstance(item, dict):
        name = item.get("id") or item.get("name") or item.get("rule")
        desc = (item.get("desc") or item.get("description")
                or item.get("name") or item.get("pattern"))
        return f"{name}: {desc}" if name else str(item)[:limit]

    if isinstance(item, (list, tuple)):
        parts = []
        for cell in item:
            if isinstance(cell, str) and len(cell) > limit:
                continue  # 丢掉超长正则，保留可读描述
            if isinstance(cell, (list, tuple, set, dict)):
                continue
            parts.append(str(cell))
        if parts:
            return " | ".join(parts)[:limit]
        return str(item)[:limit]

    return str(item)[:limit]


def _summarize_literal(value, limit=40):
    """把规则表/排除表翻成简短字符串清单。"""
    if isinstance(value, dict):
        return _truncate([f"{k}: {v}" for k, v in value.items()], limit)
    if isinstance(value, (list, tuple, set)):
        return _truncate([_describe_tuple(item) for item in value], limit)
    return [str(value)]


def _source_name_of(node):
    """取赋值右值所引用的名字：_RULE_SPECS -> '_RULE_SPECS'；其余返回 None。

    规则表常用推导式间接构造（RULES = [{...} for ... in _RULE_SPECS]），
    直接 literal_eval 会失败，需要顺着迭代对象找回真正的数据表。
    """
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        return _source_name_of(node.generators[0].iter)
    if isinstance(node, ast.Name):
        return node.id
    return None


_MEANINGFUL_STRING_RE = re.compile(r"[一-鿿]|\s")
# 正则字面量的特征串——这类字符串描述的是匹配形态，不是行为契约，丢弃
_REGEX_HINT_RE = re.compile(r"\\[sSdDwWbB]|\[\^|\(\?:|\{\d+,\d*\}")


def _harvest_strings(node, limit=40, max_len=80):
    """从含函数调用的字面量里捞"说人话"的字符串。

    规则表常写成 (id, re.compile(...), 2, "P1", "描述")，整块无法 literal_eval。
    这里只保留可读描述（含中文或空格、长度适中），丢掉正则与裸标识符。
    """
    found = []
    seen = set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Constant) or not isinstance(sub.value, str):
            continue
        text = sub.value.strip()
        if not (4 <= len(text) <= max_len):
            continue
        if not _MEANINGFUL_STRING_RE.search(text):
            continue
        if _REGEX_HINT_RE.search(text):
            continue
        if text in seen:
            continue
        seen.add(text)
        found.append(text)
        if len(found) >= limit:
            break
    return found


def _extract_module_docstring(tree):
    """取模块 docstring 原文。"""
    try:
        return ast.get_docstring(tree) or ""
    except (TypeError, ValueError):
        return ""


_DOC_HEADING_RE = re.compile(r"退出码|exit\s*code", re.IGNORECASE)


def _parse_doc_exit_codes(docstring):
    """从模块 docstring 里解析退出码契约。

    契约常写成「标题行 + 下一行」两行形态：
        退出码契约：
            0 = 扫描完成（含零命中）；1 = 自检失败；2 = 参数错误。
    因此命中标题后要连带解析紧随其后的若干行。
    """
    codes = {}
    lines = docstring.splitlines()
    for position, line in enumerate(lines):
        if not _DOC_HEADING_RE.search(line):
            continue
        # 标题行自身可能就带契约
        candidates = [line]
        for follower in lines[position + 1:position + 4]:
            if follower.strip():
                candidates.append(follower)
            elif len(candidates) > 1:
                break
        for candidate in candidates:
            for number, desc in EXIT_DOC_RE.findall(candidate):
                codes.setdefault(int(number), desc.strip())
    return codes


def probe_python(path, source):
    """用 AST 抽取 Python 引擎的结构化声明。解析失败返回 None。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    raw = {}           # 名字 -> 原始字面量（只收模块级）
    references = {}    # 名字 -> 被引用的数据表名
    cli_args = set()

    for node in tree.body:
        # 模块级常量声明（只看顶层，避免把函数内的局部变量当常量）
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not DECLARATION_NAME_RE.match(target.id):
                    continue
                value = _literal_from_node(node.value)
                if value is not None:
                    raw[target.id] = value
                    continue
                # 推导式间接构造：记下上游数据表名
                upstream = _source_name_of(node.value)
                if upstream:
                    references[target.id] = upstream
                    continue
                # 含函数调用的字面量（如 re.compile）：捞可读描述字符串
                harvested = _harvest_strings(node.value)
                if harvested:
                    raw[target.id] = harvested

        # CLI 参数（walk 整个树：add_argument 常在 build_parser 函数里）
        # add_argument 的位置参数里可能同时有短选项与长选项（"-o", "--output"），
        # 全部收集，否则长选项形态会丢失。
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                if getattr(inner.func, "attr", None) != "add_argument":
                    continue
                for arg in inner.args:
                    literal = _literal_from_node(arg)
                    if isinstance(literal, str):
                        cli_args.add(literal)

    declarations = {}
    for name in sorted(set(list(raw) + list(references))):
        if name in references:
            upstream = references[name]
            # 用上游数据表的内容代表这个推导式声明
            if upstream in raw:
                declarations[name] = _summarize_literal(raw[upstream])
            else:
                declarations[name] = [f"（由 {upstream} 推导生成）"]
        else:
            declarations[name] = _summarize_literal(raw[name])

    docstring = _extract_module_docstring(tree)
    exit_codes = {int(m) for m in EXIT_CODE_RE.findall(source)}
    exit_codes.update(_parse_doc_exit_codes(docstring).keys())

    return {
        "declarations": declarations,
        "references": {k: v for k, v in references.items()},
        "cli_args": sorted(cli_args),
        "exit_codes": sorted(exit_codes),
        "exit_code_contract": {str(k): v for k, v in
                               sorted(_parse_doc_exit_codes(docstring).items())},
    }


# ============================== 正则兜底 ==============================

def probe_generic(source):
    """非 Python 引擎的正则兜底抽取。"""
    declarations = {}
    for match in re.finditer(
        r"^(?:const|let|var|export\s+const)?\s*([A-Z][A-Z0-9_]{2,})\s*=\s*(\[|\{)",
        source,
        re.MULTILINE,
    ):
        name = match.group(1)
        if DECLARATION_NAME_RE.match(name):
            declarations.setdefault(name, ["（非 Python 引擎，仅识别到声明名）"])
    return {
        "declarations": declarations,
        "references": {},
        "cli_args": sorted(set(CLI_ARG_RE.findall(source))),
        "exit_codes": sorted({int(m) for m in EXIT_CODE_RE.findall(source)}),
        "exit_code_contract": {},
    }


# ============================== 引擎文件定位 ==============================

def find_engine_candidates(root, structure_index):
    """定位引擎实现文件：先在工程结构索引里找，再按扩展名在根目录找。"""
    root = Path(root)
    candidates = []

    for rel in structure_index:
        if any(Path(rel).name.endswith(ext) for ext in config.ENGINE_EXTS):
            path = root / rel
            if path.is_file():
                candidates.append(path)

    for ext in config.ENGINE_EXTS:
        for path in sorted(root.glob(f"*{ext}")):
            if path.is_file() and path not in candidates:
                candidates.append(path)

    return candidates[:3]


def probe_engine(root, structure_index):
    """抽取引擎结构化声明；无引擎返回 None。"""
    candidates = find_engine_candidates(root, structure_index)
    if not candidates:
        return None

    best = None
    for path in candidates:
        source = read_text(path)
        if not source:
            continue
        result = probe_python(path, source) if path.suffix == ".py" else None
        if result is None:
            result = probe_generic(source)

        result["source_file"] = path.relative_to(root).as_posix()
        result["source_bytes"] = path.stat().st_size
        result["self_test"] = {
            "has_flag": bool(SELFTEST_FLAG_RE.search(source)),
            "case_markers": len(set(CASE_MARKER_RE.findall(source))),
        }
        if best is None or result["source_bytes"] > best["source_bytes"]:
            best = result

    return best
