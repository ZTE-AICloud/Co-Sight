"""文件导入的异步任务链（上传 → 解析 → 切分 → 向量化 → 索引）。

模块结构：

* :mod:`wrapper` —— 任务对象与状态机
* :mod:`queue` —— 门面：``infrastructure.tasks`` 的 ``file_import`` 车道 + 重试 3 次 +
  统一任务表 ``task`` 持久化（``kb_import_task`` 是只读兼容视图）
* :mod:`executor` —— 处理链 runner 与大文件重试延迟
* :mod:`chain` —— 正序执行、失败时**逆序回滚**（含失败的那个 handler 自己）

**「重启不重投」是刻意保留的语义**：进程挂掉后内存队列里的任务
不会重新执行，``task_center.task`` 里的 RUNNING/PENDING 行只会成为查询可见的僵尸记录。
改掉它更"正确"，但属行为变更。
"""
