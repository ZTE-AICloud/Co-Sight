-- ============================================================================
-- 退役任务兼容视图
--
-- kb_import_task / graph_extract_task / graph_import_task 是三类任务收敛到
-- task_center.task 时留下的只读兼容视图。运行期代码从不读写它们（全部 SQL
-- 直接落在 task_center.task），验收脚本也已改为直查统一任务表；视图上没有
-- INSTEAD OF 触发器，写入本来就报错，删除不影响任何写路径。
--
-- 历史迁移 10/11/14/15 里仍会创建这三个视图（空卷初始化先建后删），这里统一
-- 收口：升级库与新建库的最终形态一致 —— public 下只剩 task_center.task。
-- ============================================================================

BEGIN;

DROP VIEW IF EXISTS public.kb_import_task;
DROP VIEW IF EXISTS public.graph_extract_task;
DROP VIEW IF EXISTS public.graph_import_task;

COMMIT;
