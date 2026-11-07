"""算子插件变更监听（**关闭**，保留模块边界）。

热加载用户上传的自定义算子包需要三样前置件：Kafka、`confluent_kafka`、
以及指向算子包目录的生产者。本部署三样都没有，且自定义算子包这条链本身是断的：
上传的是「算子包」（`.py` + `config.json`），runtime 期望的是**解压后的目录**，
两侧没有桥。所以 `rag_operator_loader` 明确只认内置算子（`operator_packages`），
自定义算子直接报错。

保留这个模块（而不是让文件消失）是为了让模块路径仍然存在、且**边界写清楚**：
将来真要支持自定义算子，需要补三样东西 —— 算子的分发与解压（谁来写 PVC/目录）、
Kafka（或任何变更通知）、以及 `rag_operator_loader` 里的包解析。到时候替换本文件即可。
"""
from engine.logutil import logger

#: 供调用方/自检查询用：本构建不启动插件监听。
#: 这是**刻意保留的显式 stub 边界**（零引用不是漏删）：它与 `start_plugins_listener`
#: 一起，把「插件能力去哪了」钉成可查的常量而非口头约定 ——
#: `start_plugins_listener` 由 `rag_operator_loader` 转出（供 vendored 代码从原位置导入），
#: 本常量在设计中用于标记「监听器已关闭」。
#: 别把二者当死代码清掉；要恢复插件能力时替换本文件（见上方模块注释）。
PLUGIN_LISTENER_ENABLED = False


def start_plugins_listener() -> None:
    """空实现：不消费 Kafka，也不阻塞。

    刻意**不抛异常也不阻塞**：调用方（启动流程）拿到的行为是「没有这个线程」，
    而不是启动期崩溃。
    """
    logger.info('plugin change listener is disabled in this build '
                '(no Kafka, no custom operator packages); see %s', __file__)
