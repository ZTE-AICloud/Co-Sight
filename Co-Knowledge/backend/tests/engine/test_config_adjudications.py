"""配置面三条约定的可执行契约。

  1. `dev_mode`：取 `os.environ.get('DEV_MODE', 'false').lower()`，两个 `is_dev_mode()`
     （rag_utils / logutil）读它 —— 漏配会让 DEV_MODE 永远无效。默认 'false'；
     只有显式 DEV_MODE=true 才会给 root logger 加 console handler（见 logutil.get_logger）。
  2. `chat_memory` 的 TTL/maxsize 是**硬编码**，没有任何配置键能改。
     这里把 1000/600 与 1000/3600 钉死 —— 要改成读配置必须先改这份契约。
  3. `rerank_model`：默认 '' 时恒回落到常量 `bge-reranker-large`，
     只有显式设置才改变请求体里的 model 字段。

为什么用子进程：`Config` 是 import 时读环境变量构建的 dict，root logger 的 handler 也是
`tools/log/logutil.py` import 时挂上的 —— 同进程里改 os.environ 影响不到它们，只有另起
进程才能真实测出「DEV_MODE / RERANK_MODEL 到底管不管用」。
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

import engine.settings as config
from engine.cache import chat_memory

# 子进程探针要能 `import engine.*`：唯一 import 根是 `src/`；
# 本文件在 <服务根>/tests/engine/ 下，parents[2] 是服务根。
IMPORT_ROOT = pathlib.Path(__file__).resolve().parents[2] / 'src'

# 子进程里跑的最小探针：把四个可观察量打成一行 JSON。
#   * console handler 判定要排除 FileHandler —— RotatingFileHandler 是 StreamHandler 的
#     子类，不排除的话「只有文件日志」也会被算成有 console 输出。
_PROBE = r'''
import json, logging

from engine.settings import Config
from engine.gateways import llm_proxy_client
from engine import logutil
from engine import rag_utils

console_handlers = [h for h in logging.getLogger().handlers
                    if isinstance(h, logging.StreamHandler)
                    and not isinstance(h, logging.FileHandler)]
print(json.dumps({
    'dev_mode': Config.get('dev_mode'),
    'rag_utils_is_dev_mode': rag_utils.is_dev_mode(),
    'logutil_is_dev_mode': logutil.is_dev_mode(),
    'console_handlers': len(console_handlers),
    'rerank_model': Config.get('rerank_model'),
    'rerank_model_resolved': llm_proxy_client.query_rerank_model('user'),
}))
'''


def _probe(tmp_path, **env_overrides):
    """在干净子进程里 import 一遍运行时，返回探针 dict（DEV_MODE/RERANK_MODEL 由调用方控制）。"""
    env = dict(os.environ)
    env['PYTHONPATH'] = str(IMPORT_ROOT)
    env['LOG_DIR'] = str(tmp_path / 'logs')  # 不往 /tmp/rkb-logs 写
    env.pop('DEV_MODE', None)
    env.pop('RERANK_MODEL', None)
    env.update(env_overrides)
    completed = subprocess.run([sys.executable, '-c', _PROBE], env=env,
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, f'探针子进程失败：{completed.stderr}'
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_dev_mode_absent_uses_defaults(tmp_path):
    """DEV_MODE 未设置：键为 'false'，两个 is_dev_mode() 为 False，
    **不挂 console handler**，重排模型仍回落常量。"""
    probe = _probe(tmp_path)

    assert probe['dev_mode'] == 'false'
    assert probe['rag_utils_is_dev_mode'] is False
    assert probe['logutil_is_dev_mode'] is False
    assert probe['console_handlers'] == 0, 'DEV_MODE 未设置时不应给 root logger 挂 console handler'
    assert probe['rerank_model'] == ''
    assert probe['rerank_model_resolved'] == 'bge-reranker-large'


@pytest.mark.parametrize('dev_mode_value', ['true', 'TRUE'])
def test_dev_mode_true_enables_console_logging(tmp_path, dev_mode_value):
    """DEV_MODE=true 的两个可观察效果：is_dev_mode() 为 True + root logger 有 console
    handler（应用日志同时到 stderr）。'TRUE' 一并钉住 .lower() 的大小写语义。"""
    probe = _probe(tmp_path, DEV_MODE=dev_mode_value)

    assert probe['dev_mode'] == 'true'
    assert probe['rag_utils_is_dev_mode'] is True
    assert probe['logutil_is_dev_mode'] is True
    assert probe['console_handlers'] >= 1, 'DEV_MODE=true 必须挂上 console handler'


def test_dev_mode_key_exists_and_tracks_the_env_var():
    """键必须存在，且取值来自环境变量（默认 'false'）并小写化。"""
    assert 'dev_mode' in config.Config
    assert config.Config['dev_mode'] == os.environ.get('DEV_MODE', 'false').strip().lower()


def test_rerank_model_env_is_honoured(tmp_path):
    """RERANK_MODEL 设置后，请求体里的模型名用它（否则该变量会被静默忽略）。"""
    probe = _probe(tmp_path, RERANK_MODEL='my-reranker-v2')

    assert probe['rerank_model'] == 'my-reranker-v2'
    assert probe['rerank_model_resolved'] == 'my-reranker-v2'


def test_rerank_model_key_exists():
    assert 'rerank_model' in config.Config


def test_chat_memory_ttl_and_maxsize_match_the_original_hardcoding():
    """这组数字是**硬编码约定**，不是随手写的常数 ——
    改动它们等于改变多轮会话缓存的寿命/容量，必须连同这份契约一起改。
    """
    assert chat_memory.user_chat_question_cache.maxsize == 1000
    assert chat_memory.user_chat_question_cache.ttl == 600
    assert chat_memory.user_chat_question_history_cache.maxsize == 1000
    assert chat_memory.user_chat_question_history_cache.ttl == 3600
