# Brief 工序模板 — schema（输出契约）

> 消费方: DF1 校验 + CI；字段一经发布即冻结（severity 枚举等）

## 生成工序（3 步）

1. **结构**: `$schema` 声明 + properties（字段/类型/语义）+ required
   【自查】与报告格式规则的术语对齐（字段名跨文件一致，cross 校验会查）
2. **物化字段**: IH3 时含 approval{required,status,dismissed_ids}；DF1 校验步骤引本文件路径
3. **样例对照**: 对照 schemas/runtime-eval.schema.yaml 的结构惯例（**仅插件内部对照路径，禁止写进产物文档**——产物需引用 schema 语义时在 `.claude/schemas/` 建副本并引用副本，G023 cross 会机检产物内 dangling 引用）
   【自查】json.load 可解析 + $schema 存在（G023 json_schema_valid 会机检）

## 落点规则

**哪里用放哪里**: 单一消费者→宿主目录内（`.claude/skills/{name}/` 内或 `.claude/agents/` 旁）；
多消费者→`.claude/schemas/`。**废止根级 `schemas/` 平铺**。

## 自样例

runtime-eval.schema.yaml 为标准样例（已读可跳过；**插件内部路径，非产物引用目标**）。
