# Skill 常见反模式(通用,不针对特定业务)

> 适用于所有 `/skill_create` 工作流。subagent 写 spec/impl/skill 前必读,自查避免重蹈覆辙。

## 反模式 1:产物不完整(流程类最常见)

**症状**:
- spec §1.3 只列 1 个产物(如 "时序表")
- 但实际业务需要多个产物(流程类需 表格 + 图 + 详细描述)

**根因**:
- subagent 凭 brief 推断,只想到最显眼的产物(表格)
- 遗漏可视化图、详细描述等次要产物
- brief 没显式说明需要哪些产物,subagent 不主动推断

**修复**:
- 写 spec 前,先 Read `knowledge/business_patterns.yaml` 匹配业务模式
- 从匹配模式的 `typical_product_parts.required: true` 读取最少产物数量
- spec §1.3 必须显式列出所有 required 部分
- 每个产物部分对应 spec §4 中独立步骤章节

## 反模式 2:无校验脚本(流程类必含)

**症状**:
- 流程类 Skill 无任何 `scripts/validate_*.py` 脚本
- `run.py` 直接生成产物,跳过校验

**根因**:
- subagent 认为"校验不是 Skill 的责任"
- 实际上校验是 Skill 质量保证的核心环节
- 没有校验就没有"自我纠错"能力

**修复**:
- 流程类 Skill 必须包含 3 类校验脚本(拓扑/内容/产物)
- 详见 `norms/validation_norms.md`
- 每个校验脚本独立,支持 `--input` + `--output` CLI
- 校验失败时支持 revision loop

## 反模式 3:LLM 断点输出字段不完整

**症状**:
- LLM-B 只输出 `insertions[]`
- 但实际还需要 `row_updates[]` + `linkage_changes[]` + `naming_decisions[]`

**根因**:
- subagent 设计 JSON Schema 时只考虑最简单的输出
- 未穷举所有 LLM 需要回答的维度

**修复**:
- 设计 LLM 断点前,先列出"LLM 需要回答的所有问题"
- 每个问题对应 1 个输出维度
- 从 `knowledge/llm_breakpoint_templates.json` 选取模板(非自创)
- **flow_design 综合断点必含 ≥ 3 类操作**(insertions + row_updates + linkage_changes)
- 详见 `norms/llm_breakpoint_norms.md` §多模板组合硬约束

## 反模式 4:阻断无追溯报告)

**症状**:
- 转换步骤遇到"接口文档缺失"或"子系统不匹配"时直接 `sys.exit(1)` 报错
- 错误信息打 stdout 但未落盘,人工调试需重跑

**根因**:
- subagent 只关心成功路径,失败路径无产物
- 阻断是不可恢复错误,需要 trace 帮助定位

**修复**:
- 阻断类错误必须写 `${STATE_DIR}/<step>_block_report.json`(命名约定 `<step_num>_block_report.json`)
- 报告字段:`timestamp` / `block_type` / `row_index` / `direction` / `interface_name` / `interface_doc_path` / `detail` / `suggestion`
- 阻断退出码用专用(0=OK, 1=解析错, 2=文件缺失, 3=校验失败,**4=外部依赖阻断(R5 接口文档缺失/R8 规则缺失)**)
- 详见 `skill-create-guidelines.md` §8 阻断报告模式

## 反模式 5:无 update_doc 反向同步)

**症状**:
- LLM-B 产出 V2 → V3 后,只生成独立结果文件
- 原始需求文档 `req_design_document.md` 不更新或回写
- 用户无法在原节点追溯"流程设计完成"

**根因**:
- subagent 把生成物当成"独立文件"处理
- 实际业务要求 LLM 产出回写到"原需求文档的对应节点"

**修复**:
- 流程类 Skill 的最后步骤必须含"update_doc"动作
- 模式:`assemble_output --update-doc <原文档>` → 在原文档同级目录或特定节点写入/追加产物
- 详见 `skill-create-guidelines.md` §8 update_doc 模式

## 反模式 6:GB 级业务知识库打包进 Skill 已 P0-7 防呆)

**症状**:
- 把整个 consume_lib(GB 级)用 `cp -r` 复制到 Skill 包的 `references/`
- Skill 包膨胀到 GB 级,无法分发

**根因**:
- framework 没有"业务背景/runtime 注入"规范
- subagent 默认走"复制"路径

**修复**:
- 业务背景知识库走 `--consume-lib <abs_path>` 运行时注入,不打包
- 复用源目录(`< 1 MB`)可复制到 `references/`,>1MB 必须 runtime 注入
- 详见 `skill-create-guidelines.md` §7 references 复用源规范 + `validate_skill_scaffold` P0-7 防呆

## 反模式 7:硬编码 `--script_extension`)

**症状**:
- framework `validate_skill_scaffold` 写死 `scripts/run.py` 不识别 `scripts/run.sh`
- 与专家约束"scripts 以 sh 为主"冲突,validate FAIL 但实际可执行

**根因**:
- framework 校验脚本默认脚本扩展名是 Python
- 未考虑业务方可能显式选择非 Python 脚本语言

**修复**:
- expert-guidance 可显式声明脚本语言(`sh` / `py`)
- framework validate 时按声明扩展名匹配
- 详见 `skill-create-guidelines.md` §7.scripts 脚本语言规范

---

## 反模式 8:LLM 断点用 `exit 0`(协议失效,)

**症状**:
- step 写 LLM 任务文件后 `exit 0`("等待响应")
- run.sh 主循环 `if ! bash; then ...` 检测不到 LLM 等待
- 主流程**继续跑后续步骤**,LLM 响应文件被覆盖
- Skill 跑飞,数据丢失

**根因**:
- POSIX 退出码 0 表示"成功",与"等待 LLM 响应"语义冲突
- `! 0 = 1` 进入 `if` 分支,但 `if ! bash` 永远捕获不到 LLM 断点意图
- 死代码:`if [[ $rc -eq 0 ]]; then exit 0; fi` 在 LLM 断点场景下永远走不到

**修复**:
- 用专门的退出码 **100** 作为"LLM 等待"哨兵
- step LLM 等待分支:`exit 100`(不是 `exit 0`)
- run.sh 主循环用 **if-else 显式检测** `if [[ $rc -eq 100 ]]; then exit 0; fi`
- 详见 `llm_checkpoint_sentinel_v1.md`

**参考**:`04_skill_dir/组件间流程设计/` 犯过此错,11 个 bug 之一。

---

## 反模式 9:5 项拓扑校验缺失)

**症状**:
- `step11_validate.sh` 只做"表/图一致性"+"业务流唯一性"2 项
- 变更组件漏掉 → 输出缺失;首行源=内部 → 消息链错;anchor 超界 → 插入位置错;接口待定+flow_type=修改 → 语义矛盾
- 5 类问题**全部逃过校验**,Skill 跑出来结果错

**根因**:
- framework 早期只规范"2 项基础校验"
- 业务流程类 Skill 实际需要 5 项(变更组件完整性/anchor 范围/首末行流向/重复消息对/兜底一致性)
- 通用模式 `topology_validation_v1` 未沉淀到 framework

**修复**:
- 调用通用工具 `scripts/common/validate_topology.sh`(已实现 5 项)
- Skill 自己的 step11 不再写 5 项校验逻辑
- 失败退出码标准化:18=变更组件,19=anchor,20=首末行,15=重复,21=兜底

**参考**:`04_skill_dir/组件间流程设计/` 校验覆盖度 0/5。

---

## 反模式 10:字段值兜底规则缺失通用化, 改名)

> **改名**:原"业务流兜底规则缺失" → "字段值兜底规则缺失",通用化。

**症状**:
- LLM 响应任意关键字段(如 `biz_if` / `category` / `expected_result`)为空时,系统直接 fail
- 缺少"待补充" / "pending" 等通用兜底模板,LLM 偷懒时空字段直接污染产物

**根因**:
- 早期 framework 未规范"LLM 推理失败时如何兜底"
- Skill 设计者凭直觉认为 LLM 一定能推理出关键字段
- 没意识到 LLM 在数据不足时**会输出空字符串**而不是合理推断

**修复**:
- 通用模式 `field_value_fallback_v1` 规范兜底值(参数化):
  - `field_name` / `flag_field` / `flag_value` 由 Skill 传入
  - 默认标识关键词:`待补充` / `pending` / `待定`
  - 默认兜底语义映射:`"待补充" → "新增"`
- 业务场景示例: `business_flow_fallback_v1`(组件间流程设计)
  - 业务流名缺失 → `"{接口名}.接口待定"` + `flow_type=新增`
  - 接口名也缺失 → `"接口待定.业务流"` + `flow_type=新增`
  - 完整兜底 → `"接口待定.${src}_${tgt}.消息交互"` + `flow_type=新增`
- 兜底值含"待补充"标识,topology C5 校验强制关联标志字段为兜底语义值
- Skill 应用兜底时,在 LLM 响应校验块加 jq 检查

**参考**:`04_skill_dir/组件间流程设计/` 无任何字段值兜底。

---

## 反模式 11:校验函数堆 main() 内联(新增,治"校验无独立函数粒度"反模式)

**症状**:
- `validate_topology.py` 把 C1-C5 5 项拓扑校验全部写在 `main()` 内联(`# C1 ...` ... `# C5 ...` 是 main 内的代码块,**没有独立 `check_*` 函数**)
- `validate_table.py` 把 3 项内容校验内联在 main()
- `validate_output.py` 把 6 项产物校验内联在 main()

**根因**:
- 反模式 #2 只规定"流程类 Skill 必含 3 类校验脚本",不规定脚本内部"每个校验项必须拆独立 check_* 函数"
- scaffold 阶段拆分 `step_N_xxx.py` 时仅机械拆 impl 主类方法,不强制拆 impl.main() 内的内联校验块
- 后果:(1) 单项校验无法独立 CLI 调用;(2) 单元测试难写;(3) main() 单点堆积 200+ 行;(4) 失去"单一职责"原则

**修复**:
- `validate_*.py` 内每个独立校验项(C1/C2/C3/C4/C5 等)必须抽为 `check_<item_name>(数据) -> List[error]` 纯函数
- main() 仅调度:`read → for check_id, fn in CHECK_REGISTRY.items(): fn(...) → 组装报告 → exit`
- 必须支持 `--check <item_name>` 单项验证 CLI(例 `validate_topology.py --check C1`)
- `check_*` 函数必须是纯函数(无 IO 副作用,无 print,无 sys.exit)
- 完整代码模式 + 自检清单见 `framework_configs/norms/validation_norms.md` §校验脚本函数粒度强制

**参考**:典型失真形态见最近一次 `/skill_create` 产物的 `step*_validate_topology.py`(其中一项把 5 项 C1-C5 拓扑校验全堆 main() 内联,无独立 check_* 函数)。

---

## 反模式快速对照表

| 反模式 | 检测方式 | 修复方向 |
|--------|---------|---------|
| 产物不完整 | `check-completeness` 检查 spec §1.3 行数 vs `business_patterns.yaml.min_parts` | 显式列出所有 required 产物 |
| 无校验脚本 | `check-completeness` 检查 `scripts/validate_*.py` 数量 | 流程类至少 3 个 validate 脚本 |
| LLM 断点字段不全 | `check-completeness` 检查 JSON Schema required 字段数 ≥ 3 / 字段名 ∈ templates 白名单 | flow_design 综合断点必含 ≥3 类操作 |
| 渲染步骤合并 | 读 spec §4 检查"render_table" / "render_diagram" / "render_detail" 是否独立 | 每个产物部分独立步骤 |
| 阻断无追溯 | check-completeness 检查 `${STATE_DIR}/*block_report.json` 模式 | 阻断必写 `<step>_block_report.json` |
| 无 update_doc | 读 `scripts/*write*.sh` 检查 `--update-doc` 参数 | 流程类最后步骤含 update_doc |
| GB 级业务知识库打包 | validate_skill_scaffold P0-7 防呆:references 单目录 > 1MB FAIL | `--consume-lib` runtime 注入 |
| 硬编码脚本扩展名 | validate_skill_scaffold 检查 `run.${ext}` 可声明 | expert-guidance 显式声明 sh/py |
| **LLM 断点用 exit 0(协议失效)** | Explore agent 探查 `grep -E "exit 0.*LLM"` 应为 0;run.sh 主循环用 if-else + 100 检测 | 用退出码 100 哨兵,详见 `llm_checkpoint_sentinel_v1.md` |
| **5 项拓扑校验缺失** | Step 11 校验覆盖度 check:必须含 C1-C5(变更组件/anchor/首末行/重复/兜底) | 调用 `scripts/common/validate_topology.sh`,详见 `patterns/topology_validation_v1.md` |
| **业务流兜底规则缺失** | LLM 响应校验块 check:biz_if 空时是否触发兜底 | 用 `business_flow_fallback_v1` 模式,`接口待定.X` + `flow_type=新增` |
| **校验函数堆 main() 内联** | `check-completeness` 检查 `validate_*.py` 内 `^def check_` 数量 ≥ 校验项数 + `main()` 函数体 ≤ 30 行 | 每个校验项拆独立 `check_*` 函数 + `--check` CLI 标志,详见 `validation_norms.md` §校验脚本函数粒度强制 |