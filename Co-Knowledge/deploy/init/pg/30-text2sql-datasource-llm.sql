-- 数据源级「SQL 生成模型」（LLM）。
--
-- 与 embedding 不同：embedding 决定向量维度、首次构建后固定；LLM 只影响
-- 运行期「问题 → SQL」的生成，随时可改，也不影响已发布版本。
-- 留空（NULL）= 跟随部署默认生成模型；请求体里显式带的 model 仍可覆盖它。
--
-- 幂等：空卷 initdb 与已有部署手工执行都可以。

BEGIN;

ALTER TABLE text2sql.t2s_datasource
    ADD COLUMN IF NOT EXISTS llm_model VARCHAR(255);

COMMENT ON COLUMN text2sql.t2s_datasource.llm_model IS
    'Data source level LLM used for SQL generation; NULL = deployment default, editable at any time';

COMMIT;
