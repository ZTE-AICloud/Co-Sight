# vendor 的 tiktoken 词表（cl100k_base）

## 为什么在这里

镜像里**没有** tiktoken 的默认缓存目录（`/root/.cache/tiktoken` 不存在）。
tiktoken 默认会在第一次截断时去 `openaipublic` 下载词表，离线镜像会直接失败
（失败点在合成路径深处，症状是「提问报错」而非「缺依赖」）。

所以词表随包 vendor，由 `primitives/components/token_split.py:get_tokenizer()` 指向本目录
（仅当环境变量 `TIKTOKEN_CACHE_DIR` 未显式设置时，与库的写法保持一致）。

## 出处与许可

* 文件 `9b5ad71b2ce5302211f9c61530b329a4922fc6a4`（1 688 126 字节）是 tiktoken 的缓存文件，
  文件名是**下载 URL 的 sha1**（tiktoken 的缓存命名规则），内容为 cl100k_base 的 BPE 词表。
* 拷贝自 `llama-index-core==0.10.31` 的 wheel：`llama_index/core/_static/tiktoken_cache/`。
* 上游许可：tiktoken（MIT License, Copyright (c) 2022 OpenAI, Shantanu Jain；
  完整许可文本见仓库根目录 `THIRD-PARTY-NOTICES.md`）。
* 校验方式：本目录的文件与库内置文件**字节级相同**（`cmp` 通过），且
  `test_primitives_token_split.py` 里有与库分词结果的差分断言。

## 不要做的事

* **不要**删掉本目录或让它被 `.dockerignore` 排除 —— 症状是"离线环境提问失败"。
* **不要**改成运行时下载（`tiktoken` 默认行为）—— 本仓按离线交付设计。
