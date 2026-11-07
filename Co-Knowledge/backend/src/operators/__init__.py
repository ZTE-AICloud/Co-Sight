"""内置系统算子入口包（由 ``ingestion/split/operator_all.json`` 注册）。

每个子目录是一个算子入口，约定 ``main.py`` 暴露注册表 ``operator_function`` 指定的
函数；``system_split_manager`` 按**文件路径**加载（与用户上传算子的契约一致）。

依赖约束：算子入口只允许依赖 ``parsing`` / ``llm`` 等基础层，**不得**依赖
``ingestion`` 框架（那会形成插件 → 执行器的反向依赖）。
"""
