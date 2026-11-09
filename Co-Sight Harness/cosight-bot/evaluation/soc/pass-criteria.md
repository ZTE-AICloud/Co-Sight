# CoSightBot SOC 验收标准（pass-criteria）

> 验收用例 AC-04、AC-05 与回归用例（PKM 链用例见 cosightbot-pkm 包），判定方法与通过阈值。执行方式：全新工作目录按 README quickstart 走一遍，逐条对照判定。每条用例给出 Given-When-Then 与**程序化判定**（可通过脚本/退出码验证的部分）。

## AC-04 SOC KB 构建

- **Given**：`knowledge/sample-kb/` 示例源目录
- **When**：`kb_cli.py add-builtin` + `kb_cli.py build`
- **Then**：向量库就绪且注册表写入

| 维度 | 判定方法 | 通过阈值 |
|---|---|---|
| 注册 | `add-builtin` exit 0，config 落 `data/workspace-soc/builder/configs/` | 是 |
| 构建产物 | `build` exit 0，`data/workspace-soc/kbs/<kb_id>/` 含两个 lancedb 表 | 双表齐备 |
| 注册表 | `soc_kb_registry.json` 含该 KB 且 enabled=true | 是 |
| 就绪校验 | `list`/`status` 显示 built=true / ready | 是 |
| 可检索 | `multi_kb_retrieve` 返回 nodes > 0 且 kb_id 正确 | ≥1 条命中 |

## AC-05 SOC 应答流水线

- **Given**：已就绪 KB + 示例标书 `knowledge/sample-tender.xlsx`
- **When**：extract → respond → review → fill
- **Then**：产出 `<stem>-应答后.xlsx`（不覆盖原件），应答带来源标注

| 维度 | 判定方法 | 通过阈值 |
|---|---|---|
| 提取 | extract validate.py exit 0；条目数 = 标书真实需求行数 | 一致 |
| 应答 | respond exit 0；命中条目带 matched_req + source_file | 命中条目 100% 有来源 |
| 复核 | review exit 0；向量误匹配条目被标 conflict=true | 误匹配全被拦 |
| 回填 | fill validate.py exit 0；原 Excel 未改动（S-06） | exit 0 + 原件哈希不变 |
| 漂移拦截 | 人为构造坏 JSON（非法 compliance/空 items/重复行），validate 必须 exit 1 | 全部拦截 |

## 回归用例（可重复执行）

| # | 场景 | 期望 |
|---|---|---|
| R-01 | extract validate 喂非法 compliance 值 | exit 1 |
| R-02 | extract validate 喂空 items / 非 JSON / 重复 sheet+row | exit 1 |
| R-03 | fill validate 产物缺失 / 产物=原件路径 | exit 1（S-06） |
| R-04 | 多 sheet 标书（部分 sheet 非应答页）提取 | 非应答页被跳过且条目数正确 |
| R-05 | 含章节标题行（1 / 1.1 / 1.2 编号结构）标书提取 | 标题行不计入条目 |
| R-06 | 知识库未构建时跑 respond/answer | exit 1 + 引导构建，无占位产物 |
| R-07 | review 在 LLM 全失败时 | 失败率 >30% → exit 1（产物仍落盘） |
