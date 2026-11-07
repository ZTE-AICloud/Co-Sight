"""黑名单（敏感词）加载器。

**它是什么**：把一批 `*.txt`（文件名 = 词表名，内容用 `|#|` 分隔关键词）读进内存，
LLM 输出里的命中词会被替换成等长 `*`（消费方见 `core/rag/custom_llm/openai_llm.py`
的 `_mask_sensitive_words`）。

目录由环境变量 `BLACK_LIST_DIR` 指定（默认 `/app/black_list`，不存在就当作
「没有配黑名单」，只记一条日志）。「部署挂一个目录 → 输出里屏蔽敏感词」这条路可用。
**没有热更新**：改词表后需要重启或显式调用一次 `reload_black_list()`。
"""
import os
from typing import Dict, List

from engine.settings import Config
from engine.logutil import logger

# 词表名 → 关键词列表（关键词按长度倒序，替换时先长后短）
sensitive_words_cache: Dict[str, List[str]] = {}


def get_black_list_dir() -> str:
    """黑名单目录（按 `BLACK_LIST_DIR` 取，见 config.py）。"""
    return Config.get('black_list_dir', '')


def reload_black_list(path: str = '') -> None:
    """（重新）加载黑名单。目录不存在时**不是错误**：只是一个没有黑名单的部署。"""
    sensitive_words = _read_black_list(path)
    sensitive_words = {k: v for k, v in sensitive_words.items() if len(v) > 0}
    sensitive_words_cache.update(sensitive_words)
    logger.info('black list loaded, vocabularies=%s', sorted(sensitive_words_cache.keys()))


def get_sensitive_words(vocabulary: str = '') -> List[str]:
    """取某个词表的关键词。**首次调用时懒加载**。"""
    if not sensitive_words_cache:
        reload_black_list()
    if not vocabulary:
        return []
    return sensitive_words_cache.get(vocabulary, [])


def _read_black_list(path: str = '') -> Dict[str, List[str]]:
    black_dict: Dict[str, List[str]] = {}
    blacklist_parent_path = path if path else get_black_list_dir()
    if os.path.exists(blacklist_parent_path):
        for black_file_name in os.listdir(blacklist_parent_path):
            file_name, file_extension = os.path.splitext(black_file_name)
            if file_extension == '.txt':
                black_file_path = os.path.join(blacklist_parent_path, black_file_name)
                logger.info("rag load black, find black file path %s" % black_file_path)
                with open(black_file_path, mode='r', encoding='utf-8') as f:
                    content = f.read()
                keywords = content.split('|#|')
                keywords.sort(key=len, reverse=True)
                black_dict[file_name] = list(keywords)
        return black_dict
    else:
        logger.info('blacklist dir %s not exist, skip loading black list' % blacklist_parent_path)
        return black_dict
