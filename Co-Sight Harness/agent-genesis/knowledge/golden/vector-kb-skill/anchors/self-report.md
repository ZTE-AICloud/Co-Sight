---
mode: create
skill_or_agent_name: vector-kb-skill
anchored_mode: K3-KB-Backed
summary:
  verdict: PASS
  file_counts:
    generated: 5
revision_rounds: 0
---

# self-report（vector-kb-skill 过程锚）

> 外部启发锚（derived）——本包源自外部参照库 golden-examples 的
> milvus-rag-skill 蒸馏重塑, 非本仓库构建产物, anchors 标 derived: true。

## 入池留痕（REFLUX.md §3 七步）

1. **选件**: 源 SKILL.md 268 行 + 4 脚本共 1432 行, 形态完整
   （技能说明 + 脚本 + 示例）, 有前置条件/使用流程可补过程锚。
2. **旧词汇重映射**: 源的品牌技能名 → `vector-kb-skill`; 构建器类名
   `MilvusCollectionBuilder` → `VectorCollectionBuilder`; 连接参数
   localhost 默认 → `VECTOR_DB_URI`/`VECTOR_DB_TOKEN` 用户凭据契约位。
3. **挂靠**: mode_id=K3-KB-Backed（货架位）, anchor_fit=real——技能职责
   即"知识库支撑"（集合创建/入库/检索全链路）, 是 K3 的纯正实现。
4. **重塑改造**: 1432 行实现蒸馏为骨架模板——接口形状与职责边界保留,
   实现体明标"实现位"不搬运; 身份消毒: 快照与锚件零源仓名/品牌名残留
   （provenance 如实记录来源）。pool 成员一律本仓库模板资产（R8）。
5. **补锚**: 本 build-plan（5 file 块, invariants 按实际字面量）+ 本 report。
6. **manifest**: 按 schema 全字段, acceptance 4 条。
7. **准入**: G028 skill-build 档（见下）。

## G028 准入记录

```bash
echo '{"profile":"skill-build","output_dir":"knowledge/golden/vector-kb-skill/output-snapshot"}' | bash scripts/gates/g028-exit-sanity.sh
```

verdict 与 concerns 如实回填 manifest known_concerns（单引号标量）。

## 交付描述

单 Skill 包（skill 线, 蒸馏骨架形态）: SKILL.md（前置条件 + 用户凭据
契约位 + 预设场景 + 使用流程 + 限制如实声明）+ scripts/check_env.py
（fail-closed 环境检测）+ scripts/kb_builder.py（构建器骨架, 凭据 env
注入, 密钥缺失显式抛错）+ scripts/insert_data.py（滑窗切块入库骨架）+
references/retrieval.md（检索引用三字段契约）。
