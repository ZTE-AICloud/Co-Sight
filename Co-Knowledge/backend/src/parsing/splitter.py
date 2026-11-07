"""段落 → 句子 → 定长 + overlap 切分器（自研，替代私有 corpus 切分）。

切分语义：先按段落（换行）切分，再按句子（中英文标点）切分，最后将句子合并为
不超过 max_word_count 的定长切片，相邻切片保留 overlap 个字符的重叠。

参数与 split/operator_all.json 中系统算子 -1 的 defaultArgs 一致：
    maxWordCount 默认 512，overlap 默认 128，且必须满足 overlap < maxWordCount。

两处质量约束：

* **拼接不再无条件补空格**：以前 ``' '.join(...)`` 会在每个中文句号后插入空格
  （``"这是第一段。 它有两句话。"``），破坏原文、影响短语检索。现在只在两侧
  都不是中日韩字符时才补空格（中英混排仍按英文习惯保留空格）。
* **超长句硬切优先落在边界**：无标点长文本（日志、base64、超宽表格行）以前按
  字符等分，会从单词/URL/数字中间切断；现在先回看最多 15% 的长度找空白或
  标点，找不到才硬切。
"""

# 常见英文缩写（不含点）及单个字母缩写，避免把 "Mr." 等误判为句尾
_ABBREVIATIONS = {
    'mr', 'mrs', 'ms', 'dr', 'prof', 'rev', 'hon', 'st', 'co', 'ltd', 'inc',
    'dept', 'univ', 'assn', 'gov', 'etc', 'eg', 'ie', 'viz', 'cf', 'ex', 'al',
    'p', 'pp', 'ch', 'sec', 'pl', 'no', 'vol', 'art', 'fig', 'para',
} | set('abcdefghijklmnopqrstuvwxyz')

#: 中日韩字符/全角标点的 Unicode 区段。用于决定拼接时要不要补空格。
_CJK_RANGES = (
    ('⺀', '⿿'),   # 部首补充
    ('　', '〿'),   # 中日韩符号与标点
    ('぀', 'ヿ'),   # 假名
    ('㐀', '䶿'),   # 扩展 A
    ('一', '鿿'),   # 基本区
    ('豈', '﫿'),   # 兼容汉字
    ('＀', '￯'),   # 全角 ASCII / 半角片假名
)

#: 硬切时优先落刀的位置：空白、中英文标点、右括号
_HARD_BREAK_CHARS = frozenset(' \t\n，。；：！？、,.;:!?）】」』”’>')


def is_cjk_char(char):
    """字符是否属于中日韩文字/全角标点。"""
    if not char:
        return False
    return any(low <= char <= high for low, high in _CJK_RANGES)


def join_parts(parts):
    """拼接句子：英文之间补空格，中文（任一侧是 CJK）直接相连。"""
    out = []
    last_char = ''
    for part in parts:
        if not part:
            continue
        if out and last_char and not (is_cjk_char(last_char) or is_cjk_char(part[0])):
            out.append(' ')
        out.append(part)
        last_char = part[-1]
    return ''.join(out)


def separator_length(last_char, first_char):
    """两个片段相连时需要补的空格数（0 或 1）。"""
    if not last_char or not first_char:
        return 0
    if is_cjk_char(last_char) or is_cjk_char(first_char):
        return 0
    return 1


def hard_split_text(text, size, overlap, lookback_ratio=0.15):
    """按字符数硬切，优先在空白/标点处落刀，并保留 overlap 重叠。

    ``size`` <= 0 时原样返回；``overlap`` 必须小于 ``size``（调用方保证），
    但即使传大也保证前进，不会死循环。
    """
    if not text:
        return []
    if size <= 0:
        return [text]
    lookback = max(1, int(size * lookback_ratio))
    pieces = []
    start = 0
    total = len(text)
    while start < total:
        end = min(start + size, total)
        if end < total:
            floor = max(start + 1, end - lookback)
            cut = -1
            for index in range(end - 1, floor - 1, -1):
                if text[index] in _HARD_BREAK_CHARS:
                    cut = index + 1
                    break
            if cut > start:
                end = cut
        pieces.append(text[start:end])
        if end >= total:
            break
        next_start = end - overlap
        start = next_start if next_start > start else end
    return pieces


def split_text_into_sentences(text):
    """将一段文本切割成句子，处理中英文标点和常见缩写。"""
    if not text:
        return []

    sentences = []
    current = []
    i = 0
    n = len(text)

    while i < n:
        char = text[i]
        current.append(char)

        # 中文标点：直接切割
        if char in {'。', '？', '！'}:
            sentences.append(''.join(current))
            current = []
            i += 1
            continue

        # 英文标点：需验证是否为缩写
        if char in {'.', '?', '!'}:
            word_before = []
            j = len(current) - 2
            while j >= 0:
                c = current[j]
                if c.isalpha() or c == '.':
                    word_before.append(c.lower())
                    j -= 1
                else:
                    break
            word_before_str = ''.join(reversed(word_before))

            next_char = text[i + 1] if i + 1 < n else None
            is_sentence_end = (
                next_char in {' ', '\n', '"', "'", ')', ']', '}', '>'}
                or next_char is None
                or (next_char.isupper() and word_before_str not in _ABBREVIATIONS)
            )

            if char in {'?', '!'} or (is_sentence_end and word_before_str not in _ABBREVIATIONS):
                sentences.append(''.join(current))
                current = []

        i += 1

    if current:
        sentences.append(''.join(current))

    return [s.strip() for s in sentences if s.strip()]


class SentenceChunkSplitter:
    """段落 → 句子 → 定长 + overlap 切分器。

    Args:
        max_word_count: 每个切片的最大字符数（对应算子参数 maxWordCount）。
        overlap: 相邻切片重叠的字符数（对应算子参数 overlap），必须小于 max_word_count。
    """

    def __init__(self, max_word_count: int = 512, overlap: int = 128):
        # max_word_count <= 0 视为“未指定”，使用默认 512
        if max_word_count <= 0:
            max_word_count = 512
        # overlap < 0 视为“未指定”，使用算子默认 128
        if overlap < 0:
            overlap = 128
        assert overlap < max_word_count, "overlap must be less than max_word_count"
        self.max_word_count = max_word_count
        self.overlap = overlap

    def split(self, text: str):
        """将文本切分为定长切片列表（保证无空切片、内容不丢失）。"""
        if not text or not text.strip():
            return []
        sentences = self._paragraphs_to_sentences(text)
        chunks = self._merge_sentences(sentences)
        return [c for c in chunks if c and c.strip()]

    def _paragraphs_to_sentences(self, text: str):
        sentences = []
        for paragraph in text.split('\n'):
            if not paragraph.strip():
                continue
            sentences.extend(split_text_into_sentences(paragraph))
        return sentences

    def _merge_sentences(self, sentences):
        chunks = []
        current = []
        current_length = 0

        for sentence in sentences:
            # 与上一句相连时的分隔符长度（中文 0，英文 1）
            sent_length = len(sentence) + separator_length(
                current[-1][-1] if current else '', sentence[0])

            # 单句超过 max_word_count：先落当前块，再对超长句做定长硬切
            if len(sentence) > self.max_word_count:
                if current:
                    chunks.append(join_parts(current))
                    current = []
                    current_length = 0
                chunks.extend(hard_split_text(sentence, self.max_word_count, self.overlap))
                continue

            if current_length + sent_length <= self.max_word_count:
                current.append(sentence)
                current_length += sent_length
            else:
                if current:
                    chunks.append(join_parts(current))
                # 从当前块末尾反向取句子作为 overlap 尾部
                tail = self._tail_sentences(current)
                tail_length = len(join_parts(tail))
                # 尾部 + 新句若仍超长，则放弃尾部，保证单个切片不超 max_word_count
                new_length = tail_length + separator_length(
                    tail[-1][-1] if tail else '', sentence[0]) + len(sentence)
                if new_length <= self.max_word_count:
                    current = tail
                    current_length = new_length
                else:
                    current = []
                    current_length = len(sentence)

                current.append(sentence)

        if current:
            chunks.append(join_parts(current))

        return chunks

    def _tail_sentences(self, sentences):
        """从块末尾反向取句子，总长不超过 overlap。"""
        tail = []
        for sentence in reversed(sentences):
            candidate = [sentence] + tail
            if len(join_parts(candidate)) > self.overlap:
                break
            tail = candidate
        return tail

    def _hard_split_long_sentence(self, sentence: str):
        """对超过 max_word_count 的单句做定长硬切，保留 overlap 重叠。"""
        return hard_split_text(sentence, self.max_word_count, self.overlap)
