"""自研 load_corpus_file：复用 parsing.parsers 解析器 + 自研定长切分器。

替代私有包 corpus.rag_corpus_parse.load_corpus_file，函数签名保持一致，输出
corpus_file.txt 的格式保持一致（每行 "page_content=... metadata=..."）。

设计说明（v1）：
- 解析：复用 parsing.parsers.strategies.FILE_PARSE_STRATEGIES（8 格式）。
- 切分：使用 parsing.splitter.SentenceChunkSplitter（段落→句子→定长+overlap）。
- 产物：每个切片生成一个 LCDocument，page_content 与 metadata['content_expand'] 均为切片全文
  （v1 简化，不再区分“检索短句 page_content / 完整上下文 content_expand”的双视图）。
"""
import gc
import logging
import os
import zipfile

from parsing.block_splitter import BlockChunkSplitter
from parsing.exception import ParseCorruptError, ParseEmptyError, UnsupportedFormatError
from parsing.sensitive import DefaultSensitiveWordChecker
from parsing.splitter import SentenceChunkSplitter
from parsing.common.create_doc import LCDocument
from parsing.parsers.strategies import FILE_PARSE_STRATEGIES


def load_corpus_file(input_path: str, output_path: str, chunk_size: int = 1024, chunk_overlap: int = 200,
                     sensitive_checker=None, min_chunk_size: int = 512, max_chunk_size: int = 2048):
    """解析并切分单个文件或目录，将切片写入 {output_path}/output/corpus_file.txt。

    min_chunk_size / max_chunk_size 保留在算子契约里；v1 定长切分器不使用它们。
    """
    if sensitive_checker is None:
        sensitive_checker = DefaultSensitiveWordChecker()
    try:
        output_path = os.path.join(output_path, 'output')
        os.makedirs(output_path, exist_ok=True)
        output_content_path = os.path.join(output_path, 'corpus_file.txt')
        if os.path.exists(output_content_path):
            os.remove(output_content_path)

        if os.path.isfile(input_path):
            process_single_file(input_path, output_content_path, chunk_size, chunk_overlap, sensitive_checker)
        elif os.path.isdir(input_path):
            for root, dirs, files in os.walk(input_path):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    process_single_file(file_path, output_content_path, chunk_size, chunk_overlap, sensitive_checker)
        else:
            raise FileNotFoundError(f"输入路径不存在或无效: {input_path}")

        gc.collect()
        return output_path
    except Exception as e:
        logging.exception(f"处理语料文件失败: {e}")
        raise


#: 「ZIP 包坏了」的异常特征。按**文本**判定而不是按异常类型：
#:   * python-docx / python-pptx 的 ``PackageNotFoundError`` —— "Package not found at '...'"
#:     （底层是 ``zipfile.is_zipfile`` 返回 False，没有稳定的公共基类跨两个库）；
#:   * openpyxl 等直接暴 ``zipfile.BadZipFile`` —— "File is not a zip file" /
#:     "Bad CRC-32 for file ..."（截断或数据损坏）。
#: 不在这里 import docx/pptx/openpyxl：沙箱子进程有内存配额，解析器必须懒加载。
_CORRUPT_PACKAGE_MARKERS = (
    'Package not found at',
    'not a zip file',
    'Bad CRC-32',
)


def _is_corrupt_package(error: Exception) -> bool:
    """解析器抛出的异常是否表示「文件本身不是完整的 ZIP/OOXML 包」。"""
    if isinstance(error, zipfile.BadZipFile):
        return True
    message = str(error)
    return any(marker in message for marker in _CORRUPT_PACKAGE_MARKERS)


def process_single_file(file_path: str, output_content_path: str, chunk_size: int,
                        chunk_overlap: int, sensitive_checker):
    doc_name = os.path.basename(file_path)
    source = os.path.splitext(doc_name)[1].lstrip('.')
    if source not in FILE_PARSE_STRATEGIES:
        # 以前是静默 return —— 下层不产出 corpus_file.txt，上层报「切分算子执行失败」，
        # 真实的「这个格式没人会解析」被完全盖住（OFD、压缩包等走这条）。
        logging.warning(f"不支持的格式: file={file_path}, format={source}")
        raise UnsupportedFormatError(file_path, source=source)
    # ⚠️ ``try`` **只包住解析**，且异常一律 ``raise`` 不吞：
    #    以前这里是 ``except Exception: logging.exception(...)`` —— 解析失败被吞掉，
    #    与「正文为空静默 return」合谋成同一个下游症状：不产出 corpus_file.txt，
    #    上层读文件报 FileNotFoundError → 对外 `RetCode.operator.split.error`
    #    （"切分算子执行失败"），真实原因只剩日志里一行。见 ParseEmptyError 的 docstring。
    try:
        # 1. 复用已有解析器：格式 -> LCDocument（metadata['content_expand'] 为段落全文）
        raw_docs = FILE_PARSE_STRATEGIES[source].process(file_path)
    except Exception as e:
        logging.exception(f"处理单个文件失败: {file_path}, 错误: {e}")
        if _is_corrupt_package(e):
            # 文件自身的问题（上传/打包时被截断），不是算子问题：给独立键，
            # 别落进「切分算子执行失败」让用户去查算子。
            raise ParseCorruptError(file_path, source=source, detail=str(e)) from e
        raise

    full_text = _reconstruct_text(raw_docs)
    if not str(full_text or '').strip():
        # 解析没抛错但没文本（JS 渲染页面只剩空壳 DOM、纯图片/扫描件、空白文件…）。
        # **必须抛**，不能静默 return —— 静默 return 正是本缺陷的原始形态。
        logging.warning(
            f"解析后正文为空: file={file_path}, format={source}, "
            f"raw_docs={len(raw_docs or [])}, output 未写出")
        raise ParseEmptyError(file_path, source=source,
                              detail=f'解析器返回 {len(raw_docs or [])} 条文档但正文为空')

    # 2. 敏感词检查（对全文做子串匹配）
    sensitive_checker.check_sensitive_word(full_text)

    # 3. 切分：有结构块就按块切（表格行不被切断、带章节路径），否则退回纯文本切分
    blocks = _collect_blocks(raw_docs, full_text)
    chunks = []
    if blocks:
        chunks = BlockChunkSplitter(max_word_count=chunk_size, overlap=chunk_overlap).split(blocks)
    if not chunks:
        splitter = SentenceChunkSplitter(max_word_count=chunk_size, overlap=chunk_overlap)
        chunks = splitter.split(full_text)

    if not chunks:
        # 兜底：``SentenceChunkSplitter`` 只在正文全为空白时返回空列表 —— 而那条
        # 路径已经被上面的 ``full_text.strip()`` 拦掉了，所以这里事实上不可达。
        # 刻意保留：当年这一支是「正文非空但被 ``SentenceValidator`` 全部挡掉」的
        # 出口（样本是 DOM 只剩「仪表盘」的 HTML 空壳），切分器改成不做过
        # 滤之后它才失效。留着是为了语义完整，不是为了当前能触发。
        logging.warning(
            f"切分后无有效句子: file={file_path}, format={source}, "
            f"full_text_len={len(full_text)}, output 未写出")
        raise ParseEmptyError(file_path, source=source,
                              detail=f'正文 {len(full_text)} 字符，但无一条句子可通过校验')

    # 4. 构造 LCDocument 并写出。``type`` 来自解析器：xlsx/csv 的每行是 QA 形态
    #    （``create_doc_by_content(..., is_qa=True)``），以前在 ``_build_document``
    #    里被硬编码成 0，QA 标记在落库前就丢了。
    chunk_type = _chunk_type(raw_docs)
    docs = [_build_document(chunk, doc_name, idx, chunk_type)
            for idx, chunk in enumerate(chunks, start=1)]
    write_txt(docs, output_content_path)


def _collect_blocks(raw_docs, full_text):
    """收集解析器给出的结构块（目前只有 docx 有）。

    兜底校验：块的文字总量明显少于全文时说明解析器没把正文写进块里，
    宁可退回纯文本切分，也不能悄悄丢内容。
    """
    blocks = []
    for doc in raw_docs or []:
        doc_blocks = getattr(doc, 'blocks', None)
        if doc_blocks:
            blocks.extend(doc_blocks)
    if not blocks:
        return []
    # 表格块与 full_text 的表格表示不可比：块里是单元格原文（``值1|说明1``），
    # full_text 走的是 ``MdTableTool`` 的 ``表头:值;`` 展开形式，同样一张表在两边
    # 长度能差 4 倍。有表格块时不做长度比 —— 否则一份表格为主的 markdown 会被
    # 误判成「块覆盖不足」并退回纯文本切分，表格行又会被 512 字切断。
    if any(block.get('kind') == 'table' for block in blocks):
        return blocks
    covered = sum(_block_text_length(block) for block in blocks)
    if covered < len(full_text or '') * 0.5:
        logging.warning(
            f"结构块覆盖不足，退回纯文本切分: blocks={len(blocks)}, "
            f"block_chars={covered}, full_chars={len(full_text or '')}")
        return []
    return blocks


def _block_text_length(block):
    kind = block.get('kind')
    if kind == 'table':
        title = block.get('title') or ''
        return len(title) + sum(len(cell) for row in block.get('rows') or [] for cell in row)
    return len(block.get('text') or '')


def _reconstruct_text(raw_docs):
    # 解析器（parsing.common.create_doc）采用「检索短句 page_content + 完整上下文
    # content_expand」双视图：同一段落的每个句子都会复制整段 content_expand，另加一个
    # 段落级 key。直接把所有 content_expand 拼接会把同一段落重复约 N 次（N=句子数）。
    # 这里按 content_expand 去重（保持首次出现顺序），还原文档唯一正文后再交给切分器。
    parts = []
    seen = set()
    for doc in raw_docs or []:
        content_expand = None
        page_content = None
        if hasattr(doc, 'metadata') and doc.metadata:
            content_expand = doc.metadata.get('content_expand')
        if hasattr(doc, 'page_content'):
            page_content = doc.page_content
        text = content_expand or page_content
        if text:
            key = text.strip()
            if key and key not in seen:
                seen.add(key)
                parts.append(text)
    return "\n\n".join(parts)


def _chunk_type(raw_docs) -> int:
    """解析产物是否全是 QA 行（0=普通切片，1=QA）。

    只有 xlsx/csv 会打 ``type=1``；其余格式的 ``metadata`` 里没有这个键。
    """
    docs = list(raw_docs or [])
    if not docs:
        return 0
    if all((getattr(doc, 'metadata', None) or {}).get('type') == 1 for doc in docs):
        return 1
    return 0


def _build_document(chunk: str, doc_name: str, chunk_id: int, chunk_type: int = 0) -> LCDocument:
    metadata = {
        'chunk_index': '',
        'source': doc_name,
        'content_expand': chunk,
        'chunk_id': chunk_id,
        'type': chunk_type,
    }
    return LCDocument(page_content=chunk, metadata=metadata)


def write_txt(docs, txt_save_path: str):
    logging.info(f'corpus size is {len(docs)}, write txt {txt_save_path}')
    parent = os.path.dirname(txt_save_path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent)
    with open(txt_save_path, 'a', encoding='utf-8') as fout:
        for doc in docs:
            fout.write(f"page_content={repr(doc.page_content)} metadata={repr(doc.metadata)}\n")
