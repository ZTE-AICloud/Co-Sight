import re


class SentenceValidator:
    def __init__(self):
        pass

    def chinese_ratio(self, text):
        chinese_count = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        ratio = chinese_count / len(text)
        return ratio

    def is_contain_chinese(self, sentence):
        chinese_pattern = re.compile(r'[\u4e00-\u9fa5]')
        match = re.search(chinese_pattern, sentence)
        return bool(match)

    def is_add_sentence_key(self, sentence):
        if sentence and len(sentence) > 3 and not self.contains_url(sentence) \
                and (self.chine_validate(sentence) or self.latin_validate(sentence)):
            return True
        return False

    def chine_validate(self, sentence):
        return self.is_contain_chinese(sentence) and self.chinese_ratio(sentence) > 0.10

    def latin_validate(self, sentence):
        """非中文句子的准入：**字母占比 > 0.5**。

        如果只认 ``chine_validate``（必须有中文且中文占比 >10%），**纯英文正文
        一条句子都进不来** —— 对 ``.txt`` 来说整个文档解析为空
        （``process_single_file`` 里「正文为空就静默 return」→ 不产出
        corpus_file.txt → 上层报「切分算子失败」）。
        ``zh``/``md`` 带标题的文档因为有「标题/段落兜底」才没暴露。

        这条判据是**增量**：中文判据原样保留，只额外放行「英文等拉丁文本」——
        中文语料的结果不变（见 ``test_split.py`` 的对照用例）。
        仍然排除 URL（``contains_url``）与长度 ≤3 的碎片。
        """
        letters = sum(1 for char in sentence if char.isalpha())
        return letters / max(len(sentence), 1) > 0.5

    def contains_url(self, text):
        url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+'
        match = re.search(url_pattern, text)
        return match is not None
