"""块切分器：表格行是原子、表头重复、章节路径前缀、目录过滤。

要处理的情况：

* 内部哨兵 ``table is find`` / ``table is finished`` 漏进切片
  （a.docx 1361/5730 块、ip.docx 11/19 块）；
* 表格行被 512 字硬切从中间切断，检索时拿到半行；
* 切片不带章节标题，孤立看不知道属于哪一节；
* 文档开头的目录被当正文切。
"""

from parsing.block_splitter import BlockChunkSplitter


def _table(rows, title='设备表'):
    return {'kind': 'table', 'title': title, 'rows': rows}


def _heading(text, level=1):
    return {'kind': 'heading', 'level': level, 'text': text}


def _text(text):
    return {'kind': 'text', 'text': text}


def test_table_rows_stay_whole():
    rows = [['序号', '姓名']] + [[f'{i}号', f'姓名{i}'] for i in range(1, 30)]
    chunks = BlockChunkSplitter(max_word_count=120, overlap=20).split([_table(rows)])

    assert len(chunks) > 1
    for chunk in chunks:
        for line in chunk.split('\n'):
            if '|' not in line:
                continue
            for cell in line.split('|'):
                assert cell.split('：')[-1] in {'序号', '姓名'} or cell.split('：')[-1] in {
                    f'{i}号' for i in range(1, 30)
                } or cell.split('：')[-1] in {f'姓名{i}' for i in range(1, 30)}


def test_table_header_repeats_in_every_chunk():
    rows = [['序号', '姓名']] + [[f'{i}号', f'姓名{i}'] for i in range(1, 30)]
    chunks = BlockChunkSplitter(max_word_count=120, overlap=20).split([_table(rows)])

    assert len(chunks) > 1
    for chunk in chunks:
        assert '序号' in chunk and '姓名' in chunk


def test_table_title_repeats_in_every_chunk():
    rows = [['序号', '姓名']] + [[f'{i}号', f'姓名{i}'] for i in range(1, 30)]
    chunks = BlockChunkSplitter(max_word_count=120, overlap=20).split([_table(rows, '应急联系人')])

    assert all(chunk.startswith('应急联系人') for chunk in chunks)


def test_heading_path_is_prefixed():
    blocks = [_heading('第一章 总则'), _heading('第一节 目的', level=2),
              _text('这是一段正文，长度足够形成切片。')]
    chunks = BlockChunkSplitter().split(blocks)

    assert chunks == ['第一章 总则 > 第一节 目的\n这是一段正文，长度足够形成切片。']


def test_heading_nesting_resets_deeper_levels():
    blocks = [
        _heading('第一章'),
        _heading('一、总则', level=2),
        _text('第一章总则的正文，长度足够形成切片。'),
        _heading('二、范围', level=2),
        _text('第一章范围的正文，长度足够形成切片。'),
        _heading('第二章', level=1),
        _text('第二章的正文，长度足够形成切片。'),
    ]
    chunks = BlockChunkSplitter(merge_sections=False).split(blocks)

    assert '第一章 > 一、总则' in chunks[0]
    assert '第一章 > 二、范围' in chunks[1]
    assert chunks[2].startswith('第二章\n')


def test_short_sections_are_packed_into_one_chunk():
    blocks = [
        _heading('第一章'),
        _heading('一、总则', level=2),
        _text('第一章总则的正文。'),
        _heading('二、范围', level=2),
        _text('第一章范围的正文。'),
    ]
    chunks = BlockChunkSplitter().split(blocks)

    assert len(chunks) == 1
    assert '一、总则' in chunks[0]
    assert '二、范围' in chunks[0]


def test_sections_from_different_chapters_are_not_packed():
    blocks = [
        _heading('第一章'),
        _text('第一章的正文。'),
        _heading('第二章'),
        _text('第二章的正文。'),
    ]
    chunks = BlockChunkSplitter().split(blocks)

    assert len(chunks) == 2
    assert chunks[0].startswith('第一章')
    assert chunks[1].startswith('第二章')


def test_merged_chunk_writes_common_prefix_once():
    blocks = [
        _heading('第一章'),
        _heading('第一节', level=2),
        _text('第一节的正文。'),
        _heading('第二节', level=2),
        _text('第二节的正文。'),
    ]
    chunks = BlockChunkSplitter().split(blocks)

    assert len(chunks) == 1
    assert chunks[0].count('第一章') == 1
    assert '第一节' in chunks[0] and '第二节' in chunks[0]


def test_table_of_contents_is_dropped():
    toc = [_text(f'{index}、第{index}章标题{index}') for index in range(1, 9)]
    blocks = [_text('前言正文，长度足够形成切片。')] + toc + [
        _text('第一章真正的正文，长度足够形成切片。')]
    chunks = BlockChunkSplitter().split(blocks)

    joined = '\n'.join(chunks)
    assert '第1章标题1' not in joined
    assert '第一章真正的正文' in joined


def test_toc_scan_only_covers_document_start():
    """目录只扫文档开头；正文中间出现「标题+页码」的短行不能误删。"""
    filler = [_text('普通正文内容，用来占位。') for _ in range(BlockChunkSplitter.TOC_SCAN_BLOCKS + 10)]
    tail = [_text(f'第{index}项说明{index}') for index in range(1, 9)]
    chunks = BlockChunkSplitter(drop_toc=True).split(filler + tail)

    assert '第1项说明1' in '\n'.join(chunks)


def test_text_chunks_overlap_by_sentences():
    sentences = [f'这是第{i}句用来测试重叠的正文内容。' for i in range(1, 12)]
    chunks = BlockChunkSplitter(max_word_count=80, overlap=30).split([_text(''.join(sentences))])

    assert len(chunks) > 1
    for previous, current in zip(chunks, chunks[1:]):
        shared = 0
        for size in range(min(len(previous), len(current)), 0, -1):
            if previous[-size:] == current[:size]:
                shared = size
                break
        assert shared > 0, (previous, current)


def test_no_overlap_when_zero():
    sentences = [f'这是第{i}句用来测试重叠的正文内容。' for i in range(1, 12)]
    chunks = BlockChunkSplitter(max_word_count=80, overlap=0).split([_text(''.join(sentences))])

    for previous, current in zip(chunks, chunks[1:]):
        assert not previous.endswith(current[:8])


def test_chunk_never_exceeds_max_word_count():
    rows = [['列一', '列二']] + [['很长的单元格内容' * 3, f'值{i}'] for i in range(10)]
    chunks = BlockChunkSplitter(max_word_count=200, overlap=20).split([
        _heading('标题'),
        _text('正文内容足够长，用来验证切片不会超过上限。' * 5),
        _table(rows),
    ])

    assert all(len(chunk) <= 200 for chunk in chunks)


def test_long_heading_path_does_not_overflow_chunks():
    """章节路径也占切片长度：路径 + 正文 + 重叠尾部必须一起算。"""
    blocks = [
        _heading('A.6.3 RRC_CONNECTION_CONTROL'),
        _heading('A.6.3.2 RRC connection control procedures', level=2),
        _heading('A.6.3.2.2 Random Access', level=3),
        _heading('A.6.3.2.2.2 4-step RA type non-contention based random access test', level=4),
        _text('The UE shall monitor the PDCCH for a random access response. ' * 12),
    ]
    chunks = BlockChunkSplitter(max_word_count=512, overlap=128).split(blocks)

    assert len(chunks) > 1
    assert all(len(chunk) <= 512 for chunk in chunks)


def test_figure_captions_are_not_treated_as_toc():
    """「图1」这类短标签不是目录行 —— 旧判据会把首尾之间的正文整段删掉。"""
    blocks = []
    for index in range(1, 6):
        blocks.append(_text(f'图{index}'))
        blocks.append(_text(f'图{index}展示了设备的接线方式，安装时必须断电操作。'))
    blocks.append(_text('结尾正文。'))

    chunks = BlockChunkSplitter().split(blocks)
    joined = '\n'.join(chunks)

    for index in range(1, 6):
        assert f'图{index}展示' in joined


def test_bare_year_lines_are_not_treated_as_toc():
    blocks = [_text(str(year)) for year in range(2019, 2024)]
    blocks.append(_text('这些年份对应的变更说明正文。'))

    chunks = BlockChunkSplitter().split(blocks)

    assert '这些年份对应的变更说明正文。' in '\n'.join(chunks)


def test_short_label_with_number_is_not_toc():
    blocks = [_text(f'步骤{index}') for index in range(1, 7)]
    blocks.append(_text('步骤正文内容。'))

    chunks = BlockChunkSplitter().split(blocks)

    assert '步骤正文内容。' in '\n'.join(chunks)


def test_pipe_in_table_cell_is_escaped():
    rows = [['列一', '列二'], ['a|b', 'c']]
    chunks = BlockChunkSplitter().split([_table(rows)])

    assert 'a\\|b' in chunks[0]
