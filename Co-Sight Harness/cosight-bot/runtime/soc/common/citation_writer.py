#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享引文模块。

从 retrieve.py 的 _save_citations / _stage_source_files 抽取。

被 semantic-search 和 soc-single-responder-skill 共用。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

# 源 .md 文件暂存子目录名
SOURCES_SUBDIR = "sources"


def _quote_url_path(rel_posix: str) -> str:
    """把 POSIX 相对路径转成可安全放进 markdown 链接的 URL 路径。

    源文件名可能含空格 / 中文 / 全角括号（真实事故：团队知识库
    "SJ-...-某设备（V7.26.20）网络通信端口表" 的暂存 URL 带裸空格，
    CommonMark 不允许链接目标含未编码空格，UI 渲染器解析失败会把
    [title](url) 整体显示成原文）。percent-encode 一切非 ASCII / 空格，
    保留 "/" 分隔符；引文 viewer 侧会 decodeURIComponent
    回真实文件名再落盘查找，端到端等价。
    """
    return quote(rel_posix, safe="/")


def _default_state_root() -> Path:
    """数据根目录（<workdir>/data，统一委托 port_resolver）。"""
    from common.port_resolver import cosight_state_root
    return cosight_state_root()


def _resolve_file_mtime(metadata: dict, file_path: str = "") -> str:
    """三级回退获取 file_mtime：last_modified_date → file_mtime → st_mtime"""
    f_mtime = metadata.get("last_modified_date", "") or metadata.get("file_mtime", "")
    if f_mtime:
        return f_mtime
    fp = file_path or metadata.get("file_path", "")
    if fp and Path(fp).is_file():
        try:
            return _dt.datetime.fromtimestamp(Path(fp).stat().st_mtime).strftime("%Y-%m-%d")
        except OSError:
            return ""
    return ""


# =====================================================================
# 源文件暂存
# =====================================================================

# 匹配 .md 文件开头的 YAML front matter 块:
#   ---
#   key: value
#   ...
#   ---
# 设计要点:
#   - \A: 必须从文件开头开始,避免误伤正文里的 "---" 水平分隔线
#   - 非贪婪 .*?: 防止多对 "---" 时吃掉中间所有内容
#   - re.DOTALL: 让 "." 匹配换行(front matter 是多行块)
#   - 容忍 CRLF / LF(Windows 源是 \r\n,Linux 是 \n)
#   - 仅在源文件以 "---" 开头时才命中,普通 .md 不受影响
_YAML_FRONTMATTER_RE = re.compile(
    r'\A---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)',
    re.DOTALL,
)


def _strip_yaml_frontmatter(content: str) -> str:
    """
    剥离 .md 文件开头的 YAML front matter 块(若存在)。

    使用场景: 部分来源的页面文档会带元数据头
    (source / author / fetched_at / ...),
    这些元数据对检索和追溯有用,但不应该被最终用户看到 —— 用户点开
    canvas/deep-search/<agent>/<msg>/sources/ 下的源文件链接时,只需要
    看到页面正文。

    关键约束:
      - 只在文件以 "---" 开头时才尝试剥离,普通 .md 不会被误伤
      - 剥离后 lstrip 掉开头空行,保证用户看到的第一行就是正文标题
      - 原文件不被修改,只在写到 staged 副本时剥除
    """
    if not content:
        return content
    m = _YAML_FRONTMATTER_RE.match(content)
    if not m:
        return content
    stripped = content[m.end():]
    # 剥离后可能留下开头空行,清掉,保证用户看到的第一行就是正文标题
    return stripped.lstrip('\r\n')


def stage_source_files(
    agent_id: str,
    msg_sn: str,
    source_nodes: list,
    *,
    state_root: Optional[Path] = None,
    pre_dirs: Optional[List[Path]] = None,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    把 source_nodes 中每个唯一的源 .md 文件复制到
    <state_root>/canvas/deep-search/<agent_id>/<msg_sn>/sources/<sha1前8位>_<basename>.md,
    返回 (source_url_map, assets_url_map) 两份映射。

    Args:
      - source_url_map: {绝对源路径: "file://<state_root>/canvas/.../sources/<name>.md"}。
        引文 URL 一律为 file:// 本地文件 URL（无 canvas host）。
      - assets_url_map: {绝对源路径: "file://<state_root>/canvas/.../sources/<h>_assets"}。
        仅当源 .md 旁边存在 assets/ 子目录并被一起暂存时填入,否则为空串。
        save_citations 据此改写引文 Content 段里的 assets/X 相对路径,
        让详情面板里的 <img> 也能在引文 viewer
        上下文解析到暂存的图片文件(否则浏览器会按引文 HTML 的
        相对路径解析,落到不存在的 assets/X → 全 404)。

    设计要点:
      - 源 .md 文件位于 canvas 根目录之外(workspace-{agent_id}/llamaindex_data/pre-processed/...),
        canvas host 的 resolveFileWithinRoot 会 404。复制到 canvas 子目录后现有路由能直接服务。
      - 每次重跑时清空 sources/,避免跨会话遗留过期副本。
      - 同名文件用源路径的 SHA-1 前 8 位前缀保证唯一(不同子目录下的同名 .md 不冲突)。
      - 源文件不是 .md 或复制失败时,URL 映射为空串 — 调用方据此跳过超链。
      - 本地资料(workspace-bound)和会话级资料(session-level)都要产生链接。
        当 metadata.file_path 失效(例如用户清理了 pre-processed、wiki 页面
        被删除但 lancedb 仍残留向量)时,会按 pre_dirs 顺序回退查找:
          1. <pre_dir>/<basename>
          2. <pre_dir>/<stem>_<ext>.md   (wiki / 上传时的预处理命名约定)
        找到则用回退到的真实 .md 复制,但 URL 映射键仍是 metadata 里的 file_path,
        保证引文统计能命中该条目。
      - assets/ 子目录用 <sha1前8位>_assets/ 命名空间,避免同一次 stage 调用里
        多源 .md 的 assets/ 互相覆盖。
    """
    if state_root is None:
        state_root = _default_state_root()
    sources_dir = state_root / "canvas" / "deep-search" / agent_id / msg_sn / SOURCES_SUBDIR
    sources_dir.mkdir(parents=True, exist_ok=True)

    # 清空旧的暂存副本,避免跨会话残留
    try:
        for old in sources_dir.iterdir():
            if old.is_file():
                old.unlink()
    except Exception as e:
        logger.warning(f"[StageSources] failed to clean {sources_dir}: {e}")

    pre_dirs = [pd for pd in (pre_dirs or []) if pd]

    def _resolve_existing_md(src_p: Path) -> Optional[Path]:
        """若 src_p 不在磁盘上,按 pre_dirs 顺序回退查找真实 .md。

        命名约定参考 watch_dog/file_watcher/handler.py 的 _update_for_event:
            md_name = f"{stem}_{suffix.lstrip('.')}".replace(".", "_") + ".md"
        即对 .tar.gz 这种多后缀文件名,会先把 stem 内的 '.' 替换成 '_' 再拼接。
        """
        if src_p.is_file():
            return src_p
        if not pre_dirs:
            return None
        stem = src_p.stem
        ext = src_p.suffix.lstrip('.')
        for pd in pre_dirs:
            try:
                if not pd.is_dir():
                    continue
            except OSError:
                continue
            # 1. 直接按 basename 匹配(适用于本地资料已复制到 pre-processed 的场景)
            cand1 = pd / src_p.name
            if cand1.is_file():
                return cand1
            # 2. wiki / 上传预处理命名约定:<stem>_<ext>.md
            #    stem 内嵌的 '.' 也要替换成 '_',例如 .tar.gz → archive_tar_gz.md
            if stem and ext:
                md_name = f"{stem}_{ext}".replace(".", "_") + ".md"
                cand2 = pd / md_name
                if cand2.is_file():
                    return cand2
            # 3. 兼容 .md / .markdown 的同名变体
            for alt_ext in (".md", ".markdown"):
                if alt_ext == src_p.suffix.lower():
                    continue
                cand3 = pd / f"{stem}{alt_ext}"
                if cand3.is_file():
                    return cand3
        return None

    mapping: Dict[str, str] = {}
    assets_map: Dict[str, str] = {}
    seen: set = set()

    for nws in source_nodes:
        meta = nws.node.metadata or {}
        src_abs = (meta.get("file_path", "") or "").strip()
        if not src_abs or src_abs in seen:
            continue
        seen.add(src_abs)

        if not src_abs.lower().endswith(".md"):
            mapping[src_abs] = ""
            assets_map[src_abs] = ""
            continue
        src_p = Path(src_abs)
        resolved = _resolve_existing_md(src_p)
        if resolved is None:
            logger.warning(
                f"[StageSources] source missing and no fallback found, skip link: {src_abs} "
                f"(pre_dirs={[str(p) for p in pre_dirs]})"
            )
            mapping[src_abs] = ""
            assets_map[src_abs] = ""
            continue
        # 用 metadata 路径的 sha1 前缀保证 URL 稳定;
        # 真实拷贝源可以来自回退路径(原文件已删除但 pre-processed 副本存在)。
        h = hashlib.sha1(src_abs.encode("utf-8")).hexdigest()[:8]
        staged_name = f"{h}_{resolved.name}"
        staged_path = sources_dir / staged_name
        # ── 处理附带 assets/ 子目录的源文件（网页抓取类 markdown） ──
        # 网页类来源把图片下载到 <page_dir>/assets/,在生成的
        # .md 里用相对路径 ![](assets/img_xxx.png) 引用。仅复制 .md 时,
        # 用户在画布点开文档链接后图片全部 404。这里把 assets/ 一起暂存
        # 到 sources/<h>_assets/(用 sha1 前缀命名空间避免多源冲突),
        # 并把 .md 里的 assets/X 引用重写为 <h>_assets/X,这样
        # 浏览器从 sources/<h>_<basename>.md 加载时,相对路径
        # <h>_assets/img_xxx.png 会解析到 sources/<h>_assets/img_xxx.png,
        # 引文 viewer 的文件路由能直接服务。
        assets_namespace = None
        try:
            src_assets = resolved.parent / "assets"
            if src_assets.is_dir():
                dst_assets = sources_dir / f"{h}_assets"
                try:
                    if dst_assets.exists():
                        shutil.rmtree(dst_assets)
                    shutil.copytree(src_assets, dst_assets)
                    assets_namespace = f"{h}_assets"
                except Exception as e:
                    logger.warning(
                        f"[StageSources] copytree assets failed for {src_assets}: {e}"
                    )
                    assets_namespace = None
        except OSError:
            assets_namespace = None

        try:
            # 拷贝时剥离 .md 顶部的 YAML front matter — 网页抓取类来源
            # 拉取的页面会带数行元数据头(source / author /
            # fetched_at ...),这些对检索 / 追溯有用,但不应该被
            # 最终用户看到 —— 用户点开 sources/ 链接看的是页面正文,元数据头
            # 只会造成困惑("这是什么?")。所以只在 staged 副本上剥除,
            # 不动 pre-processed / pre_dirs 里的原文件,保证检索侧元数据完整。
            #
            # 同时若本源带 assets/ 子目录,会把正文中相对路径
            # assets/X 重写为 <h>_assets/X,使其指向刚才 copytree 的暂存目录。
            #
            # 流程设计:
            #   1. shutil.copy2 先把 mtime / 权限等元数据复制过来
            #      —— 保留原文件的"修改时间"信息,方便外部按 mtime 排查
            #   2. 再读出 staged 副本,剥除 frontmatter,仅当确有 frontmatter
            #      时才覆盖写 —— 避免对普通 .md 做无谓 IO
            #   3. 用二进制读写,避免 "w" 文本模式把 \n 替换为 \r\n
            #      (同 save_citations 里提到的 \r\n → \r\r\n 坑)
            #   4. 非 utf-8 源文件(极小概率)保持 copy2 的原样结果,不动
            #   5. 读 resolved 而不是 src_p —— 真实存在的文件是 resolved
            #      (可能来自 pre_dirs 回退,src_p 本身可能已不存在)
            #   6. assets/ 重写 + frontmatter 剥除 合在一次"写回"里完成,
            #      用 final_text != text 判定是否需要 IO
            shutil.copy2(resolved, staged_path)
            with open(staged_path, "rb") as f:
                raw = f.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                # 非 utf-8 源,保持 copy2 的原样结果
                pass
            else:
                stripped = _strip_yaml_frontmatter(text)
                final_text = stripped
                if assets_namespace:
                    # 仅在源 markdown 里出现的 assets/ 相对路径才重写,避免误伤
                    # 正文里偶然出现的 "assets" 字面量(例如某个英文段落)。
                    # Pattern 1: 标准 markdown 图片/链接 ![alt](assets/X) / [text](assets/X)
                    final_text = re.sub(
                        r'(?<=\]\()assets/([^)\s"]+)',
                        rf'{assets_namespace}/\1',
                        final_text,
                    )
                    # Pattern 2: 内联 HTML <img src="assets/X" />
                    final_text = re.sub(
                        r'(?<=src=")assets/([^"\s]+)',
                        rf'{assets_namespace}/\1',
                        final_text,
                    )
                if final_text != text:  # 有 frontmatter 或 assets 重写时才覆盖写
                    with open(staged_path, "wb") as f:
                        f.write(final_text.encode("utf-8"))
        except Exception as e:
            logger.warning(f"[StageSources] copy failed for {src_abs} (resolved={resolved}): {e}")
            mapping[src_abs] = ""
            assets_map[src_abs] = ""
            continue
        # 引文 URL 用 file:// 本地文件 URL（无 canvas host）
        mapping[src_abs] = staged_path.resolve().as_uri()
        # assets 目录 URL(暂存过的源才有值):save_citations 据此把
        # 引文正文里的 assets/X 相对路径改写为绝对 URL,保证 hover tooltip /
        # 详情面板里的 <img> 在引文 viewer(citations/
        # <i>.md)两个上下文都能解析到暂存的图片。
        if assets_namespace:
            assets_map[src_abs] = (sources_dir / f"{h}_assets").resolve().as_uri()
        else:
            assets_map[src_abs] = ""
    return mapping, assets_map


# =====================================================================
# 引文文件保存
# =====================================================================


# KB 构建产物目录的稳定锚点。spec metadata.file_path / paradigm metadata.source_path
# 都是构建机当时的绝对路径，盘符与上级目录（状态根、机器名）随构建机而变，
# 只有锚点之后的路径（KB 内相对路径）对任何机器上的用户都有定位意义。
_KB_PATH_ANCHORS: Tuple[str, ...] = (
    "pd_spec_vector_library/",      # spec:  .../builds/<kb>/pre-processed/pd_spec_vector_library/<rel>
    "historical_paradigms/",        # paradigm 预处理产物（若构建机直存该目录）
    "builder/sources/",            # paradigm: .../workspace-soc/builder/sources/<kb_id>/<rel>（跳过 kb_id 段）
)


def _kb_relative_path(fp: str) -> str:
    """把构建机绝对路径裁剪为 KB 内相对路径；识别不到锚点时原样返回。

    例：
      D:/.../builds/support_sub_xxx/pre-processed/pd_spec_vector_library/A/B/c.md
        → A/B/c.md
      D:/.../workspace-soc/builder/sources/team_xxx/02_Historical_Responses/xx.xlsx
        → 02_Historical_Responses/xx.xlsx
    """
    norm = (fp or "").replace("\\", "/")
    for anchor in _KB_PATH_ANCHORS:
        idx = norm.find(anchor)
        if idx < 0:
            continue
        rest = norm[idx + len(anchor):]
        if anchor == "builder/sources/":
            # 锚点后第一段是 KB 目录（sources/<kb_id>/<rel>），跳过
            rest = rest.split("/", 1)[1] if "/" in rest else rest
        return rest
    return fp


def save_citations(
    agent_id: str,
    msg_sn: str,
    query: str,
    source_nodes: list,
    *,
    source_url_map: Optional[Dict[str, str]] = None,
    assets_url_map: Optional[Dict[str, str]] = None,
    state_root: Optional[Path] = None,
    hide_file_path: bool = False,
) -> List[str]:
    """
    将召回节点保存为引文文件 (canvas/deep-search/<agent>/<msg>/citations/<i>.md)。

    Args:
        source_url_map: 可选映射 {绝对源路径: 暂存URL}。当传入时，引文 .md 文件
                        的 `**file_path**:` 行会被写成 markdown 链接。
        assets_url_map: 可选映射 {绝对源路径: assets 暂存目录 URL}。当传入且
                        非空时,引文 # Content 段里的 assets/X 相对路径会被
                        改写为 <assets_url>/X 绝对 URL。这样:
                          - 引文 viewer 渲染 citations/<i>.md 时,marked 生成的
                            <img src="..."> 是绝对 URL,浏览器按网关解析。
                          - 点击详情面板也是从 citations/<i>.md 的 Content 段
                            取出 content_preview 再交给 marked 渲染,绝对 URL
                            在引文 HTML 这个上下文也仍然能解析到暂存的图片
                            (不再相对 assets/X → 404)。
                        没有 assets/ 的源(空串)→ 不重写,正文里出现
                        assets/ 字面量也不会被误伤。
        hide_file_path: 是否在 # Metadata 段跳过 file_path 字段。
                        背景:知识库的 lancedb 可能由其他机器构建后拷贝过来,
                        metadata.file_path 字段保存的是构建机当时的绝对路径
                        (例如 `D:/work/bot/.../pre-processed/.../xx.md`),
                        与当前部署机的真实路径不匹配 —— stage_source_files
                        在 source_url_map 拿不到该路径时,会把 file_path 当纯文本
                        写在 # Metadata 段,既不可点击又指向一个用户本机不存在的
                        路径,造成"参考文档点开链接显示的完整路径在本地找不到"
                        的体验问题。
                        现行为:无链接兜底分支会经 _kb_relative_path 裁剪为
                        KB 内相对路径(如 `Support官方产品文档/.../xx.md`),
                        已不存在误导性,传 False 展示相对路径即可;
                        仍保留 True 选项彻底跳过该字段。
                        默认 False 保持其它 agent 行为不变。
    """
    if not msg_sn or not agent_id:
        return []

    if state_root is None:
        state_root = _default_state_root()
    citation_dir = state_root / "canvas" / "deep-search" / agent_id / msg_sn / "citations"
    citation_dir.mkdir(parents=True, exist_ok=True)

    citation_paths = []
    for i, node in enumerate(source_nodes, 1):
        content = node.node.get_content()
        metadata = dict(node.node.metadata or {})
        score = getattr(node, "score", 0.0)
        vector_score = metadata.pop('vector_score', None)

        start_char_idx = getattr(node.node, 'start_char_idx', None)
        if start_char_idx is not None:
            metadata['start_char_idx'] = start_char_idx

        # ── 1. 剥 chunk 内容顶部的 YAML frontmatter ──
        # chunk 来自 lancedb,索引自网页抓取类来源写出的 .md,
        # 顶部带数行元数据头(source / author / fetched_at / ...)。
        # stage_source_files 在写到 sources/<h>_<basename>.md 时已经
        # 剥过一次(_strip_yaml_frontmatter),但 chunk 是从 vector DB
        # 取的,这里是它进 citations/<i>.md # Content 段的第一道关。
        # 不在这里剥的话,用户看 citations viewer 或 hover tooltip /
        # 详情面板时,顶部会被 marked 渲染成一段元数据列表,
        # 等于 commit c0253378a 的"去头部无用 wiki 页面信息"
        # 在 citations 路径上失效。
        if content:
            content = _strip_yaml_frontmatter(content)

        # ── 2. 把 chunk 正文里的 assets/X 相对引用改写为暂存目录绝对 URL ──
        # 触发条件:本 chunk 的来源 .md 在 stage_source_files 时确实把
        # assets/ 一起暂存了(assets_url_map[file_path] 非空)。
        # 用绝对 URL 而非相对 URL,是因为这段 content 同时被
        # 消费方：citations/<i>.md 引文 viewer（markdown 渲染）。
        # viewer 页面的"当前 URL"与 canvas 资源的相对位置不同,
        # 绝对 URL 不依赖 base URL,在两处都能解析到 canvas/
        # deep-search/<agent>/<msg>/sources/<h>_assets/X（file:// URL）。
        _fp = (metadata.get("file_path", "") or "").strip()
        _assets_url = (assets_url_map or {}).get(_fp, "") if _fp else ""
        if _assets_url and content:
            content = re.sub(
                r'(?<=\]\()assets/([^)\s"]+)',
                rf'{_assets_url}/\1',
                content,
            )
            content = re.sub(
                r'(?<=src=")assets/([^"\s]+)',
                rf'{_assets_url}/\1',
                content,
            )

        # 构造 Markdown 格式的引文内容
        md_lines = [
            f"# Citation [{i}]",
            f"**Query**: {query}",
            f"- **Score**: {score:.4f}"
        ]
        if vector_score is not None:
            md_lines.append(f"- **Vector Score (原始)**: {float(vector_score):.4f}")
        md_lines.append(f"- **LLM Relevance**: {score:.4f}")
        if "file_name" in metadata:
            md_lines.append(f"- **Source File**: {metadata['file_name']}")

        # 资料修改时间：last_modified_date → file_mtime → st_mtime
        file_mtime = _resolve_file_mtime(metadata)
        if file_mtime:
            md_lines.append(f"- **Last Modified**: {file_mtime}")

        md_lines.append("\n# Content")
        
        # 检测并修复 Excel 内容（如果内容来自 xlsx 文件）
        file_name = metadata.get("file_name", "")
        chapter_title = metadata.get("chapter_title", "")
        
        if file_name.endswith(("_xlsx.md", "_xls.md")):
            # 检查内容是否包含混乱的文本（如 \\n 字面量）
            if "\\n" in content:
                # 将 \\n 替换为实际换行符
                content = content.replace("\\n", "\n")
            
            # 检查内容是否包含 | 分隔符（Markdown 表格特征）
            if "|" in content:
                lines = content.split("\n")
                # 过滤掉空行
                non_empty_lines = [line for line in lines if line.strip()]
                
                if non_empty_lines:
                    # 查找第一个包含多个 | 的行（可能是表头）
                    header_idx = -1
                    for idx, line in enumerate(non_empty_lines):
                        if line.count("|") >= 3:
                            header_idx = idx
                            break
                    
                    if header_idx >= 0:
                        # 找到了表头行，检查是否有分隔线
                        has_separator = False
                        if header_idx + 1 < len(non_empty_lines):
                            second_line = non_empty_lines[header_idx + 1]
                            # 检查第二行是否是分隔线（包含 --- 和 |）
                            if "---" in second_line and "|" in second_line:
                                has_separator = True
                        
                        # 如果没有分隔线，添加一个
                        if not has_separator:
                            # 计算列数
                            col_count = non_empty_lines[header_idx].count("|") - 1
                            separator = "|" + "---|" * col_count
                            # 在表头行后插入分隔线
                            non_empty_lines.insert(header_idx + 1, separator)
                        
                        # 如果表头前面有非表格内容，将其删除或移到表格后面
                        if header_idx > 0:
                            # 将表头前的内容移到表格后面
                            non_table_lines = non_empty_lines[:header_idx]
                            table_lines = non_empty_lines[header_idx:]
                            # 重新组合：表格在前，其他内容在后
                            non_empty_lines = table_lines + [""] + non_table_lines
                        
                        content = "\n".join(non_empty_lines)
            
            # 如果内容仍然不包含表头，尝试从原始 Excel 文件中提取表头
            # 这里我们假设表头已经在预处理时被正确生成
            # 如果没有，我们需要在切片时保留表头
                
        md_lines.append(content)

        md_lines.append("\n# Metadata")
        for k, v in metadata.items():
            # 时间字段已在头部展示，跳过避免重复
            if k in ("file_mtime", "last_modified_date", "creation_date"):
                continue
            if k == "file_path":
                # hide_file_path=True 时彻底跳过;False 时:
                #   - source_url_map 命中 → 写成可点击链接(键保持绝对路径,
                #     引文解析时会剥回绝对路径查 source_url_map)
                #   - 未命中 → 裁剪为 KB 内相对路径展示(SOC 场景:构建机绝对路径
                #     在本机不存在,相对路径才有定位意义)
                if hide_file_path:
                    continue
                if v and source_url_map and source_url_map.get(v):
                    md_lines.append(f"- **file_path**: [{v}]({source_url_map[v]})")
                else:
                    md_lines.append(f"- **{k}**: {_kb_relative_path(str(v))}")
                continue
            md_lines.append(f"- **{k}**: {v}")

        md_content = "\n".join(md_lines)
        filepath = citation_dir / f"{i}.md"

        # 行尾归一 + 二进制写入(防止 Windows 文本模式把 \r\n 写成 \r\r\n)
        # 源 markdown 文件(LanceDB 里的 content)是 Windows 格式 (\r\n),
        # 若用 "w" 文本模式写入,Python 会把 \n 替换为 \r\n,导致 \r\n → \r\r\n。
        # 下游按文本读取时 universal newlines 会把 \r\r\n 翻译成
        # 2 个 \n,GFM 表格解析器看到表格行之间多了空行,就退化成 <p>|...|</p>。
        md_content = md_content.replace("\r\n", "\n").replace("\r", "\n")

        try:
            with open(filepath, "wb") as f:
                f.write(md_content.encode("utf-8"))
            citation_paths.append(str(filepath))
            logger.debug(f"已保存引文文本到文件: {filepath}")
        except Exception as e:
            logger.error(f"保存引文信息失败: {e}")

    return citation_paths


def save_merged_paradigm_citations(
    agent_id: str,
    msg_sn: str,
    source_nodes: list,
    *,
    state_root: Optional[Path] = None,
) -> Dict[str, str]:
    """
    对历史范式（_source_kind=paradigm）按 file_path 分组，每个文件写一个
    citations/paradigm_{hash}.md，包含该文件所有 chunk 的内容拼接 + 元数据。

    背景：
      - stage_source_files 只暂存 .md，paradigm 的源文件是 .xlsx，永进不了 staging。
      - save_citations 按 chunk 写 citations/N.md，N 段 paradigm → N 个 .md，
        用户看参考列表点进去只能看到单段内容。
      - 本函数把同一 paradigm 文件的多段合并成 1 个 .md，给"参考文档"列表用，
        让用户点进去看到该文件所有被引用的段。

    仅在 file 有 >= 2 段 paradigm chunk 时生成合并文件（单段走 save_citations
    写出的 citations/{idx}.md 即可，不重复写）。

    Returns:
        Dict[Tuple[str, str], str]: {(kb_id, file_path): file:// URL，
                          如 file://<state_root>/canvas/deep-search/<agent_id>/<msg_sn>/citations/paradigm_{hash}.md}
        无合并需求时返回空 dict。
    """
    if not msg_sn or not agent_id:
        return {}

    if state_root is None:
        state_root = _default_state_root()
    citation_dir = state_root / "canvas" / "deep-search" / agent_id / msg_sn / "citations"
    citation_dir.mkdir(parents=True, exist_ok=True)

    # 1. 按 (kb_id, source_path / source_file) 分组 paradigm chunks
    # 注：paradigm metadata 由 _search_paradigms 生成，没有 file_path 字段，
    # 只有 source_path（完整路径）、source_file（文件名）、file_name（同 source_file）。
    # 用 source_path 作 key 最精确，回退到 source_file 兼容缺字段的老数据。
    # v2 修复：多 KB 时 key 包含 kb_id，避免不同子库的同名 paradigm 文件混进同一个合并文件。
    by_file: Dict[Tuple[str, str], List[tuple]] = {}
    for i, nws in enumerate(source_nodes, 1):
        meta = (nws.node.metadata or {}) if hasattr(nws, "node") else {}
        if meta.get("_source_kind") != "paradigm":
            continue
        kb_id = (meta.get("kb_id", "") or "").strip()
        fp = (
            (meta.get("source_path", "") or "").strip()
            or (meta.get("source_file", "") or "").strip()
        )
        if not fp:
            continue
        by_file.setdefault((kb_id, fp), []).append((i, nws))

    mapping: Dict[Tuple[str, str], str] = {}
    for (kb_id, fp), items in by_file.items():
        if len(items) < 2:
            # 单段 paradigm：复用 save_citations 的 citations/{idx}.md，跳过
            continue

        h = hashlib.sha1(f"{kb_id}::{fp}".encode("utf-8")).hexdigest()[:8]
        merged_name = f"paradigm_{h}.md"
        merged_path = citation_dir / merged_name

        # 2. 拼接所有 chunks
        file_name = Path(fp).name
        md_lines: List[str] = [
            "# 历史范式合并引用",
            "",
            f"- **源文件**: `{file_name}`",
            f"- **相对路径**: `{_kb_relative_path(fp)}`",
            f"- **包含片段数**: {len(items)}",
            "",
            "---",
            "",
        ]

        for chunk_idx, nws in items:
            meta = nws.node.metadata or {}
            content = nws.node.get_content()
            score = getattr(nws, "score", 0.0)
            vector_score = meta.get("vector_score")
            comp = meta.get("compliance", "")
            remarks = meta.get("remarks", "")
            ref_doc = meta.get("reference_document", "")
            source_file = meta.get("source_file", "")
            created_at = meta.get("created_at", "")

            md_lines.append(f"## 片段 {chunk_idx}（引文编号 [{chunk_idx}]）")
            md_lines.append("")
            md_lines.append(f"- **LLM Relevance**: {float(score):.4f}")
            if vector_score is not None:
                md_lines.append(f"- **Vector Score（原始 cosine sim）**: {float(vector_score):.4f}")
            if comp:
                md_lines.append(f"- **历史合规**: {comp}")
            if remarks:
                md_lines.append(f"- **历史备注**: {remarks}")
            if ref_doc:
                md_lines.append(f"- **参考文档**: {ref_doc}")
            if source_file:
                md_lines.append(f"- **Source File**: {source_file}")
            if created_at:
                md_lines.append(f"- **入库时间**: {created_at}")
            md_lines.append("")
            md_lines.append("### 内容")
            md_lines.append("")
            md_lines.append(content)
            md_lines.append("")
            md_lines.append("---")
            md_lines.append("")

        md_content = "\n".join(md_lines)
        # 行尾归一（防 Windows 文本模式 \r\n 坑，与 save_citations 保持一致）
        md_content = md_content.replace("\r\n", "\n").replace("\r", "\n")

        try:
            with open(merged_path, "wb") as f:
                f.write(md_content.encode("utf-8"))
            mapping[(kb_id, fp)] = merged_path.resolve().as_uri()
            logger.info(f"[SaveMergedParadigm] merged {len(items)} chunks for {file_name} → {merged_path}")
        except Exception as e:
            logger.error(f"[SaveMergedParadigm] failed to write {merged_path}: {e}")

    return mapping


def save_merged_spec_citations(
    agent_id: str,
    msg_sn: str,
    source_nodes: list,
    *,
    state_root: Optional[Path] = None,
) -> "Dict[Tuple[str, str, str], str]":
    """
    对产品规范（_source_kind=product_spec）按 (kb_id, file_path, section) 分组，
    每个文件+章节写一个 citations/spec_{hash}.md，包含该 section 所有 chunk 的内容拼接 + 元数据。

    背景：
      - stage_source_files 暂存的是整个 .md，参考文档链接打开看到的是全文（动辄几十页）。
      - 用户从"📚 参考文档"点进去只想看被引用章节的内容，不需要整个文档。
      - 本函数把同一 spec 文件+章节的多段合并成 1 个 .md，让用户点进去看到该 section
        内被检索到的所有 chunk。

    仅在某个 (file_path, section) 有 >= 2 段 spec chunk 时生成合并文件（单段走 save_citations
    写出的 citations/{idx}.md 即可，不重复写）。

    Returns:
        Dict[Tuple[str, str, str], str]: {(kb_id, file_path, section): file:// URL，
                                       如 file://<state_root>/canvas/deep-search/<agent_id>/<msg_sn>/citations/spec_{hash}.md}

    v2 修复：key 改为 (kb_id, file_path, section)，避免多 KB 同名同章节的文档
    被合并到同一个文件、造成参考链接内容混乱。
    """
    if not msg_sn or not agent_id:
        return {}

    if state_root is None:
        state_root = _default_state_root()
    citation_dir = state_root / "canvas" / "deep-search" / agent_id / msg_sn / "citations"
    citation_dir.mkdir(parents=True, exist_ok=True)

    # 1. 按 (kb_id, file_path, section) 分组 spec chunks
    # section 提取规则与 respond.py 的 _build_source_list_section 一致：
    #   - header_path 去掉首段（H1），剩下的多级用 " / " 拼接
    #   - 跳级标题时用 chapter_title 兜底
    # v2 修复：多 KB 时 key 包含 kb_id，避免不同子库的同名同章节文档混进同一个合并文件。
    by_section: "Dict[Tuple[str, str, str], List[tuple]]" = {}
    for i, nws in enumerate(source_nodes, 1):
        meta = (nws.node.metadata or {}) if hasattr(nws, "node") else {}
        if meta.get("_source_kind") != "product_spec":
            continue
        kb_id = (meta.get("kb_id", "") or "").strip()
        fp = (meta.get("file_path", "") or "").strip()
        if not fp:
            continue

        header_path = (meta.get("header_path", "") or "").replace("\n", " ").replace("\r", "").strip()
        chapter_title = (meta.get("chapter_title", "") or "").strip()
        parts: List[str] = []
        if header_path:
            parts = [
                p.strip().lstrip("#").strip()
                for p in header_path.split("/")
                if p.strip()
            ]
        section = ""
        if parts:
            chapter_parts = parts[1:]
            if chapter_parts:
                section = " / ".join(chapter_parts)
            elif chapter_title:
                _ct = chapter_title.lstrip("#").strip()
                if _ct and _ct != parts[0]:
                    section = _ct
        elif chapter_title:
            _ct = chapter_title.lstrip("#").strip()
            if _ct:
                section = _ct

        if not section:
            # 没有 section 信息的 spec chunk 不合并（避免把整个文件当章节展示）
            continue

        key = (kb_id, fp, section)
        by_section.setdefault(key, []).append((i, nws))

    mapping: "Dict[Tuple[str, str, str], str]" = {}
    for (kb_id, fp, section), items in by_section.items():
        if len(items) < 2:
            # 单段 spec：复用 save_citations 的 citations/{idx}.md，跳过
            continue

        h = hashlib.sha1(f"{kb_id}::{fp}::{section}".encode("utf-8")).hexdigest()[:8]
        merged_name = f"spec_{h}.md"
        merged_path = citation_dir / merged_name

        # 2. 拼接所有 chunks
        file_name = Path(fp).name
        md_lines: List[str] = [
            "# 产品规范合并引用",
            "",
            f"- **源文件**: `{file_name}`",
            f"- **相对路径**: `{_kb_relative_path(fp)}`",
            f"- **章节**: `{section}`",
            f"- **包含片段数**: {len(items)}",
            "",
            "---",
            "",
        ]

        for chunk_idx, nws in items:
            meta = nws.node.metadata or {}
            content = nws.node.get_content()
            score = getattr(nws, "score", 0.0)
            vector_score = meta.get("vector_score")
            file_mtime = meta.get("file_mtime", "")

            md_lines.append(f"## 片段 {chunk_idx}（引文编号 [{chunk_idx}]）")
            md_lines.append("")
            md_lines.append(f"- **LLM Relevance**: {float(score):.4f}")
            if vector_score is not None:
                md_lines.append(f"- **Vector Score**: {float(vector_score):.4f}")
            if file_mtime:
                md_lines.append(f"- **修改时间**: {file_mtime}")
            md_lines.append("")
            md_lines.append("### 内容")
            md_lines.append("")
            md_lines.append(content)
            md_lines.append("")
            md_lines.append("---")
            md_lines.append("")

        md_content = "\n".join(md_lines)
        md_content = md_content.replace("\r\n", "\n").replace("\r", "\n")

        try:
            with open(merged_path, "wb") as f:
                f.write(md_content.encode("utf-8"))
            mapping[(kb_id, fp, section)] = merged_path.resolve().as_uri()
            logger.info(f"[SaveMergedSpec] merged {len(items)} chunks for {file_name}::{section} → {merged_path}")
        except Exception as e:
            logger.error(f"[SaveMergedSpec] failed to write {merged_path}: {e}")

    return mapping
