"""解析/切分共享库。

包含自研切分器 / 敏感词 / 异常与 8 种格式的解析器。
依赖方向固定为：

    common / parsers  →  splitter / sensitive  →  corpus  →  split_common

``common`` 保持为叶子层，**不反向依赖** ``corpus``；``split_common`` 是面向系统算子
的薄编排层，放在包根而不是 ``common/`` 下。

对外入口：

* ``parsing.corpus``       —— ``load_corpus_file``（解析 + 切分 + 敏感词）
* ``parsing.split_common`` —— 系统算子用的 ``file_split_common``
* ``parsing.splitter``     —— ``SentenceChunkSplitter``
* ``parsing.sensitive``    —— 敏感词检查器
* ``parsing.exception``    —— ``ParseEmptyError`` / ``SensitiveMsgException``
* ``parsing.parsers``      —— 各格式解析器（docx/pdf/pptx/xlsx/html/md/txt）
* ``parsing.common``       —— 解析器共用工具（create_doc/logutil/pathutil…）

依赖方向：本包**不依赖** ``ingestion`` / ``operators``；上层单向依赖本包。
"""
