#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-soc-analyze —— 标书通读与方案提炼器（Map-Reduce）。

工作流：
  1. 解析命令行（excel 绝对路径 + 调优参数）
  2. 调用 common/excel_to_md.convert_excel_to_md
  3. 把 markdown 落盘到 Excel 同目录，命名 = {stem}.md
  4. 按 "## Sheet名" 锚点切分 md → chunks（单 sheet 超大时空行兜底再切）
  5. 并发调 LLM，每 chunk 输出结构化 JSON（Map 阶段）
  6. 合并所有 JSON 中间结果（程序层字段聚合，带 sheet 归属标签）
  7. 再调一次 LLM 做最终汇总，输出 8 段 markdown 报告（Reduce 阶段）
  8. 落盘中间结果 + 打印最终报告

要点：
  - LLM 配置统一走 common.cosight_runtime（纯环境变量 ANTHROPIC_* / OPENAI_*）；
  - --agent-id 可选（不参与任何路径解析）。
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
import sys
import time
from pathlib import Path

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-soc-analyze/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "soc"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap  # noqa: E402

bootstrap()  # venv 重入 + .env 加载 + preflight（失败 exit 3）


def _force_utf8_stdout() -> None:
    """CLI 入口启用：避免 Windows console 默认 GBK 解码失败。
    仅在 __main__ 里调用，不要在模块级别执行（会污染 pytest 等外部 capture）。"""
    if sys.platform != 'win32':
        return
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8', errors='replace')


try:
    import aiohttp
except ImportError:
    print("错误: 需要安装 aiohttp 库（pip install aiohttp，或运行 scripts/install.py）", flush=True)
    sys.exit(1)

try:
    import openpyxl  # noqa: F401
except ImportError:
    print("错误: 需要安装 openpyxl 库（pip install openpyxl，或运行 scripts/install.py）", flush=True)
    sys.exit(1)

try:
    from common.excel_to_md import convert_excel_to_md
    from common.cosight_runtime import resolve_runtime_llm_config
except Exception as e:
    print(f"错误: 无法导入 common.excel_to_md: {e}", flush=True)
    print("请确认 runtime/common/excel_to_md.py 存在", flush=True)
    sys.exit(1)


def get_llm_config() -> dict | None:
    """读取 LLM 配置（纯环境变量：OPENAI_* 主配置优先，ANTHROPIC_* 回退）。"""
    cfg = resolve_runtime_llm_config("soc_analyze")
    if not cfg:
        return None
    return {
        "base_url": cfg.get("base_url"),
        "api_key":  cfg.get("api_key"),
        "model":    cfg.get("model"),
    }


# ---------------------------------------------------------------------------
# Excel → Markdown
# ---------------------------------------------------------------------------

# 单 chunk（单 sheet）送入 LLM 的安全上限（字符）
# 中文 1 字 ≈ 1.5 token，留约 30K token 给 system prompt / 输出余量
MAX_CHUNK_CHARS = 60_000


def excel_to_markdown_file(excel_path: Path, drop_empty_cols: bool = True) -> Path:
    """Excel → markdown，落盘到 Excel 同目录，命名 = {stem}.md

    drop_empty_cols=True 时删除整列全空的列（宽矩阵 Excel 可大幅减少 chunk 数，
    默认开启）
    """
    md_path = excel_path.with_suffix(".md")

    print(f"📄 读取 Excel: {excel_path.name}", flush=True)
    print(f"   路径: {excel_path}", flush=True)
    if drop_empty_cols:
        print("   选项: drop_empty_cols=True（删除整列全空的列）", flush=True)

    try:
        md_content = convert_excel_to_md(
            excel_path,
            drop_empty_cols=drop_empty_cols,
        )
    except Exception as e:
        print(f"❌ Excel → Markdown 转换失败: {e}", flush=True)
        sys.exit(1)

    if not md_content or not md_content.strip():
        # 这是影响结果的关键异常：转换出空 md = 后续 LLM 看不到任何内容
        # = 报告会得到一堆"未提及"或编造内容。直接终止。
        print(
            "❌ Excel → Markdown 转换结果为空：所有 Sheet 都没有内容，"
            "无法进行标书分析。",
            flush=True,
        )
        sys.exit(1)

    md_path.write_text(md_content, encoding="utf-8")
    print(f"✅ Markdown 已落盘: {md_path.name}（{len(md_content)} 字符）", flush=True)
    return md_path


# ---------------------------------------------------------------------------
# Sheet 切分
# ---------------------------------------------------------------------------

# 严格：默认 excel_to_md 渲染（include_sheet_index=True）格式 — "## Sheet N: name"
#   group(1) = 数字, group(2) = name
# 约束：
#   - 必须以 "Sheet" 单词 + 1+ 个数字开头（如 Sheet 1, Sheet 12）
#   - 必须有 ": " 分隔符
#   - 行首匹配，规避表格内的 "| ## xxx"
_SHEET_INDEXED_RE = re.compile(
    r"^##\s+Sheet\s+(\d+):\s*(.+?)\s*$", re.MULTILINE,
)

# 兜底：excel_to_md 用 include_sheet_index=False 时的格式 — "## name"
# 仅当 Sheet 模式未命中时使用（保持向后兼容）
_SHEET_PLAIN_RE = re.compile(
    r"^##\s+(.+?)\s*$", re.MULTILINE,
)

# 段落分隔：连续两个换行（空行）。
# excel_to_md.py 在源头做了双重防御（表格行间单 \n、单元格内 \n 替换为空格），
# 因此输出里 \n\n 只会出现在 markdown 块之间，不会出现在表格内部。
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


def _detect_sheet_matches(text: str) -> tuple[list, str]:
    """
    按"严格优先、宽松兜底"的两层策略找 sheet 标题锚点。

    返回: (matches, source)
      - matches: re.Match 列表（按位置排序）
      - source: "indexed"（默认格式）或 "plain"（fallback）或 "none"
    """
    matches = list(_SHEET_INDEXED_RE.finditer(text))
    if matches:
        return matches, "indexed"
    matches = list(_SHEET_PLAIN_RE.finditer(text))
    if matches:
        return matches, "plain"
    return [], "none"


def _extract_sheet_name(m: re.Match, source: str) -> str:
    """根据匹配来源提取 sheet 名。indexed: group(2); plain: group(1)。"""
    if source == "indexed":
        return m.group(2).strip()
    return m.group(1).strip()


def chunk_md_by_sheet(md_text: str, max_chunk_chars: int = MAX_CHUNK_CHARS) -> list[dict]:
    """
    按 '## Sheet名' 锚点切分 md 为 chunks。

    匹配策略：
      1. 严格：'## Sheet N: name' 格式（excel_to_md 默认输出）
      2. 兜底：'## name' 格式（excel_to_md include_sheet_index=False）

    兜底：单 sheet > max_chunk_chars 时按"空行"二次切分；每子块前置 sheet 上下文以保留语义。
    """
    text = md_text.strip()
    if not text:
        return []

    matches, source = _detect_sheet_matches(text)
    if not matches:
        # 整篇没有任何 ## 标题——当成 1 个无标题 chunk
        if len(text) <= max_chunk_chars:
            return [{
                "chunk_index": 0,
                "sheet_name": "(无Sheet标题)",
                "content": text,
                "oversize": False,
                "sub_chunks": 1,
            }]
        return _split_oversize_chunk(0, "(无Sheet标题)", text, max_chunk_chars)

    chunks: list[dict] = []

    # 处理首部前言（标题前的内容）
    intro = text[: matches[0].start()].strip()
    if intro:
        chunks.append({
            "chunk_index": len(chunks),
            "sheet_name": "(标书前言)",
            "content": intro,
            "oversize": False,
            "sub_chunks": 1,
        })

    # 处理每个 sheet
    for i, m in enumerate(matches):
        sheet_name = _extract_sheet_name(m, source)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        if len(content) <= max_chunk_chars:
            chunks.append({
                "chunk_index": len(chunks),
                "sheet_name": sheet_name,
                "content": content,
                "oversize": False,
                "sub_chunks": 1,
            })
        else:
            chunks.extend(_split_oversize_chunk(len(chunks), sheet_name, content, max_chunk_chars))

    return chunks


def _split_oversize_chunk(start_index: int, sheet_name: str, content: str, max_chars: int) -> list[dict]:
    """
    单个 sheet > max_chars 时的兜底切分。

    策略：
      1. 按空行切段，贪婪合并到 <= per_chunk_target；用 min_chunk_size 防止开头小段孤岛
      2. 单段仍超长则字符级硬切，切点优先在空白处

    安全前提：表格不会被误切 — _PARAGRAPH_SPLIT_RE 只匹配 \n\n，
    而 Excel 表格行间只单 \n（由 excel_to_md.py 的 "\n".join() 强制）；
    同时 _SHEET_INDEXED_RE 用 ^## 行首锚点避开 "| ## Sheet N" 的误匹配。
    """
    header_prefix = f"## {sheet_name}"
    # 留 64 字符给 header + "续 i/N" + 缓冲余量
    per_chunk_target = max(200, max_chars - 64)
    # 最小块大小：避免出现"开头小段孤岛"（如 sheet 简介 75 字符 + N 个大段时，
    # 第 1 个 buffer 只装 75 字符，浪费 LLM 上下文窗口）
    min_chunk_size = max(2000, per_chunk_target // 4)

    # ---- 阶段 1：按空行切段并合并 ----
    segments = [seg.strip() for seg in _PARAGRAPH_SPLIT_RE.split(content) if seg.strip()]
    if not segments:
        segments = [content.strip()]

    buffers: list[str] = []
    current: list[str] = []
    current_len = 0

    for seg in segments:
        seg_len = len(seg) + 2
        candidate_len = current_len + seg_len
        if not current:
            # 空 buffer 直接放第一段
            current.append(seg)
            current_len = seg_len
            continue
        if candidate_len <= per_chunk_target:
            # 完整能塞
            current.append(seg)
            current_len = candidate_len
            continue
        # 塞不下：分两种情况
        if current_len >= min_chunk_size:
            # 当前 buffer 已够大 → flush 它，新段独立
            buffers.append("\n\n".join(current))
            current = [seg]
            current_len = seg_len
        else:
            # 当前 buffer 还太小，强行合并这一段（容忍轻微超 target），
            # 否则会出现一个几十字符的孤儿 chunk
            current.append(seg)
            current_len += seg_len
            buffers.append("\n\n".join(current))
            current = []
            current_len = 0

    if current:
        buffers.append("\n\n".join(current))

    # ---- 阶段 2：单段仍超长时按字符硬切 ----
    final_buffers: list[str] = []
    for buf in buffers:
        if len(buf) <= max_chars:
            final_buffers.append(buf)
            continue
        # 按字符硬切，切点优先在空白 / 换行处
        i = 0
        n = len(buf)
        while i < n:
            end = min(i + per_chunk_target, n)
            if end < n:
                # 在 end 之前找一个最近的空白字符作为切点（避免断词）
                window_end = max(end - 40, i + 1)
                split_at = end
                for j in range(end - 1, window_end, -1):
                    if buf[j] in " \t\n,。":
                        split_at = j
                        break
                final_buffers.append(buf[i:split_at].strip())
                i = split_at
            else:
                final_buffers.append(buf[i:end].strip())
                i = end

    parts_total = len(final_buffers)
    out: list[dict] = []
    for i, buf in enumerate(final_buffers, start=1):
        if parts_total == 1:
            sub_name = sheet_name
        else:
            sub_name = f"{sheet_name}（第 {i}/{parts_total} 部分）"
        composed = (
            f"{header_prefix}（续 {i}/{parts_total}）\n\n{buf}"
            if parts_total > 1 else buf
        )
        out.append({
            "chunk_index": start_index + i - 1,
            "sheet_name": sub_name,
            "content": composed,
            "oversize": True,
            "sub_chunks": parts_total,
        })
    return out


# ---------------------------------------------------------------------------
# LLM Prompts
# ---------------------------------------------------------------------------

# 中间结构化 prompt：让 LLM 对单个 sheet 输出 JSON
INTERMEDIATE_SYSTEM_PROMPT = (
    "你是一名资深的标书技术分析师，负责逐 sheet 抽取关键信息。\n"
    "你将收到【单个 Sheet 的完整内容】（仅此一个 sheet，不要联想其他 sheet）。\n"
    "请仔细阅读后，严格输出 JSON 对象，不要 markdown 代码块包裹，不要任何解释性文字。\n\n"
    "JSON Schema（必须全部 key 出现，缺失时填空字符串或空数组）：\n"
    "{\n"
    '  "tender_overview": "本 sheet 的覆盖范围与量化信息（如条数/占比/表头列名）",\n'
    '  "customer_needs": "本 sheet 体现的客户需求要点，1-3 句",\n'
    '  "hardware": "本 sheet 涉及的硬件清单（型号/数量等具体值），列表化字符串",\n'
    '  "software": "本 sheet 涉及的软件/平台清单",\n'
    '  "outsourcing": "本 sheet 涉及的外购服务或第三方产品",\n'
    '  "vendor_bias": "本 sheet 是否指定厂商或专有技术锁定（含原文片段）",\n'
    '  "tech_architecture": "本 sheet 体现的技术关键词/架构倾向",\n'
    '  "key_takeaways": ["本 sheet 的关键结论 1", "关键结论 2"],\n'
    '  "uncertainty": "本 sheet 中内容模糊、可能有歧义的点（没有就空字符串）"\n'
    "}\n"
    "注意事项：\n"
    "1. 严格 JSON 输出；任何额外文字都会被拒收。\n"
    "2. 涉及具体型号/数量时保留原文数字与单位。\n"
    "3. 如果某 sheet 是空表或只含表头，对应字段填空字符串。\n"
    "4. 如果一个字段有多项，用换行或列表字符串组织。\n"
    "5. 如果 sheet 是标书前言/总则/引用规范类，整体做总览，不要硬套硬件/软件等字段。"
)


# 最终汇总 prompt：输入合并 JSON，输出 8 段 markdown 报告
SUMMARY_SYSTEM_PROMPT = (
    "你是资深的标书技术分析师。下面是【已聚合】的中间分析结果（JSON 格式，"
    "字段涵盖 tender_overview / customer_needs / hardware / software / outsourcing / "
    "vendor_bias / tech_architecture / key_takeaways / uncertainty），覆盖标书的所有 Sheet。"
    "请据此输出最终的标书分析报告，严格按以下 8 个二级标题（## 开头），顺序固定。\n\n"
    "## 📊 标书概况\n"
    "- **总需求条数**：粗略统计（可注明 '约 N 条'）\n"
    "- **涉及 Sheet 范围**：列出所有相关 Sheet 名\n"
    "- **主要分布**：按主题类目统计条数并从大到小排序（top 3-5）\n\n"
    "## 🎯 客户主要需求\n"
    "用 1～3 句话概括客户的核心意图和痛点。\n\n"
    "## 🖥️ 硬件方案\n"
    "汇总所有 sheet 的硬件清单，覆盖：服务器（CPU/内存/硬盘/GPU等）、"
    "承载设备（路由器/网管平台）、防火墙、安全设备。未涉及的注明'标书未提及<类目>'。\n\n"
    "## 💻 软件方案\n"
    "汇总所有 sheet 的软件清单：智算方案（算力资源池/一体机）、通算方案（核心网/私有云/HCI）、"
    "自智网络等。未涉及的注明'标书未提及<类目>'。\n\n"
    "## 🛒 外购方案\n"
    "汇总外购软硬件清单（含服务、第三方产品等）。未涉及写明'标书未涉及外购方案'。\n\n"
    "## 🏷️ 厂商与专有技术分析\n"
    "判断标书是否存在厂商绑定或专有技术锁定倾向：\n"
    "- **关于特定厂商**：点名否 / 倾向 XX 厂商\n"
    "- **关于专有技术/厂商锁定**：反锁定条款（3-5 条核心条款）\n"
    "- **关于开放标准/互操作性**：是否要求 OpenStack/Kubernetes/OpenAPI 等\n\n"
    "## 🔧 技术架构倾向\n"
    "提取标书中反复出现的技术关键词与频次、识别架构风格（微服务/云原生/Serverless/数据湖/AI/ML等）。\n\n"
    "## 💡 综合结论\n"
    "用 4-6 个 ✅ 关键点总结：标书类型、厂商策略、技术倾向、数据主权与合规、关键启示。\n\n"
    "【格式要求】\n"
    "1. 严格使用 8 个二级标题，顺序固定。\n"
    "2. 每个标题下用有序列表、子标题或 markdown 表格组织细节。\n"
    "3. 涉及具体型号/数量/参数时尽量保留原文数字与单位；统计用'约 N 次'表述。\n"
    "4. 不要寒暄，不要总结性结尾语，直接出报告。\n"
    "5. **不要在标题前/后加任何前言、寒暄、总结性结尾语**（如不要输出'以下是分析报告'/'希望对您有帮助'/'综上'等），报告正文直接以 `## 📊 标书概况` 开头。\n"
    "6. 8 个二级标题是**输出契约**，每段都必须出现且按顺序排列，**缺任何一段都视为输出失败**。"
)


# 向后兼容旧名字
SYSTEM_PROMPT = SUMMARY_SYSTEM_PROMPT


# AGENT 必读保留规则（HTML 注释，对用户不可见，仅给 agent 看）：
# 把"agent 必须 verbatim 输出 8 段报告"的规则用 HTML 注释包起来嵌到工具输出顶部。
_ANALYSIS_PRESERVATION_RULES = """\
<!--
================================================================
AGENT 必读保留规则（HTML 注释，渲染时对用户不可见）

下面是要给用户的最终标书分析报告（脚本 Reduce 阶段直接输出）。
**你（agent）只做加上下文（如"以下是分析结果："前缀、中间产物路径），
不要做总结、润色、改写、重新组织**，以下强制项必须原样保留：

✅ 强制保留：**8 段结构保留区**（在 `<!--ANALYSIS-REPORT-START-->` 和 `<!--ANALYSIS-REPORT-END-->` 之间）
- 必须 8 段齐全且顺序固定（缺一不可）：
    1. ## 📊 标书概况
    2. ## 🎯 客户主要需求
    3. ## 🖥️ 硬件方案
    4. ## 💻 软件方案
    5. ## 🛒 外购方案
    6. ## 🏷️ 厂商与专有技术分析
    7. ## 🔧 技术架构倾向
    8. ## 💡 综合结论
- **不要**改 emoji / 改标题文字（如把 `## 📊 标书概况` 改成 `## 概述`）
- **不要**把任意两段合并成自定义结构（如"硬件方案 + 软件方案" → "方案概览"）
- **不要**抽取某一段单独展示而省略其他七段
- **不要**重排 8 段顺序
- **不要**简化 / 删除 / 改写段内任何字符
- **不要**在段内加"总结"或"补充"
- **不要**在标记区外重复报告内容（避免双份输出）

违规 = 输出失败。请原样保留。
================================================================
-->
"""


# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

def _extract_json_object(text: str) -> dict | None:
    """从 LLM 返回文本中尽量提取 JSON 对象（兜底解析）"""
    if not text:
        return None
    text = text.strip()
    # 直接尝试
    try:
        return json.loads(text)
    except Exception:
        pass
    # 去掉 markdown 代码块
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except Exception:
            pass
    # 取最外层花括号
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except Exception:
            return None
    return None


async def call_llm(
    llm_config: dict,
    user_prompt: str,
    system_prompt: str,
    json_mode: bool = False,
    timeout: int = 600,
) -> str:
    """异步调 LLM chat/completions；返回 content 原始文本"""
    url = f"{llm_config['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {llm_config['api_key']}",
    }
    payload = {
        "model": llm_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    # trust_env=True: aiohttp 默认忽略 HTTP_PROXY / HTTPS_PROXY / NO_PROXY（与 requests 不同），
    # 不开启则在需要代理的环境永远直连失败。
    async with aiohttp.ClientSession(timeout=client_timeout, trust_env=True) as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                raise RuntimeError(f"LLM 请求失败 (Status {resp.status}): {err_text[:200]}")
            data = await resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")


async def call_llm_with_json_retry(
    llm_config: dict,
    user_prompt: str,
    system_prompt: str,
    timeout: int = 600,
    max_retries: int = 1,
) -> dict:
    """调 LLM 并解析为 JSON；JSON 解析失败时重试一次，仍失败抛 ValueError"""
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        text = await call_llm(
            llm_config,
            user_prompt,
            system_prompt,
            json_mode=True,
            timeout=timeout,
        )
        parsed = _extract_json_object(text)
        if parsed is not None:
            return parsed
        last_err = ValueError(f"LLM 返回非 JSON（{len(text)} 字符）: {text[:120]!r}")
    raise last_err  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 中间分析（Map 阶段）
# ---------------------------------------------------------------------------

EMPTY_INTERMEDIATE: dict = {
    "tender_overview": "",
    "customer_needs": "",
    "hardware": "",
    "software": "",
    "outsourcing": "",
    "vendor_bias": "",
    "tech_architecture": "",
    "key_takeaways": [],
    "uncertainty": "",
}


def _normalize_intermediate(d: dict | None) -> dict:
    """归一化中间结果；缺字段用默认值补；key_takeaways 必须为 list[str]"""
    # deepcopy 避免对 EMPTY_INTERMEDIATE["key_takeaways"] 的 append 污染全局
    base = copy.deepcopy(EMPTY_INTERMEDIATE)
    if not isinstance(d, dict):
        return base
    for k, v in d.items():
        if k in base:
            base[k] = v
    # key_takeaways 规整
    if not isinstance(base["key_takeaways"], list):
        if isinstance(base["key_takeaways"], str) and base["key_takeaways"]:
            base["key_takeaways"] = [
                s.strip() for s in re.split(r"[\n;；]", base["key_takeaways"]) if s.strip()
            ]
        else:
            base["key_takeaways"] = []
    # 列表项只保留字符串
    base["key_takeaways"] = [str(x).strip() for x in base["key_takeaways"] if x is not None and str(x).strip()]
    return base


async def analyze_chunk(llm_config: dict, chunk: dict, timeout: int = 600) -> dict:
    """分析单个 chunk，返回标准化中间 JSON（含 _sheet_name / _chunk_index 元数据）"""
    sheet_name = chunk["sheet_name"]
    content = chunk["content"]
    user_prompt = (
        f"请分析以下 sheet 内容：{sheet_name}（{len(content)} 字符）。\n"
        f"只关注这个 sheet，不要推测其他 sheet。\n\n"
        f"---\n{content}\n---\n"
    )
    try:
        parsed = await call_llm_with_json_retry(
            llm_config, user_prompt, INTERMEDIATE_SYSTEM_PROMPT, timeout=timeout
        )
        return _normalize_intermediate(parsed) | {
            "_sheet_name": sheet_name,
            "_chunk_index": chunk["chunk_index"],
        }
    except Exception as e:
        # 失败时返回空结构 + 错误标记（不阻塞整体）
        return dict(EMPTY_INTERMEDIATE) | {
            "_sheet_name": sheet_name,
            "_chunk_index": chunk["chunk_index"],
            "_error": str(e),
        }


async def analyze_chunks_parallel(
    llm_config: dict,
    chunks: list[dict],
    concurrency: int = 4,
    timeout: int = 600,
) -> list[dict]:
    """并发分析所有 chunk（Semaphore 限速）；失败的 chunk 用空结果占位（带 _error）"""
    sem = asyncio.Semaphore(concurrency)

    async def _run(chunk: dict) -> dict:
        async with sem:
            t0 = time.time()
            result = await analyze_chunk(llm_config, chunk, timeout=timeout)
            elapsed = time.time() - t0
            ok = "_error" not in result
            mark = "✅" if ok else "⚠️"
            err_suffix = f" — {result['_error']}" if not ok else ""
            print(
                f"   {mark} [{result['_chunk_index'] + 1}/{len(chunks)}] "
                f"{chunk['sheet_name']} ({len(chunk['content'])} 字符) "
                f"→ {elapsed:.1f}s{err_suffix}",
                flush=True,
            )
            return result

    tasks = [_run(c) for c in chunks]
    return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# 合并 + Reduce 阶段
# ---------------------------------------------------------------------------

# 字符串型字段：每 sheet 用 "【sheet名】内容" 拼接
_TEXT_FIELDS = (
    "tender_overview",
    "customer_needs",
    "hardware",
    "software",
    "outsourcing",
    "vendor_bias",
    "tech_architecture",
    "uncertainty",
)


def _dedupe_keep_order(items: list[str]) -> list[str]:
    """按行去重（忽略空白差异），保留首次出现的顺序"""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if not it:
            continue
        for line in re.split(r"[\n;；。]", str(it)):
            line = line.strip()
            if not line:
                continue
            key = re.sub(r"\s+", "", line)
            if key in seen:
                continue
            seen.add(key)
            out.append(line)
    return out


def _normalize_block(val: str) -> str:
    """对单个 sheet 的字符串字段做行级保序去重后再拼接。
    避免同 sheet 内部 'line1\\nline1' 这种重复污染最终合并结果。"""
    if not val or not val.strip():
        return ""
    lines = _dedupe_keep_order([val])
    return "\n".join(lines)


def merge_intermediates(results: list[dict]) -> dict:
    """
    把 N 份中间 JSON 合并为 1 份：
      - 字符串型字段：按 sheet 顺序拼接（每段前缀 "【sheet名】"）
      - 列表型字段 (key_takeaways)：flatten + 按 normalize 去重，保留 sheet 归属前缀
    """
    # 用 deepcopy 避免 EMPTY_INTERMEDIATE["key_takeaways"] 列表被反复 append 后污染后续调用
    merged = copy.deepcopy(EMPTY_INTERMEDIATE)
    sheet_names: list[str] = []
    successful: list[str] = []
    failed: list[str] = []

    for r in results:
        sheet_name = r.get("_sheet_name", "?")
        sheet_names.append(sheet_name)
        if "_error" in r:
            failed.append(f"{sheet_name}: {r['_error']}")
            continue
        successful.append(sheet_name)
        # 字符串字段拼接，保留 sheet 归属前缀；先对单 sheet 内部做行级去重
        for field in _TEXT_FIELDS:
            val = _normalize_block(r.get(field) or "")
            if val:
                if merged[field]:
                    merged[field] = merged[field] + "\n" + f"【{sheet_name}】{val}"
                else:
                    merged[field] = f"【{sheet_name}】{val}"
        # 列表字段
        for kt in r.get("key_takeaways", []):
            if isinstance(kt, str) and kt.strip():
                merged["key_takeaways"].append(f"【{sheet_name}】{kt.strip()}")

    # 去重 key_takeaways（每个已带 【sheet】 前缀，跨 sheet 不重复）
    merged["key_takeaways"] = _dedupe_keep_order(merged["key_takeaways"])
    # uncertainty 已经是拼接好的整段，再做一次行级去重（消除同 sheet 内重复行）
    if merged["uncertainty"]:
        merged["uncertainty"] = _normalize_block(merged["uncertainty"])

    return {
        "merged": merged,
        "sheet_names": sheet_names,
        "successful_sheets": successful,
        "failed_sheets": failed,
    }


async def final_summary(
    llm_config: dict,
    merged_summary: dict,
    total_chunks: int,
    user_requirement: str = "",
    timeout: int = 900,
) -> str:
    """最终汇总：输入合并 JSON，输出 8 段 markdown 报告"""
    payload = {
        "user_requirement": user_requirement,
        "sheet_summary": {
            "total_chunks": total_chunks,
            "sheets": merged_summary["sheet_names"],
            "successful": merged_summary["successful_sheets"],
            "failed": merged_summary["failed_sheets"],
        },
        "merged_intermediate": merged_summary["merged"],
    }
    user_prompt = (
        "请基于以下聚合后的中间分析结果（来自标书各 sheet 的并行分析）输出最终报告。\n\n"
        f"---\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n---\n"
    )
    if user_requirement:
        user_prompt = f"【用户的分析要求】\n{user_requirement}\n\n" + user_prompt

    return await call_llm(
        llm_config,
        user_prompt,
        SUMMARY_SYSTEM_PROMPT,
        json_mode=False,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="标书通读与方案提炼器（Map-Reduce：按 sheet 切分并行分析 + 汇总）"
    )
    parser.add_argument("excel", help="标书 Excel 文件绝对路径")
    parser.add_argument("--agent-id", default=None,
                        help="兼容参数：不参与路径解析，可省略")
    parser.add_argument(
        "--max-chunk-chars",
        type=int,
        default=MAX_CHUNK_CHARS,
        help=f"单 chunk（单 sheet）最大字符数（默认 {MAX_CHUNK_CHARS}）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="并行调 LLM 的并发度（默认 4）",
    )
    parser.add_argument(
        "--requirement",
        type=str,
        help="用户的分析要求（会作为额外指令注入到 Reduce 阶段 user_prompt 顶部）",
    )
    parser.add_argument(
        "--no-intermediate-file",
        action="store_true",
        help="禁止落盘中间结果 JSON（默认落盘到 <excel同名>.intermediate.json）",
    )
    parser.add_argument(
        "--drop-empty-cols",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Excel → MD 时删除整列全空的列（默认开启）。"
             "宽矩阵型 Excel"
             "加上此开关可避免单行渲染出数十 K 字符的空 padding，"
             "大幅减少 chunk 数与 LLM 输入 token。仅删除全空列，零数据丢失。"
             "如需保留全空列，传 --no-drop-empty-cols。",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="单次 LLM 调用的超时（秒，默认 600）",
    )
    args = parser.parse_args()

    excel_path = Path(args.excel).absolute()
    if not excel_path.is_file():
        print(f"❌ 错误: Excel 文件不存在: {excel_path}", flush=True)
        sys.exit(1)
    if excel_path.suffix.lower() not in (".xls", ".xlsx"):
        print(f"❌ 错误: 不支持的文件类型: {excel_path.suffix}（仅支持 .xls / .xlsx）", flush=True)
        sys.exit(1)

    # 1. Excel → Markdown
    print("=" * 60, flush=True)
    print("📊 标书通读与方案提炼（Map-Reduce 版）", flush=True)
    print("=" * 60, flush=True)
    md_path = excel_to_markdown_file(excel_path, drop_empty_cols=args.drop_empty_cols)

    # 2. 读取 md
    md_text = md_path.read_text(encoding="utf-8").strip()
    if not md_text:
        print("❌ 错误: Markdown 内容为空，无法进行大模型分析", flush=True)
        sys.exit(1)

    # 3. 按 sheet 切分（单 sheet 超大时空行兜底）
    chunks = chunk_md_by_sheet(md_text, max_chunk_chars=args.max_chunk_chars)
    if not chunks:
        print("❌ 错误: 未能从 md 中切分出任何 chunk", flush=True)
        sys.exit(1)
    oversize_count = sum(1 for c in chunks if c["oversize"])
    print(
        f"📦 切分为 {len(chunks)} 个 chunk（其中 {oversize_count} 个为超大 sheet 的二次切分子块）",
        flush=True,
    )
    sheets_set = {c["sheet_name"].split("（")[0] for c in chunks}
    print(f"   涉及 sheet（共 {len(sheets_set)} 个）：{', '.join(list(sheets_set)[:10])}{'...' if len(sheets_set) > 10 else ''}", flush=True)
    # 影响结果的异常：超大 sheet 会被二次切分，单一 LLM 上下文只能看到碎片，
    # 分析的连贯性可能会下降。这里显式列出被拆开的 sheet 名，避免用户以为"全标书通读"。
    if oversize_count > 0:
        oversize_sheets = sorted({
            c["sheet_name"].split("（")[0] for c in chunks if c["oversize"]
        })
        print(
            f"\n⚠️  警告: 以下 {len(oversize_sheets)} 个超大 sheet 被二次切分，"
            "LLM 只会按段落/片段分别看，可能丢失跨段上下文：",
            flush=True,
        )
        for s in oversize_sheets:
            print(f"      · {s}", flush=True)
        print(
            "   如需全文通读，请调大 --max-chunk-chars 后重试；"
            "或考虑先用 Excel 拆分工具把超大 sheet 拆成多份。",
            flush=True,
        )

    # 4. 准备 LLM 配置
    llm_config = get_llm_config()
    if not llm_config or not llm_config.get("base_url") or not llm_config.get("api_key"):
        print(
            "❌ 错误: 无法读取 LLM 配置——请在 data/.env 中配置 OPENAI_BASE_URL/"
            "OPENAI_API_KEY/OPENAI_MODEL（未配时将回退会话继承的 ANTHROPIC_*）后重试。",
            flush=True,
        )
        sys.exit(1)

    # 5. Map 阶段：并发分析所有 chunk
    print(
        f"\n🤖 并行分析中（concurrency={args.concurrency}），共 {len(chunks)} 个 chunk...",
        flush=True,
    )
    map_t0 = time.time()
    chunk_results = asyncio.run(
        analyze_chunks_parallel(
            llm_config,
            chunks,
            concurrency=args.concurrency,
            timeout=args.timeout,
        )
    )
    map_elapsed = time.time() - map_t0

    # 6. 落盘中间结果（默认开，可用 --no-intermediate-file 关闭）
    intermediate_path = md_path.with_name(md_path.stem + ".intermediate.json")
    if not args.no_intermediate_file:
        try:
            intermediate_path.write_text(
                json.dumps(chunk_results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"💾 中间结果已落盘: {intermediate_path.name}（{len(chunk_results)} 条）", flush=True)
        except Exception as e:
            print(f"⚠️  中间结果落盘失败: {e}", flush=True)

    # 7. 合并
    print("\n🔗 合并各 chunk 中间结果...", flush=True)
    merged_summary = merge_intermediates(chunk_results)
    total = len(merged_summary["sheet_names"])
    ok = len(merged_summary["successful_sheets"])
    fail = len(merged_summary["failed_sheets"])
    print(f"   成功 {ok}/{total} 个 chunk，失败 {fail} 个", flush=True)
    if merged_summary["failed_sheets"]:
        for f in merged_summary["failed_sheets"]:
            print(f"      · {f}", flush=True)

    # 影响结果的异常：任何 chunk 失败都必须立刻终止，**不允许**给出
    # "看似完整但失败 sheet 内容缺失"的假报告——哪怕只失败 1 个 sheet，
    # 用户也可能因为看到 8 段报告齐全而误以为"全部成功"。
    if total > 0 and fail > 0:
        if ok == 0:
            print(
                f"\n❌ 标书分析失败: {total}/{total} 个 chunk 全部失败，"
                "没有任何 sheet 被成功解析。",
                flush=True,
            )
        else:
            print(
                f"\n❌ 标书分析失败: {total} 个 chunk 中 {fail} 个解析失败"
                f"（{ok} 个成功）。失败 sheet 列表：",
                flush=True,
            )
            for f in merged_summary["failed_sheets"]:
                print(f"      · {f}", flush=True)
        print(
            "❌ 当前技能已立刻终止；请排查失败的 sheet（网络 / LLM 配置 /"
            " 该 sheet 内容格式）后重试。",
            flush=True,
        )
        sys.exit(1)

    # 8. Reduce 阶段：最终汇总
    user_requirement = args.requirement.strip() if args.requirement else ""
    if user_requirement:
        print(f"📌 已应用用户分析要求（{len(user_requirement)} 字符）", flush=True)
    print(f"\n📝 调用大模型汇总（输入聚合 JSON，约 {len(json.dumps(merged_summary['merged'], ensure_ascii=False))} 字符）...", flush=True)

    try:
        final_text = asyncio.run(
            final_summary(
                llm_config,
                merged_summary,
                total_chunks=len(chunks),
                user_requirement=user_requirement,
                timeout=max(args.timeout, 900),
            )
        )
    except Exception as e:
        print(f"❌ 最终汇总失败: {e}", flush=True)
        sys.exit(1)

    if not final_text or not final_text.strip():
        print("❌ 错误: 大模型返回内容为空", flush=True)
        sys.exit(1)

    # 9. 输出结果
    total_elapsed = time.time() - map_t0
    print("\n" + "=" * 60, flush=True)
    print("📋 分析结果", flush=True)
    print("=" * 60 + "\n", flush=True)
    # 用 HTML 注释把 8 段报告包起来，避免 agent 改写/合并/简化
    final_text_with_markers = (
        _ANALYSIS_PRESERVATION_RULES
        + "<!--ANALYSIS-REPORT-START-->\n"
        + "<!-- ⚠️ 标书分析报告：8 段结构保留区，agent 严禁改写/合并/删除/重排 -->\n"
        + final_text.rstrip() + "\n"
        + "<!--ANALYSIS-REPORT-END-->\n"
    )
    print(final_text_with_markers, flush=True)
    print("\n" + "=" * 60, flush=True)
    print("✅ 分析完成。", flush=True)
    print(f"   - Markdown: {md_path}", flush=True)
    if not args.no_intermediate_file:
        print(f"   - 中间 JSON: {intermediate_path}", flush=True)
    print(f"   - Map 阶段耗时: {map_elapsed:.1f}s（共 {len(chunks)} 个 chunk，{args.concurrency} 并发）", flush=True)
    print(f"   - 总耗时（含 Reduce）: {total_elapsed:.1f}s", flush=True)
    print("=" * 60, flush=True)


if __name__ == '__main__':
    _force_utf8_stdout()
    main()
