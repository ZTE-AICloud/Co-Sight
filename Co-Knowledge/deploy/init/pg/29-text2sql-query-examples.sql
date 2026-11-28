-- 数据源级「示例问题」：AI 辅助生成后保存，提问框直接展示。
--
-- 之前示例问题只能从表/指标名硬拼（「查询 kb_directory 的前 20 条记录」），
-- 既不像业务问题，也不随语义层更新。生成一次存在数据源上，前端优先使用它。
--
-- 幂等：已有部署可直接执行。

BEGIN;

ALTER TABLE text2sql.t2s_datasource
    ADD COLUMN IF NOT EXISTS query_examples JSONB NOT NULL DEFAULT '[]';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 't2s_datasource_query_examples_check'
    ) THEN
        ALTER TABLE text2sql.t2s_datasource
            ADD CONSTRAINT t2s_datasource_query_examples_check
            CHECK (jsonb_typeof(query_examples) = 'array');
    END IF;
END
$$;

COMMIT;
