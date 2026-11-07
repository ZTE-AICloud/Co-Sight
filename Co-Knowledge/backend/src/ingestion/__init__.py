"""文档处理模块（解析 → 清洗 → 切分 → 抽图管线与算子沙箱）。

管线的入口是 ``ingestion/runtime.py``；后端以**进程内函数调用**使用本包。

## 导入约定

本包内的模块**一律用绝对导入** ``from ingestion.<子包> import ...``。

## 与共享解析包的关系

解析/切分库不在本包内，而与算子入口一起放在 import 根（``src/``）：

  * ``parsing``    —— 格式解析 / 切分 / 敏感词库
  * ``operators``  —— 系统算子入口包（``text_split``）
  * ``model``      —— 模型网关调用

它们由 ``split/operator_all.json`` 的 ``operator_module`` 字段按名字引用，
所以必须留在能让那种解析方式命中的位置。
"""
