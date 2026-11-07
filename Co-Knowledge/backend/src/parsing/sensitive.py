"""敏感词检查器：从本地词表文件加载。

词表文件为 config/sensitive_words.txt。
"""
import logging
import os

from parsing.exception import SensitiveMsgException


class DefaultSensitiveWordChecker:
    """敏感词检查器接口。默认实现为空（不检查），与私有 corpus 行为一致。"""

    def check_sensitive_word(self, content: str):
        return


def _default_word_file() -> str:
    # parsing/sensitive.py -> 服务根（backend）
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # SENSITIVE_WORDS_FILE 可覆盖（compose 里通常挂载到卷上）
    return os.environ.get('SENSITIVE_WORDS_FILE') or os.path.join(project_root, 'config', 'sensitive_words.txt')


class LocalSensitiveWordChecker(DefaultSensitiveWordChecker):
    """读取本地词表文件进行子串匹配的敏感词检查器。

    词表格式：每行一个敏感词，# 开头为注释，空白行忽略。词表为空或文件不存在时视为不过滤。
    """

    def __init__(self, word_file: str = None):
        self.word_file = word_file or _default_word_file()
        self._words = self._load_words(self.word_file)

    def _load_words(self, word_file):
        if not os.path.exists(word_file):
            logging.warning(f"sensitive word file not found, skip filtering: {word_file}")
            return []
        words = []
        with open(word_file, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                words.append(line)
        return words

    def check_sensitive_word(self, content: str):
        if not self._words or not content:
            return
        for word in self._words:
            if word in content:
                raise SensitiveMsgException(
                    code="0006",
                    bo=None,
                    message_dict={
                        'zh_CN': "处理失败，语料存在敏感信息",
                        'en_US': "Parsing failed. The corpus contains sensitive information"
                    }
                )


class SensitiveWordChecker(LocalSensitiveWordChecker):
    """带初始化日志的本地敏感词检查器。"""

    def __init__(self, word_file: str = None):
        super().__init__(word_file=word_file)
        logging.info(f'SensitiveWordChecker loaded {len(self._words)} sensitive words from {self.word_file}')
