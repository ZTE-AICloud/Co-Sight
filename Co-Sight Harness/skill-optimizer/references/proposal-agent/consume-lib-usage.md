# consume_lib 全局视角知识库使用指南

> **由 proposal-agent.md 引用。开工前 Read。**
> **不为了降本而降本** —— 这是"提分"工具,核心目标是发现跨 case 的全局方法论。

## 前提

若 prompt 中给出 `consume_lib_path`(从 `taskid_root/config.json` 读),本节适用。未给则跳过,直接走工作流。

## 定位

`consume_lib` 是**全局知识**,不是用来逐 case 修补模板的工具。

**目的**:跳出当前 case 的细节局限,站在领域方法论 / 反模式 / 最佳实践的高度,重新审视优化方向 —— 避免在某个 case 的局部修补里打转。

## 使用方式

开工前**必须**先做,**全部用并发工具调用**:

### 1. 并发探查(1 个 message 发 N 个 tool call)

```bash
# 全局结构
ls -la {consume_lib_path}/
find {consume_lib_path} -maxdepth 2 -type d | head -30

# 反模式扫描
grep -rE 'TODO|FIXME|hardcode' {consume_lib_path} | head -20
```

**并发 Read**(1 个 message 发 3-5 个 Read):
- 方法论/README/反模式/规范等代表性文件

### 2. 提炼(LLM 内部完成,不需 tool call)

- **领域方法论**:scripts/ 抽取时机、渐进式披露、章节组织
- **反模式清单**:硬编码 case_id、纯加规则段、edit_exact 盲目新增
- **跨场景共性原则**:异常处理矩阵、必填字段校验、早退规则

### 3. 带着全局视角再看 phase3-eval

并发 Read 多 case 的 `differences[]` / `diff_notes`:
- **如果发现某 case 的问题其实是全局原则没贯彻**(如多处应代码化却写成规则段)→ 改一次修一族,modifications 必填 reason 含"全局原则"关键字
- **如果读完知识库没有发现任何高于当前 case 的方法论/原则** → 明确说"本次无更高视角可补",沿用常规 case-by-case 修补

## 反约束(违反 REWORK)

- ❌ 严禁照抄业务专有内容(具体 case_id / 业务名 / 协议细节硬编码进 Skill)
- ❌ 严禁只读不写、读了一堆知识但 modifications 还是 case-by-case 修补
- ❌ 严禁把 consume_lib 当 case-by-case 模板复制

## self_check.knowledge_used 必填

在 `optimization_summary.md` 头部填:

```json
{
  "consume_lib_path": "{consume_lib_path 或 null}",
  "global_principles_extracted": ["方法论1", "方法论2", ...],
  "one_fix_for_family": "M1 修的是哪一族 case 的共性问题"
}
```