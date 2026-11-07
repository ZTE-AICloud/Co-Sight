"""切分器与 load_corpus_file 管线的自测脚本。

运行方式（服务根下）：
    python3 src/ingestion/tests/test_split.py

覆盖：
- 自研切分器 SentenceChunkSplitter（段落→句子→定长+overlap）
- load_corpus_file 对 4 类样本（md/txt/docx/pdf）的解析+切分管线
"""
import ast
import os
import shutil
import sys
import tempfile

# 保证可从任意目录运行：本文件在 <服务根>/src/ingestion/tests/ 下，
# 上溯三层得到 import 根 ``src/``。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from parsing.splitter import SentenceChunkSplitter, split_text_into_sentences  # noqa: E402


def _norm(s):
    return ' '.join(s.split())


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


CHINESE_PARAS = [
    "人工智能是计算机科学的一个重要分支。它研究如何让机器模拟人类的智能行为。近年来深度学习取得了巨大进展。",
    "自然语言处理是人工智能的核心方向之一。它致力于让计算机理解并生成人类语言。大语言模型推动了这一领域的发展。",
    "知识图谱是一种结构化的语义知识库。它用节点和边描述实体及其关系。知识图谱在问答系统中应用广泛。",
]

MD_CONTENT = (
    "# 第一章 人工智能概述\n" + CHINESE_PARAS[0] + "\n\n"
    "# 第二章 自然语言处理\n" + CHINESE_PARAS[1] + "\n\n"
    "# 第三章 知识图谱\n" + CHINESE_PARAS[2] + "\n"
)

def _make_sample_dir():
    d = tempfile.mkdtemp(prefix="ingestion_test_")
    return d


def _write(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _make_docx(path):
    import docx
    doc = docx.Document()
    doc.add_heading('人工智能概述', level=1)
    doc.add_paragraph(CHINESE_PARAS[0])
    doc.add_heading('自然语言处理', level=1)
    doc.add_paragraph(CHINESE_PARAS[1])
    doc.add_heading('知识图谱', level=1)
    doc.add_paragraph(CHINESE_PARAS[2])
    doc.save(path)


def _make_pdf(path):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    # 使用 reportlab 内置 Adobe CID 中文字体（STSong-Light），避免 reportlab 默认
    # Helvetica 无法渲染中文。wqy-microhei.ttc（GPL）已移除，
    # 故改为内置字体，无需随仓库分发 CJK 字体文件。
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))

    c = canvas.Canvas(path, pagesize=A4)
    c.setFont('STSong-Light', 12)
    y = 600  # 避开 read_pdf.py 的页眉/页脚过滤区间
    lines = [
        "# 第一章 人工智能概述",
        CHINESE_PARAS[0],
        "# 第二章 自然语言处理",
        CHINESE_PARAS[1],
        "# 第三章 知识图谱",
        CHINESE_PARAS[2],
    ]
    for line in lines:
        c.drawString(60, y, line)
        y -= 40
    c.save()


def _read_corpus_txt(corpus_file):
    docs = []
    with open(corpus_file, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or line.startswith('filepath='):
                continue
            page_content = ast.literal_eval(line.split('metadata=')[0].split('page_content=', 1)[1].strip())
            metadata = ast.literal_eval(line.split('metadata=', 1)[1])
            docs.append((page_content, metadata))
    return docs


# --------------------------------------------------------------------------
# 切分器单元测试
# --------------------------------------------------------------------------

def test_splitter_no_empty_no_overlong_no_loss():
    text = "\n\n".join(CHINESE_PARAS * 10)
    sp = SentenceChunkSplitter(max_word_count=200, overlap=50)
    chunks = sp.split(text)
    _assert(chunks, "splitter returned no chunks")

    for c in chunks:
        _assert(c.strip(), "empty chunk found")
        _assert(len(c) <= sp.max_word_count + sp.overlap,
                f"over-long chunk: len={len(c)} > max+overlap={sp.max_word_count + sp.overlap}")

    # 内容不丢失：每个句子都作为某一切片的子串出现
    sentences = split_text_into_sentences(text)
    _assert(sentences, "no sentences extracted")
    for s in sentences:
        s_norm = _norm(s)
        if len(s_norm) < 8:
            continue
        _assert(any(s_norm in _norm(c) for c in chunks), f"content lost: {s_norm[:30]}")
    return len(chunks)


def test_splitter_overlap_effective():
    # 短句 + 小窗口，确保产生重叠
    sentences = [f"第{i}句" for i in range(30)]
    text = "。".join(sentences) + "。"
    sp = SentenceChunkSplitter(max_word_count=20, overlap=10)
    chunks = sp.split(text)
    _assert(len(chunks) >= 2, f"expected >=2 chunks, got {len(chunks)}")

    overlapped = False
    for i in range(len(chunks) - 1):
        cur = chunks[i]
        nxt = chunks[i + 1]
        cur_sentences = split_text_into_sentences(cur)
        if cur_sentences and any(_norm(s) in _norm(nxt) for s in cur_sentences):
            overlapped = True
            break
    _assert(overlapped, "overlap did not take effect between adjacent chunks")
    return len(chunks)


def test_splitter_rejects_invalid_overlap():
    raised = False
    try:
        SentenceChunkSplitter(max_word_count=100, overlap=100)
    except AssertionError:
        raised = True
    _assert(raised, "overlap >= max_word_count should raise AssertionError")


# --------------------------------------------------------------------------
# identify_duplicate_chunks 的 chunk 表 text 语义（回归 D-缺3）
# --------------------------------------------------------------------------

def test_identify_duplicate_chunks_text_fallback():
    """chunk 表 text 语义：系统算子取 content_expand（完整上下文），
    自定义算子无 content_expand 时回退到节点正文 text，避免 chunk 表 text 为空。"""
    from ingestion.split.node_transfer import identify_duplicate_chunks

    kbase_id, source = "kb-test", "custom.md"

    # 自定义算子：metadata 无 content_expand -> chunk text 回退到节点 text（与向量/ES 一致）
    custom_nodes = [
        {"nodeId": "n1", "text": "自定义算子正文A",
         "metadata": {"source": source, "chunk_index": 1}, "embedding": None},
        {"nodeId": "n2", "text": "自定义算子正文B",
         "metadata": {"source": source, "chunk_index": 2}, "embedding": None},
    ]
    _, custom_chunks = identify_duplicate_chunks(custom_nodes, kbase_id, source)
    custom_texts = {c["text"] for c in custom_chunks}
    _assert(custom_texts == {"自定义算子正文A", "自定义算子正文B"},
            f"custom op chunk text mismatch: {custom_texts}")

    # 系统算子：metadata 含 content_expand -> chunk text 保留 content_expand（不回退）
    sys_nodes = [
        {"nodeId": "n3", "text": "检索短句",
         "metadata": {"source": source, "chunk_index": 1, "content_expand": "完整上下文"}, "embedding": None},
    ]
    _, sys_chunks = identify_duplicate_chunks(sys_nodes, kbase_id, source)
    _assert(sys_chunks[0]["text"] == "完整上下文",
            f"system op chunk text changed: {sys_chunks[0]['text']!r}")

    return {"custom_texts": sorted(custom_texts), "system_text": sys_chunks[0]["text"]}


# --------------------------------------------------------------------------
# load_corpus_file 管线测试（解析 + 切分 + corpus_file.txt 写出）
# --------------------------------------------------------------------------

def _run_pipeline(src_path, max_word_count, overlap, out_dir):
    from parsing.corpus import load_corpus_file
    load_corpus_file(src_path, out_dir, max_word_count, overlap)
    corpus_file = os.path.join(out_dir, 'output', 'corpus_file.txt')
    _assert(os.path.exists(corpus_file), f"corpus_file.txt not generated: {corpus_file}")
    return _read_corpus_txt(corpus_file)


def _assert_pipeline_invariants(docs, max_word_count, overlap, label):
    _assert(docs, f"[{label}] pipeline produced no chunks")
    for page_content, metadata in docs:
        _assert(page_content and page_content.strip(), f"[{label}] empty page_content")
        _assert(len(page_content) <= max_word_count + overlap,
                f"[{label}] over-long chunk len={len(page_content)}")
        _assert(metadata.get('source'), f"[{label}] metadata missing source")
        _assert('content_expand' in metadata, f"[{label}] metadata missing content_expand")
    return len(docs)


def test_pipeline_reconstruct_no_duplicate():
    """回归 D-缺2：md 解析器为每个句子复制整段 content_expand，_reconstruct_text 须按
    content_expand 去重，不能把同一段落重复 N 次。"""
    from parsing.corpus import _reconstruct_text
    from parsing.parsers.strategies import MdFileParseStrategy

    sample_dir = _make_sample_dir()
    md_path = os.path.join(sample_dir, 'dup.md')
    para = "这是第一句。这是第二句。这是第三句。"
    _write(md_path, "# 标题\n" + para + "\n")
    try:
        docs = MdFileParseStrategy().process(md_path)
        text = _reconstruct_text(docs)
        _assert(text.count("这是第一句") == 1,
                f"paragraph duplicated: count={text.count('这是第一句')}")
        _assert("这是第二句" in text and "这是第三句" in text, "content lost after dedup")
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)
    return text.count("这是第一句")


def test_pipeline_md_txt_docx_pdf():
    from parsing.corpus import load_corpus_file  # noqa: F401 (import smoke)

    sample_dir = _make_sample_dir()
    max_word_count, overlap = 200, 50
    results = {}
    try:
        # md
        md_path = os.path.join(sample_dir, 'sample.md')
        _write(md_path, MD_CONTENT)
        docs = _run_pipeline(md_path, max_word_count, overlap, os.path.join(sample_dir, 'out_md'))
        results['md'] = _assert_pipeline_invariants(docs, max_word_count, overlap, 'md')
        _assert(any('人工智能是计算机科学' in d[0] for d in docs), "[md] key content missing")

        # txt
        txt_path = os.path.join(sample_dir, 'sample.txt')
        _write(txt_path, "\n\n".join(CHINESE_PARAS))
        docs = _run_pipeline(txt_path, max_word_count, overlap, os.path.join(sample_dir, 'out_txt'))
        results['txt'] = _assert_pipeline_invariants(docs, max_word_count, overlap, 'txt')
        _assert(any('知识图谱在问答系统中应用广泛' in d[0] for d in docs), "[txt] key content missing")

        # docx
        docx_path = os.path.join(sample_dir, 'sample.docx')
        _make_docx(docx_path)
        docs = _run_pipeline(docx_path, max_word_count, overlap, os.path.join(sample_dir, 'out_docx'))
        results['docx'] = _assert_pipeline_invariants(docs, max_word_count, overlap, 'docx')

        # pdf
        pdf_path = os.path.join(sample_dir, 'sample.pdf')
        try:
            _make_pdf(pdf_path)
        except ImportError as e:
            results['pdf'] = f"SKIPPED (reportlab not available: {e})"
        else:
            docs = _run_pipeline(pdf_path, max_word_count, overlap, os.path.join(sample_dir, 'out_pdf'))
            results['pdf'] = _assert_pipeline_invariants(docs, max_word_count, overlap, 'pdf')
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)

    return results


# --------------------------------------------------------------------------

def _make_headingless_docx(path):
    """只用「正文」样式排版、完全没有 Heading 1~5 的 Word 文档。"""
    import docx
    doc = docx.Document()
    for para in CHINESE_PARAS:
        doc.add_paragraph(para)
    doc.save(path)


def _make_headingless_pptx(path):
    """只有标题、没有正文的 PPT（真实的单页标题幻灯片）。"""
    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])   # Title Only
    slide.shapes.title.text = '人工智能概述'
    prs.save(path)


def test_pipeline_headingless_documents():
    """**没有标题层级的文档必须能出切片**（回归：整类真实文档解析为空）。

    病因：解析链是「标题锚定」的 ——

    * docx：``WordContentParser.set_content`` 里 ``if self.is_not_header(headers)``
      在没出现过 Heading 样式时恒为假，正文一条都不收集；
    * pdf / pptx / html：``MdContentParser.extract_heading_and_paragraphs`` 丢掉
      第一个 ``#`` **之前**的正文，且跳过「只有标题没有正文」的章节。

    于是只用「正文」样式排版的 Word、Word 导出的 PDF、单页标题 PPT 全部产出 0 条
    记录，上层 corpus 抛 ``ParseEmptyError`` → 对外 ``RetCode.operator.split.empty``
    （"文件未能解析出文本内容"），而这些恰恰是用户最常见的文件形态。
    """
    sample_dir = _make_sample_dir()
    max_word_count, overlap = 200, 50
    results = {}
    try:
        # docx：无 Heading 样式
        docx_path = os.path.join(sample_dir, 'plain.docx')
        try:
            _make_headingless_docx(docx_path)
        except ImportError as e:
            results['docx'] = f"SKIPPED (python-docx not available: {e})"
        else:
            docs = _run_pipeline(docx_path, max_word_count, overlap, os.path.join(sample_dir, 'out_docx'))
            results['docx'] = _assert_pipeline_invariants(docs, max_word_count, overlap, 'docx')
            _assert(any('人工智能是计算机科学' in d[0] for d in docs),
                    "[docx] heading-less body content missing")

        # pptx：只有标题
        pptx_path = os.path.join(sample_dir, 'titled.pptx')
        try:
            _make_headingless_pptx(pptx_path)
        except ImportError as e:
            results['pptx'] = f"SKIPPED (python-pptx not available: {e})"
        else:
            docs = _run_pipeline(pptx_path, max_word_count, overlap, os.path.join(sample_dir, 'out_pptx'))
            results['pptx'] = _assert_pipeline_invariants(docs, max_word_count, overlap, 'pptx')
            _assert(any('人工智能概述' in d[0] for d in docs),
                    "[pptx] title-only slide content missing")

        # html：只有正文段落、没有标题标签，且不能把 <title>/<script> 当正文
        html_path = os.path.join(sample_dir, 'plain.html')
        _write(html_path, "<!DOCTYPE html><html><head><title>页面标题</title></head><body>"
                          + ''.join(f"<p>{para}</p>" for para in CHINESE_PARAS)
                          + "<script>var x = 1;</script></body></html>")
        docs = _run_pipeline(html_path, max_word_count, overlap, os.path.join(sample_dir, 'out_html'))
        results['html'] = _assert_pipeline_invariants(docs, max_word_count, overlap, 'html')
        joined = ' '.join(d[0] for d in docs)
        _assert('人工智能是计算机科学' in joined, "[html] heading-less body content missing")
        _assert('页面标题' not in joined, "[html] <title> leaked into chunks")
        _assert('var x' not in joined, "[html] <script> leaked into chunks")
        _assert('=====' not in joined, "[html] setext heading underline leaked into chunks")
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)

    return results


def test_pipeline_table_rows_keep_all_columns():
    """Excel/CSV 的每一行必须**保留全部列**（回归：只取前两列）。

    以前 ``ExcelContentParser`` 只读 ``row[0]`` / ``row[1]``，三列以上的表格
    第三列起全部丢失 —— 实测一份 3 列的 xlsx 切片只剩 ``Category EV`` 这种碎片。
    """
    sample_dir = _make_sample_dir()
    max_word_count, overlap = 200, 50
    results = {}
    try:
        csv_path = os.path.join(sample_dir, 'table.csv')
        _write(csv_path, "Category,Company,Volume\nEV,BYD,1200\nEV,Tesla,900\n")
        docs = _run_pipeline(csv_path, max_word_count, overlap, os.path.join(sample_dir, 'out_csv'))
        joined = ' '.join(d[0] for d in docs)
        results['csv'] = _assert_pipeline_invariants(docs, max_word_count, overlap, 'csv')
        for expected in ('BYD', '1200', 'Tesla', '900'):
            _assert(expected in joined, f"[csv] column value lost: {expected}")
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)

    return results


# --------------------------------------------------------------------------

def test_pipeline_english_txt_and_validator_scope():
    """英文 .txt 必须能进解析（回归：`修改提示词.txt` 曾整篇解析为空）。

    病因：``SentenceValidator.is_add_sentence_key`` 只认中文（``chine_validate``：
    含中文且中文占比 >10%），纯英文正文一条句子都进不来 → ``process_single_file``
    里「正文为空就静默 return」→ 不产出 corpus_file.txt → 上层报「切分算子失败」。
    实测该文件在不同后端**同样失败**，属解析器的缺陷。

    同时钉住「纯增量」：中文语料的判定结果**不变**（英文与中文各判一条），
    URL 仍被排除。
    """
    from parsing.common.sentence_add_validator import SentenceValidator
    validator = SentenceValidator()

    # 1) 英文句子现在放行（之前 False）
    _assert(validator.is_add_sentence_key("You are a world-class software architect"),
            "English sentence should be accepted as a sentence key")
    # 2) 中文判定不变
    _assert(validator.is_add_sentence_key("这是中文段落：用于验证切分链路。"),
            "Chinese sentence must keep being accepted")
    # 3) URL 仍排除；过短的碎片仍排除
    _assert(not validator.is_add_sentence_key("see https://example.com/a/b for details"),
            "URL sentence must stay rejected")
    _assert(not validator.is_add_sentence_key("ok"), "too-short fragment must stay rejected")

    # 4) 端到端：英文 txt 走完整管线并产出切片
    sample_dir = _make_sample_dir()
    txt_path = os.path.join(sample_dir, 'english.txt')
    _write(txt_path, "# Role\n\nYou are a world-class software architect.\n\n"
                     "Extract entities and relationships from the code.\n")
    try:
        docs = _run_pipeline(txt_path, 512, 128, os.path.join(sample_dir, 'out_en'))
        _assert_pipeline_invariants(docs, 512, 128, 'english-txt')
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)
    return len(docs)


def test_empty_content_raises_parse_empty_error():
    """零文本文件**必须抛 ParseEmptyError**，不能静默 return。

    示例：GoAccess 报告是 JS 渲染页 —— 正文全在
    ``<script>var json_data=…</script>`` 里，静态 DOM 只有空壳。``markdownify`` 读 DOM
    得到 76 字节（标题 + 页脚），解析器产出 0 条文本；若 ``if not full_text: return``
    静默返回、不写 corpus_file.txt，上层读文件报 ``FileNotFoundError``，最终被翻译成
    ``RetCode.operator.split.error``（"切分算子执行失败，请检查算子是否存在问题"）
    —— 用户拿到的提示与真实原因无关。

    同一路径的空白 .txt 亦然（本条用例的第二个样本）。改动后异常带
    ``message='RetCode.operator.split.empty'``，信封 ``code.msg`` 即该键，
    上层据此映射出可读文案。

    ⚠️ 解析器会保留「标题之前的正文」，**有字的短页面会产出切片**（这是对的），
    所以第三个样本必须是真正零文本的页面。见下方注释。
    """
    from parsing.exception import ParseEmptyError
    from parsing.corpus import load_corpus_file

    sample_dir = _make_sample_dir()
    # 1) JS 渲染页的空壳 HTML：正文在 <script> 里，静态 DOM 一字皆无
    html_path = os.path.join(sample_dir, 'report.html')
    _write(html_path, "<!DOCTYPE html><html><head><title>服务器统计</title></head>"
                      "<body><div id='app'></div>"
                      "<script>var json_data={\"total_requests\": 547486};</script>"
                      "</body></html>")
    # 2) 纯空白 .txt：一条句子都进不来
    blank_path = os.path.join(sample_dir, 'blank.txt')
    _write(blank_path, "   \n\n \t\n")
    # 3) 只有 <script> 的页面（没有 <title>）：同样一个字都没有
    #    ⚠️ 不能用「DOM 只剩『仪表盘』的短文本页」当本用例样本：
    #    切分器不挂 ``SentenceValidator``，解析器又会保留「标题前的正文」，
    #    于是那个样本**应该**产出一个切片（正文确实有字）。这里用真正零文本的页面。
    stub_path = os.path.join(sample_dir, 'stub.html')
    _write(stub_path, "<html><body><div id='app'></div>"
                      "<script>window.__DATA__ = {};</script></body></html>")

    checked = []
    try:
        for path in (html_path, blank_path, stub_path):
            try:
                load_corpus_file(path, os.path.join(sample_dir, 'out_' + os.path.basename(path)),
                                 512, 128)
            except ParseEmptyError as e:
                _assert(e.message == 'RetCode.operator.split.empty',
                        f"wire key wrong: {e.message}")
                _assert(os.path.basename(path) in str(e),
                        f"diagnostic lacks file name: {e}")
                checked.append(os.path.basename(path))
            else:
                raise AssertionError(f"{path}: 旧行为复辟 —— 零文本未抛 ParseEmptyError")
    finally:
        shutil.rmtree(sample_dir, ignore_errors=True)
    return ','.join(checked)


def main():
    tests = [
        ('test_splitter_no_empty_no_overlong_no_loss', test_splitter_no_empty_no_overlong_no_loss),
        ('test_splitter_overlap_effective', test_splitter_overlap_effective),
        ('test_splitter_rejects_invalid_overlap', test_splitter_rejects_invalid_overlap),
        ('test_identify_duplicate_chunks_text_fallback', test_identify_duplicate_chunks_text_fallback),
        ('test_pipeline_reconstruct_no_duplicate', test_pipeline_reconstruct_no_duplicate),
        ('test_pipeline_md_txt_docx_pdf', test_pipeline_md_txt_docx_pdf),
        ('test_pipeline_headingless_documents', test_pipeline_headingless_documents),
        ('test_pipeline_table_rows_keep_all_columns', test_pipeline_table_rows_keep_all_columns),
        ('test_pipeline_english_txt_and_validator_scope', test_pipeline_english_txt_and_validator_scope),
        ('test_empty_content_raises_parse_empty_error', test_empty_content_raises_parse_empty_error),
    ]

    failures = []
    for name, fn in tests:
        try:
            detail = fn()
            print(f"PASS  {name}  -> {detail}")
        except Exception as e:
            failures.append((name, e))
            print(f"FAIL  {name}  -> {type(e).__name__}: {e}")

    print("-" * 70)
    if failures:
        print(f"RESULT: {len(tests) - len(failures)}/{len(tests)} passed, {len(failures)} failed")
        for name, e in failures:
            print(f"  FAILED: {name}: {e}")
        sys.exit(1)
    else:
        print(f"RESULT: all {len(tests)} tests passed")
        sys.exit(0)


if __name__ == '__main__':
    main()
