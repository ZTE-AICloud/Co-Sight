"""按结构块切分：标题 / 段落 / 表格。

解析层（docx、markdown 及其派生格式）不再把表格压成带内部标记的纯文本，而是
产出块序列::

    {'kind': 'heading', 'level': 1, 'text': '第一章'}
    {'kind': 'text', 'text': '段落正文…'}
    {'kind': 'table', 'title': '设备表', 'rows': [['表头a', '表头b'], ['值1', '值2']]}

这里按块打包，保证：

* **表格行是原子**，不会被从中间切断；整表装不下时按行分包，每包重复
  表头行 —— 拆出来的每一块都要能独立读懂；
* **章节路径写进切片正文**（``第一章 > 第一节``），且同一块里多个小节共用
  公共前缀，不重复整条路径；
* **小切片会被打包**：相邻小节合起来仍不超过 ``max_word_count`` 时并成一块，
  否则一份小节普遍只有几十字的文档会切出一堆远小于上限的碎片；
* 目录行（「标题 + 页码」连续成段）默认过滤，且判据要求**连续、页码不下降、
  标题至少 4 个字**——「图1」「表2」「步骤3」「2019」这类编号/年份行不再被
  误判成目录（旧判据会因此把首尾之间的正文整段删掉）。

没有块序列的格式继续走 ``SentenceChunkSplitter``。
"""

import re

from parsing.splitter import (
    hard_split_text,
    join_parts,
    split_text_into_sentences,
)

#: 目录行：结尾 1~3 位页码。标题部分至少 4 个字符（挡掉「图1」「表2」「2019」）
_TOC_LINE = re.compile(r'^(.*?)(\d{1,3})$')

#: 表格单元格里的 ``|`` 必须转义，否则拆出来的行结构会有歧义
_CELL_PIPE = '\\|'


class BlockChunkSplitter:
    """块序列 → 切片。

    Args:
        max_word_count: 单个切片最大字符数（算子参数 maxWordCount）。
        overlap: 段落块之间的重叠字符数；**表格块不重叠**。
        include_heading_path: 是否把章节路径写进切片正文。
        drop_toc: 是否过滤目录行。
        heading_path_max_len: 章节路径的最大长度，超出时保留最深的几级。
        merge_sections: 相邻小节是否打包到同一块（默认开）。
    """

    #: 目录扫描只看文档开头这么多块
    TOC_SCAN_BLOCKS = 150
    #: 少于这么多条连续「标题+页码」就不当目录
    TOC_MIN_LINES = 5
    #: 目录行之间最多隔几个块（容忍换行折行）
    TOC_MAX_GAP = 3
    #: 目录行标题的最小长度（挡掉「图1」「2019」这类短行）
    TOC_TITLE_MIN_LEN = 4

    def __init__(self, max_word_count: int = 512, overlap: int = 128,
                 include_heading_path: bool = True, drop_toc: bool = True,
                 heading_path_max_len: int = 120, merge_sections: bool = True):
        if max_word_count <= 0:
            max_word_count = 512
        if overlap < 0:
            overlap = 128
        assert overlap < max_word_count, "overlap must be less than max_word_count"
        self.max_word_count = max_word_count
        self.overlap = overlap
        self.include_heading_path = include_heading_path
        self.drop_toc = drop_toc
        self.heading_path_max_len = heading_path_max_len
        self.merge_sections = merge_sections

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def split(self, blocks):
        return [chunk['text'] for chunk in self.split_detailed(blocks)]

    def split_detailed(self, blocks):
        """返回 ``[{'text': 切片正文, 'heading_path': 章节路径}]``。"""
        if not blocks:
            return []
        if self.drop_toc:
            blocks = self.drop_table_of_contents(blocks)

        chunks = []
        state = {'items': [], 'stack': []}
        for block in blocks:
            kind = block.get('kind')
            if kind == 'heading':
                state['stack'] = self.push_heading(state['stack'], block)
            elif kind == 'table':
                # 整张表能装进当前块时就并进去：表格行仍是原子单位，但不再让
                # 每张两行的小表各占一个 100 字的碎片切片。
                prepared = self.prepare_table(block, state['stack'])
                full = prepared[2]
                if full:
                    item = {'stack': list(state['stack']), 'text': full, 'raw': True}
                    if len(self.render(state['items'] + [item])) <= self.max_word_count:
                        state['items'].append(item)
                        # 表格是块的结尾：表格之后的段落另起一块，保证两者能
                        # 分开检索（表格前的段落可以并进来，方向不影响可分离性）。
                        self.flush(chunks, state)
                        continue
                self.flush(chunks, state)
                chunks.extend(self.split_table(block, state['stack'], prepared))
            else:
                self.feed_text(block.get('text') or '', chunks, state)
        self.flush(chunks, state)
        return [chunk for chunk in chunks if chunk['text'] and chunk['text'].strip()]

    # ------------------------------------------------------------------
    # 段落
    # ------------------------------------------------------------------

    def text_budget(self, stack):
        """正文预算 = 上限 − 章节路径前缀（前缀也算进切片长度）。"""
        prefix = self.heading_prefix(stack)
        return max(self.max_word_count - len(prefix) - 1, 1)

    def feed_text(self, text, chunks, state):
        budget = self.text_budget(state['stack'])
        for paragraph in text.split('\n'):
            if not paragraph.strip():
                continue
            for sentence in split_text_into_sentences(paragraph):
                if not sentence.strip():
                    continue
                if len(sentence) > budget:
                    self.flush(chunks, state)
                    overlap = max(0, min(self.overlap, budget - 1))
                    for piece in hard_split_text(sentence, budget, overlap):
                        chunks.append(self.make_chunk(
                            [{'stack': list(state['stack']), 'text': piece}]))
                    continue
                self.feed_sentence(sentence, chunks, state)

    def feed_sentence(self, sentence, chunks, state):
        item = {'stack': list(state['stack']), 'text': sentence}
        if not state['items']:
            state['items'] = [item]
            return
        if not self.merge_sections:
            # 旧语义：遇到新小节就落盘（此时 stack 已切换）
            if state['items'][-1]['stack'] != item['stack']:
                self.flush(chunks, state)
                state['items'] = [item]
                return
        elif not self.same_chapter(state['items'][0]['stack'], item['stack']):
            # 不跨一级标题打包：跨章的切片引用/展示都会指错地方
            self.flush(chunks, state)
            state['items'] = [item]
            return

        if len(self.render(state['items'] + [item])) <= self.max_word_count:
            state['items'].append(item)
            return

        flushed = self.flush(chunks, state)
        if self.overlap > 0 and flushed:
            carried = self.tail_items(flushed, self.overlap)
            if carried and len(self.render(carried + [item])) <= self.max_word_count:
                state['items'] = carried + [item]
                return
        state['items'] = [item]

    def flush(self, chunks, state):
        if not state['items']:
            return []
        items = state['items']
        chunks.append(self.make_chunk(items))
        state['items'] = []
        return items

    def make_chunk(self, items):
        return {
            'text': self.render(items),
            'heading_path': self.path_text(self.common_prefix([item['stack'] for item in items])),
        }

    def render(self, items):
        """把一组 (章节路径, 句子) 渲染成切片正文。

        同一块里多个小节共用公共前缀：``第一章 > 第一节`` 只写一次，各小节只写
        自己新增的那一级。
        """
        if not items:
            return ''
        prefix = self.common_prefix([item['stack'] for item in items])
        lines = []
        prefix_text = self.path_text(prefix)
        if prefix_text:
            lines.append(prefix_text)

        body = []
        current_path = None
        for item in items:
            if item['stack'] != current_path:
                if body:
                    lines.append(join_parts(body))
                    body = []
                sub_text = self.path_text(item['stack'][len(prefix):])
                if sub_text:
                    lines.append(sub_text)
                current_path = item['stack']
            if item.get('raw'):
                # 表格整体是一段自带换行的文本：独占若干行，不和相邻句子粘在一起
                if body:
                    lines.append(join_parts(body))
                    body = []
                lines.append(item['text'])
            else:
                body.append(item['text'])
        if body:
            lines.append(join_parts(body))
        return '\n'.join(line for line in lines if line)

    def tail_items(self, items, limit):
        """从块末尾反向取句子作为下一块的重叠部分（按正文长度算，不含前缀）。"""
        tail = []
        for item in reversed(items):
            if item.get('raw'):
                break
            candidate = [item] + tail
            if len(join_parts([entry['text'] for entry in candidate])) > limit:
                break
            tail = candidate
        return tail

    def same_chapter(self, left, right):
        """两个小节是否属于同一个一级标题。任一方没有一级标题时不限制。"""
        if not left or not right:
            return True
        return left[0] == right[0]

    def common_prefix(self, stacks):
        if not stacks:
            return []
        prefix = list(stacks[0])
        for stack in stacks[1:]:
            length = 0
            while length < len(prefix) and length < len(stack) and prefix[length] == stack[length]:
                length += 1
            prefix = prefix[:length]
            if not prefix:
                break
        return prefix

    def path_text(self, stack):
        if not stack:
            return ''
        return ' > '.join(text for _, text in stack if text)

    # ------------------------------------------------------------------
    # 表格
    # ------------------------------------------------------------------

    def prepare_table(self, block, stack):
        """返回 ``(head_text, body_lines, full_text)``；head_text 已按预算裁剪。"""
        rows = block.get('rows') or []
        if not rows:
            return '', [], ''
        title = (block.get('title') or '').strip()
        header_line = self.render_row(rows[0])
        head_text = '\n'.join(part for part in (title, header_line) if part)
        # 表头本身超预算（很宽的表）：先丢表头行、只留表名；还超就都不带，
        # 否则每一块都会超出上限。
        if len(self.decorate(head_text, stack)) >= self.max_word_count:
            head_text = title if len(self.decorate(title, stack)) < self.max_word_count else ''
        body = [self.render_row(row) for row in rows[1:]]
        full = '\n'.join([head_text] + body) if head_text else '\n'.join(body)
        return head_text, body, full

    def split_table(self, block, stack, prepared=None):
        head_text, body, full = prepared or self.prepare_table(block, stack)
        if not full:
            return []
        decorated = self.decorate(full, stack)
        if len(decorated) <= self.max_word_count:
            return [self.make_chunk_from_text(decorated, stack)]

        if not body:
            budget = self.text_budget(stack)
            overlap = max(0, min(self.overlap, budget - 1))
            return [self.make_chunk_from_text(self.decorate(piece, stack), stack)
                    for piece in hard_split_text(head_text, budget, overlap)]

        chunks = []
        budget = self.max_word_count - len(self.decorate(head_text, stack)) - 1
        current = []
        current_length = 0
        for line in body:
            if len(line) > budget:
                if current:
                    chunks.append(self.make_chunk_from_text(
                        self.decorate(head_text + '\n' + '\n'.join(current), stack), stack))
                    current = []
                    current_length = 0
                for piece in self.split_row(line, budget):
                    chunks.append(self.make_chunk_from_text(
                        self.decorate(head_text + '\n' + piece, stack), stack))
                continue
            if current_length + len(line) + 1 > budget and current:
                chunks.append(self.make_chunk_from_text(
                    self.decorate(head_text + '\n' + '\n'.join(current), stack), stack))
                current = []
                current_length = 0
            current.append(line)
            current_length += len(line) + 1
        if current:
            chunks.append(self.make_chunk_from_text(
                self.decorate(head_text + '\n' + '\n'.join(current), stack), stack))
        return chunks

    def split_row(self, line, budget):
        """单行超过预算时按单元格边界拆，实在拆不动才按字符硬切。"""
        budget = max(budget, 1)
        pieces = []
        current = []
        current_length = 0
        for cell in line.split('|'):
            if len(cell) > budget:
                # 单个格子就超预算：先把已攒的落盘，再按预算硬切这个格子
                if current:
                    pieces.append('|'.join(current))
                    current = []
                    current_length = 0
                pieces.extend(hard_split_text(cell, budget, 0))
                continue
            if current_length + len(cell) + 1 > budget and current:
                pieces.append('|'.join(current))
                current = []
                current_length = 0
            current.append(cell)
            current_length += len(cell) + 1
        if current:
            pieces.append('|'.join(current))
        return pieces

    def render_row(self, row):
        cells = []
        for cell in row:
            text = (cell or '').rstrip()
            text = text.replace('\r', ' ').replace('\n', ' ')
            cells.append(text.replace('|', _CELL_PIPE))
        return '|'.join(cells)

    # ------------------------------------------------------------------
    # 标题 / 目录
    # ------------------------------------------------------------------

    def push_heading(self, stack, block):
        level = block.get('level') or 1
        text = (block.get('text') or '').strip()
        stack = [item for item in stack if item[0] < level]
        if text:
            stack.append((level, text))
        return stack

    def decorate(self, body, stack):
        prefix = self.heading_prefix(stack)
        body = (body or '').strip()
        if not prefix:
            return body
        return f'{prefix}\n{body}' if body else prefix

    def heading_prefix(self, stack):
        if not self.include_heading_path or not stack:
            return ''
        path = ' > '.join(text for _, text in stack if text)
        if len(path) > self.heading_path_max_len:
            parts = path.split(' > ')
            while len(parts) > 1 and len(' > '.join(parts)) > self.heading_path_max_len:
                parts.pop(0)
            path = ' > '.join(parts)[-self.heading_path_max_len:]
        return path

    def make_chunk_from_text(self, text, stack):
        return {'text': text, 'heading_path': self.heading_prefix(stack)}

    # ------------------------------------------------------------------
    # 目录
    # ------------------------------------------------------------------

    def toc_page_number(self, block):
        """块是「标题 + 页码」样式的目录行时返回页码，否则 None。

        ⚠️ 判据必须足够严：``^.{1,60}\\d{1,3}$`` 这类宽判据会把「图1」「表2」
        「2019」也算成目录 —— 只要前 150 块里凑够 5 行，首尾之间的正文
        会被整段删掉（15 块的技术文档只剩 1 块）。判据：

        * 页码前至少 4 个字符（挡掉纯编号/短标签）；
        * 标题不能以数字结尾（挡掉「2023」这类年份行）；
        * 页码 ≥ 1。
        """
        if block.get('kind') not in ('text', 'heading'):
            return None
        text = (block.get('text') or '').strip()
        if not text or len(text) > 60 or '|' in text:
            return None
        match = _TOC_LINE.match(text)
        if not match:
            return None
        title = match.group(1).strip(' .·…\t')
        if len(title) < self.TOC_TITLE_MIN_LEN:
            return None
        if not title or title[-1].isdigit():
            return None
        page = int(match.group(2))
        if page < 1:
            return None
        return page

    def is_toc_line(self, block):
        return self.toc_page_number(block) is not None

    def drop_table_of_contents(self, blocks):
        """过滤文档开头的目录段（连续、「标题 + 页码」、页码不下降）。

        只删**匹配到的目录行**以及它们之间紧邻的折行块（间隔 ≤ ``TOC_MAX_GAP``），
        不能退化成「把首尾之间的所有块整段删掉」。
        """
        limit = min(len(blocks), self.TOC_SCAN_BLOCKS)
        candidates = []
        for index in range(limit):
            page = self.toc_page_number(blocks[index])
            if page is not None:
                candidates.append((index, page))
        if len(candidates) < self.TOC_MIN_LINES:
            return blocks

        best = []
        run = []
        for index, page in candidates:
            if run and (index - run[-1][0] > self.TOC_MAX_GAP or page < run[-1][1]):
                run = []
            run.append((index, page))
            if len(run) > len(best):
                best = list(run)
        if len(best) < self.TOC_MIN_LINES:
            return blocks

        drop = set()
        previous = None
        for index, _ in best:
            drop.add(index)
            if previous is not None and index - previous <= self.TOC_MAX_GAP:
                drop.update(range(previous + 1, index))
            previous = index
        return [block for index, block in enumerate(blocks) if index not in drop]
