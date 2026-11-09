"""Skill 结构层重构 — Plan 草稿自动生成器。

对标 d7bcf0da 实战案例(session:d7bcf0da-0160-485e-8cf0-9f015a73bf48),
本模块基于关系树自动生成 7 步 refactor plan 草稿(refactor_plan_draft.md),
CC 在 plan mode 仍需批准/微调,但不必从零合成。

d7bcf0da 7 大类改动(每次 refactor 都应覆盖):
  1. frontmatter description 4 要素公式
  2. §3 硬约束 + §7 任务完成标准外置到 references/execution-rules.md
  3. 内联代码精简(§1 §2 §4 §5.1 §5.2 §6.2 → 对应外移到 skill-assets/router/README/io-contract)
  4. 引用闭合性验证 + orphan 文件合并到 references/lookup-rules/manifest.json
  5. scripts/ 工具层合并(对标 d7bcf0da: common+error_handler+utils+config → lib.sh)
  6. 新增 references/{router,io-contract,skill-assets}.md + templates/README.md
  7. 回归测试 + 出最终报告
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# d7bcf0da 对标 7 大类 FD(每次 refactor 自动覆盖)
D7BCF0DA_FD_TEMPLATES = [
    {
        "id": "FD-001",
        "theme": "frontmatter description 4 要素公式化",
        "severity": "HIGH",
        "principle_ref": "docs/重构原则-skill分层与目录结构.md §5",
        "必做": "把 SKILL.md L1 frontmatter 的 description 改成「做什么+何时触发+输入+输出」公式,长度 30~1024 字符",
        "参考案例": "d7bcf0da: description 4 要素,202 字符",
    },
    {
        "id": "FD-002",
        "theme": "§3 硬约束外置到 references/execution-rules.md",
        "severity": "HIGH",
        "principle_ref": "docs/重构原则-skill重构模式库.md 模式 B",
        "必做": "SKILL.md §3 硬约束 9 条 → 单行引用 'references/execution-rules.md §1'",
        "参考案例": "d7bcf0da: §3 内容保留并重排版,可保留 body 或外置",
    },
    {
        "id": "FD-003",
        "theme": "§7 任务完成标准外置到 references/execution-rules.md",
        "severity": "HIGH",
        "principle_ref": "docs/重构原则-skill重构模式库.md 模式 B",
        "必做": "SKILL.md §7 任务完成标准 → 单行引用 'references/execution-rules.md §2'",
        "参考案例": "d7bcf0da: §7 内容保留并重排版",
    },
    {
        "id": "FD-004",
        "theme": "orphan 文件合并到 references/lookup-rules/manifest.json",
        "severity": "HIGH",
        "principle_ref": "docs/重构后检查-Skill完整性验证.md SK-S11 + 实战案例 d7bcf0da",
        "必做": "(a) 删除 references/ 下所有 orphan md 文件(常见为组件变更拆分规则/* 与子系统间消息处理组件规则/*);(b) 新建 references/lookup-rules/manifest.json,合并所有规则到结构化 JSON;(c) 配套新增 scripts/load_rule.sh,按规则类型 + id 查询",
        "参考案例": "d7bcf0da: 删除 8 个 orphan md,合并为 67 行 manifest.json",
    },
    {
        "id": "FD-005",
        "theme": "scripts/ 工具层合并(common+error_handler+utils+config → lib.sh)",
        "severity": "HIGH",
        "principle_ref": "docs/重构后检查-Skill完整性验证.md SK-S12(脚本 source 链一致性)",
        "必做": "(a) 新建 scripts/lib.sh,合并 BASE_DIR / 日志机制 / 通用工具 / 业务常量与映射表 / 路径推导 5 大块;(b) 删除 common.sh / error_handler.sh / utils.sh / config.sh(被 lib.sh 合并);(c) 修改所有引用这 4 个脚本的 .sh 文件,把 'source if [ -f] config.sh' 块改为 'source lib.sh' 直接调用(消除 if 块残留)",
        "参考案例": "d7bcf0da: 合并为 353 行 lib.sh,5 个脚本(if 块)全部改为 source lib.sh",
    },
    {
        "id": "FD-006",
        "theme": "新增 scripts/load_rule.sh + table_io.sh + scripts/README.md",
        "severity": "MEDIUM",
        "principle_ref": "docs/重构原则-skill重构模式库.md 模式 A",
        "必做": "(a) scripts/load_rule.sh 按规则类型 + id 查询 manifest.json;(b) scripts/table_io.sh 表格 IO 工具(md ↔ json 转换、字段抽取);(c) scripts/README.md 脚本目录索引,按 Procedure 列每个脚本的调用时机与参数",
        "参考案例": "d7bcf0da: 3 个新文件,scripts/README.md 提供目录索引",
    },
    {
        "id": "FD-007",
        "theme": "新增 references/router.md(5 Procedure ASCII 流程图外移)",
        "severity": "MEDIUM",
        "principle_ref": "docs/重构原则-skill分层与目录结构.md §3(按需加载)",
        "必做": "(a) SKILL.md §4 执行总览大流程图 → 简化为 5 行 + '详细 ASCII 流程图见 references/router.md';(b) references/router.md 包含完整 ASCII 流程图 + 关键中间层标注(避免 Agent 跳过中间组件)",
        "参考案例": "d7bcf0da: SKILL.md §4 简化为 5 行,router.md 44 行含完整流程图",
    },
    {
        "id": "FD-008",
        "theme": "新增 references/io-contract.md(13 项过程产物路径外移)",
        "severity": "MEDIUM",
        "principle_ref": "docs/重构原则-skill分层与目录结构.md §4(参考文档分类)",
        "必做": "(a) SKILL.md §6.2 过程产物 13 行表格 → 1 行 + '详细路径见 references/io-contract.md';(b) references/io-contract.md 列出所有过程产物的输入/输出/Schema,按 Procedure 分组",
        "参考案例": "d7bcf0da: io-contract.md 列出 13 项过程产物完整路径清单",
    },
    {
        "id": "FD-009",
        "theme": "新增 references/skill-assets.md(资产目录树外移)",
        "severity": "MEDIUM",
        "principle_ref": "docs/重构原则-skill分层与目录结构.md §3",
        "必做": "(a) SKILL.md §2 SKILL 关联资产大目录树(43 行内联)→ 简化为 4 行资产清单表 + '详细目录树见 references/skill-assets.md';(b) references/skill-assets.md 维护者参考,执行时不必读",
        "参考案例": "d7bcf0da: skill-assets.md 50 行含完整目录树",
    },
    {
        "id": "FD-010",
        "theme": "新增 templates/README.md(模板目录索引)",
        "severity": "LOW",
        "principle_ref": "docs/重构原则-skill分层与目录结构.md §3",
        "必做": "templates/README.md 列出每个模板的用途与适用 Procedure,执行时可按需查阅",
        "参考案例": "d7bcf0da: templates/README.md 模板目录索引",
    },
    {
        "id": "FD-011",
        "theme": "SKILL.md 引用闭合性验证(对标 d7bcf0da 实战教训 §1.5)",
        "severity": "HIGH",
        "principle_ref": "docs/重构后检查-Skill完整性验证.md SK-S2 + d7bcf0da 实战教训 §1.5",
        "必做": "(a) grep 提取 SKILL.md 所有 references/scripts/templates 引用,逐一检查文件存在性,100% 闭合;(b) 跨 Skill 引用(如 .specify/scripts/...)加显式说明行,不计入本 Skill 引用闭合性",
        "参考案例": "d7bcf0da: 修复 1 个断链(collect_related_instances.sh)",
    },
    {
        "id": "FD-012",
        "theme": "scripts/ source 链一致性预检(对标实战教训 §1.5)",
        "severity": "MEDIUM",
        "principle_ref": "docs/重构后检查-Skill完整性验证.md SK-S12(新增)",
        "必做": "在合并/删除 scripts/ 源文件前,先 grep -rn 'source\\|if.* -f' scripts/ 列出所有引用点,确认每个引用都已同步,避免 5 个脚本残留 if -f config.sh 块导致 exit 1",
        "参考案例": "d7bcf0da: SK-S12 5 个脚本残留 if 块被全量修复为 source lib.sh",
    },
    {
        "id": "FD-013",
        "theme": "关键路径/中间层保留验证(对标实战教训 §4.5)",
        "severity": "MEDIUM",
        "principle_ref": "docs/重构后检查-等效性与回归测试.md R-MidLayer(新增)",
        "必做": "在外移详细流程图到 references/router.md 前,先对比 R 链路(原始需求链路 vs router.md 中间层),确保 router.md 含完整中间层(不跳 SMC/FCS/XC 等)",
        "参考案例": "d7bcf0da: 1/6 需求中间层被 Agent 跳过,router.md 加 ⚠️ '必须包含中间组件' 标注",
    },
]


def build_plan_draft(
    skill_root: Path,
    relation_tree: dict,
    skill_md_text: str = "",
    skill_md_path: Optional[Path] = None,
) -> str:
    """基于关系树自动生成 7 步 refactor plan 草稿(对标 d7bcf0da 7 大类)。

    Args:
        skill_root: Skill 根目录(从 --skill-path 解析)
        relation_tree: 关系树 dict(从 skill_file_relations.json 读取)
        skill_md_text: SKILL.md 全文(用于 frontmatter 描述公式化 + 行数判断)
        skill_md_path: SKILL.md 绝对路径(可选,用于 frontmatter 解析)

    Returns:
        7 步 plan 的 Markdown 字符串
    """
    stats = relation_tree.get("stats", {})
    files = relation_tree.get("files", [])
    orphans = relation_tree.get("orphans", [])
    clusters = relation_tree.get("clusters", [])

    # 基础数据汇总
    file_count = stats.get("file_count", 0)
    edge_count = stats.get("edge_count", 0)
    orphan_count = stats.get("orphan_count", 0)
    md_count = stats.get("md_count", 0)
    code_count = stats.get("code_count", 0)
    max_indegree = stats.get("max_indegree", 0)
    max_outdegree = stats.get("max_outdegree", 0)
    cluster_count = stats.get("cluster_count", 0)

    # 找 SKILL.md 文件
    skill_md_file = next((f for f in files if f.get("is_skill_md")), None)
    skill_md_lines = skill_md_file.get("line_count", 0) if skill_md_file else 0
    skill_md_bytes = skill_md_file.get("size_bytes", 0) if skill_md_file else 0

    # 找 references/scripts/templates 数量
    ref_count = sum(1 for f in files if f.get("in_references"))
    script_count = sum(1 for f in files if f.get("in_scripts"))
    tpl_count = sum(1 for f in files if f.get("in_templates"))

    # 生成 FD 列表(基于关系树动态调整)
    findings = []
    for fd in D7BCF0DA_FD_TEMPLATES:
        finding = dict(fd)
        # 动态调整
        if fd["id"] == "FD-004" and orphan_count == 0:
            finding["applicable"] = False
            finding["note"] = f"无 orphan 文件({orphan_count} 个),跳过此 FD"
        else:
            finding["applicable"] = True
        findings.append(finding)

    # 生成 plan markdown
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    orphan_list = "\n".join(f"- `{o}`" for o in orphans[:20]) or "- (无)"

    # 静态代码块(避免 f-string 反斜杠问题)
    code_block_static = r"""```bash
# SK-S1 结构完整性
python3 -c "import yaml; yaml.safe_load(open('SKILL.md').read().split('---')[1])"

# SK-S2 引用闭合性 100%
grep -oE '(references|scripts|templates)/[a-zA-Z0-9_./-]+\.(md|py|sh|json|yaml|yml)' SKILL.md | sort -u | while read p; do
  [ -f "$p" ] || [ -d "$p" ] || echo "MISSING: $p"
done

# SK-S3 无占位符
grep -cE '\b(TODO|TBD|FIXME)\b|\{\{.*\}\}' SKILL.md references/*.md

# SK-S8 Design Form(SKILL.md body ≤ 300 行)
wc -l SKILL.md

# SK-S10 Anthropic 规范(L3 加载链 100%)
for f in references/*.md; do
  grep -q "$(basename "$f")" SKILL.md || echo "UNREFERENCED: $f"
done

# SK-S12 脚本 source 链一致性(对标 d7bcf0da 实战教训)
grep -rn "^source\|if.* -f.*\.sh" scripts/ | head -20
```"""

    plan_md = f"""# {skill_root.name} Skill 重构 Plan 草稿(自动生成)

> ⚠️ **本文件由 `static_plan_drafter.py` 自动生成,基于 d7bcf0da 实战案例 7 大类。**
> CC 在 plan mode 仍需根据实际情况微调(每个 Step 的 4 字段),但不必从零合成 plan。
> 生成时间:{today}
> 实战参考:[d7bcf0da session 案例](docs/重构案例-d7bcf0da-Skill组件间流程设计.md)

---

## §0 现状(基础数据)

| 指标 | 值 |
|---|---|
| Skill 路径 | `{skill_root}` |
| 文件总数 | {file_count}({md_count} md + {code_count} code/sh) |
| 引用边数 | {edge_count} |
| Orphan 文件数 | {orphan_count} |
| 簇数 | {cluster_count} |
| max_indegree | {max_indegree} |
| max_outdegree | {max_outdegree} |
| SKILL.md 体积 | {skill_md_lines} 行 / {skill_md_bytes} 字节 |
| references/ 文件 | {ref_count} |
| scripts/ 文件 | {script_count} |
| templates/ 文件 | {tpl_count} |

**Orphan 文件列表**(可能为死代码,FD-004 决定是否合并到 manifest.json):
{orphan_list}

**before_skill/ 快照**:与 diff 报告一致(workspace/before_skill/{{SkillName}}/)
**回滚源**:workspace/before_skill/{{SkillName}}/

---

## §1 7 步实施计划(对标 d7bcf0da 7 大类)

"""
    for i, fd in enumerate(findings, 1):
        applicable = fd.get("applicable", True)
        if not applicable:
            plan_md += f"### Step {i}:{fd['theme']}(跳过,因不适用)\n\n> 注:{fd.get('note', '不适用')}\n\n"
            continue
        plan_md += f"""### Step {i}:{fd['theme']}
**覆盖**:`{fd['id']}`({fd['severity']})

| 字段 | 内容 |
|---|---|
| **操作** | {fd['必做']} |
| **不改** | SKILL.md 其他章节(非此 FD 涉及) + references/ 中已有文件的具体内容(仅新增) |
| **before** | (见 SKILL.md L<line> + references/ 现状 + scripts/ 现状) |
| **after** | (执行操作后的预期产物) |
| **验收** | `wc -l SKILL.md`(应减少 30+ 行)+ `bash -n scripts/lib.sh`(语法 OK)+ `python3 -c "import json; json.load(open('references/lookup-rules/manifest.json'))"`(JSON 合法) |
| **回归** | 跑 6 项 SK-S 静态验证(SK-S1/S2/S3/S8/S10/S12)+ 跑 3 个 R-N 场景(R-ScriptLink/R-MidLayer/R-IOContract) |

> **参考案例**:`{fd['参考案例']}`
> **principle_ref**:`{fd['principle_ref']}`

---

"""
    plan_md += f"""## §2 关键设计资产保留

| 资产 | 保留位置 | 验证方法 |
|---|---|---|
| 5 个 Procedure 顺序链 | SKILL.md §4 简化为 5 行 + references/router.md 含完整流程图 | grep "Procedure [1-5]" SKILL.md + references/router.md |
| 上下文预算感知 | references/execution-rules.md §1 硬约束 #7 | grep "CONTEXT_EXHAUSTED" references/execution-rules.md |
| Procedure 完成校验 | references/execution-rules.md §1 #8 + §2 #7 | bash 校验脚本触发 |
| 13 个过程产物路径 | references/io-contract.md | 路径完整性 grep |
| 资产目录树 | references/skill-assets.md(执行时不读) | 文件存在性 check |
| 5 个 Templates 模板 | templates/README.md 索引 + 5 个 md 文件 | ls templates/*.md |

---

## §3 新增/删除/保留文件清单

### 3.1 新增文件(预计 8-10 个,对标 d7bcf0da)

| 文件 | 来源 Step | 用途 |
|---|---|---|
| `references/execution-rules.md` | Step 2 | 收纳 §3 硬约束 + §7 任务完成标准 |
| `references/lookup-rules/manifest.json` | Step 4 | 合并所有 orphan md 的结构化规则清单 |
| `scripts/load_rule.sh` | Step 6 | 按规则类型 + id 查询 manifest.json |
| `scripts/table_io.sh` | Step 6 | 表格 IO 工具(md ↔ json) |
| `scripts/lib.sh` | Step 5 | 合并 common+error_handler+utils+config 的统一库 |
| `scripts/README.md` | Step 6 | 脚本目录索引 |
| `references/router.md` | Step 7 | 5 Procedure ASCII 流程图 |
| `references/io-contract.md` | Step 8 | 13 项过程产物路径清单 |
| `references/skill-assets.md` | Step 9 | 资产目录树(执行时不读) |
| `templates/README.md` | Step 10 | 模板目录索引 |

### 3.2 删除文件(预计 4-8 个)

| 文件 | 来源 Step | 替代方案 |
|---|---|---|
| `references/组件变更拆分规则/*.md`(3 个) | Step 4 | manifest.json 合并 |
| `references/子系统间消息处理组件规则/*.md`(5 个) | Step 4 | manifest.json 合并 |
| `scripts/common.sh` | Step 5 | lib.sh 合并 |
| `scripts/error_handler.sh` | Step 5 | lib.sh 合并 |
| `scripts/utils.sh` | Step 5 | lib.sh 合并 |
| `scripts/config.sh` | Step 5 | lib.sh 合并 |

### 3.3 保留文件(主体内容,仅改部分章节)

| 文件 | 来源 Step | 改动点 |
|---|---|---|
| `SKILL.md` | Step 1+2+3+7+8+9 | description 4 要素 / §3 §7 外置 / §1 §2 §4 §5.1 §5.2 §6.2 简化为引用 |
| 14 个 scripts(除 common/error_handler/utils/config) | Step 5 | 把 `source if [ -f] config.sh` 块改为 `source lib.sh` |

---

## §4 验证方案

### 4.1 静态验证(Step X 自动跑)

{code_block_static}

### 4.2 行为层验证(分数不退化)

| R-N 场景 | 验证方法 | 对应 Step |
|---|---|---|
| R-ScriptLink | 跑每个修改后的 scripts/*.sh 不应 exit 1 | Step 5 |
| R-MidLayer | 对比 R 链路(原始 vs router.md),关键中间层不跳 | Step 7 |
| R-IOContract | 13 项过程产物路径 100% 可达 | Step 8 |
| R-Description | description 长度 30~1024 + 含 4 要素 | Step 1 |
| R-FileRefs | 跨 Skill 引用加显式说明,不计入本 Skill 引用闭合性 | Step 11 |

### 4.3 预期收益(对标 d7bcf0da)

| 指标 | d7bcf0da 实际 | 本次预期 |
|---|---|---|
| 文件数变更 | 33 个 | 30+ |
| 新增行数 | +752 | +700+ |
| 删除行数 | -970 | -800+ |
| SKILL.md 行数 | 243 → ~110 | 243 → ~150 |

---

## §5 与 d7bcf0da 实战案例对齐

| 类别 | d7bcf0da 做法 | 本次 plan 是否覆盖 |
|---|---|:---:|
| description 4 要素 | ✓ | ✅ Step 1 |
| §3 §7 外置 | ✓(保留并重排版) | ✅ Step 2+3(外置) |
| orphan 合并 manifest.json | ✓(删 8 个 md) | ✅ Step 4(按 orphan_count 动态) |
| scripts/ 工具层合并 | ✓(lib.sh 353 行) | ✅ Step 5 |
| 路由/IO 契约/资产目录 | ✓(3 个新 references) | ✅ Step 7+8+9 |
| 模板目录索引 | ✓ | ✅ Step 10 |
| 引用闭合性 | ✓ | ✅ Step 11 |
| 脚本 source 链一致 | ✓ | ✅ Step 12(实战教训 §1.5) |
| 中间层保留验证 | ✓ | ✅ Step 13(实战教训 §4.5) |

---

## §6 关键文件清单(本 plan 修改/新建的所有文件)

- 修改:SKILL.md + 14 个 scripts/*.sh
- 新建:references/{{execution-rules,lookup-rules/manifest.json,router,io-contract,skill-assets}}.md + scripts/{{lib,load_rule,table_io}}.sh + scripts/README.md + templates/README.md
- 删除:references/组件变更拆分规则/* + references/子系统间消息处理组件规则/* + scripts/{{common,error_handler,utils,config}}.sh

**回滚源**:workspace/before_skill/{{SkillName}}/

---

> **CC 行动建议**:
> 1. 在 plan mode 打开本文件
> 2. 根据实际 SKILL.md 内容 + scripts/ 现状,微调每个 Step 的 before/after 段
> 3. ExitPlanMode 让用户批准
> 4. 用 Read + Edit 工具应用
> 5. 跑 SK-S1/S2/S3/S8/S10/S12 + R-ScriptLink/R-MidLayer/R-IOContract 验证
> 6. 出最终报告 + 调 orchestrator --mode refactor-diff-report 生成 diff HTML
> 7. 在最终报告里对照 d7bcf0da 案例,记录"做了多少 / 还差多少"
"""
    return plan_md


def write_plan_draft(
    plan_md: str,
    output_path: Path,
) -> None:
    """写 plan 草稿到 refactor_plan_draft.md。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(plan_md, encoding="utf-8")
    logger.info("refactor plan 草稿已生成:%s", output_path)


def run_plan_draft(
    skill_root: Path,
    relation_tree: dict,
    output_path: Path,
    skill_md_path: Optional[Path] = None,
) -> Optional[Path]:
    """从关系树生成 plan 草稿并写出,返回 output_path 或 None(失败)。"""
    skill_md_text = ""
    if skill_md_path is None:
        skill_md_path = skill_root / "SKILL.md"
    if skill_md_path.exists():
        try:
            skill_md_text = skill_md_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("SKILL.md 读取失败:%s;plan 草稿将不含 description 公式化建议", e)

    try:
        plan_md = build_plan_draft(skill_root, relation_tree, skill_md_text, skill_md_path)
        write_plan_draft(plan_md, output_path)
        return output_path
    except Exception as e:  # noqa: BLE001
        logger.warning("plan 草稿生成失败: %s", e)
        return None