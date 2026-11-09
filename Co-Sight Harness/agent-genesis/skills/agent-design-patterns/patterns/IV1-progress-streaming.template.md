---
pattern_id: IV1
pattern_name: Progress-Streaming
category: interaction
sub_dimension: visibility
selection_rule: "可选。独立于其他交互子维度。"
solves: "执行过程长，用户需要知道当前进展和中间状态"
fills_spec_section: Execution Workflow (进展汇报规则)

variables:
  - name: REPORT_FREQUENCY
    description: "汇报频率——每个阶段/步骤开始和结束时 / 每个子任务完成时 / 定时汇报"
    type: string
    source: user_input
    required: true
    default: "每个阶段/步骤开始和结束时"
  - name: NORMAL_PROGRESS_FORMAT
    description: "正常进展汇报的格式模板"
    type: string
    source: user_input
    required: false
    default: "📍当前阶段 + ✅已完成 + 🔄进行中 + ⏳待执行"
  - name: BLOCKING_REPORT_FORMAT
    description: "阻断/异常时的汇报格式模板"
    type: string
    source: user_input
    required: false
    default: "⛔阻断原因 + 📋已尝试动作 + 🙋需要用户提供"
  - name: MIN_REPORT_INTERVAL
    description: "两次汇报之间的最小间隔（避免刷屏）。不适用时填'N/A'"
    type: string
    source: user_input
    required: false
    default: "每个步骤至少汇报一次"

constraints:
  - "每个阶段/步骤开始和结束时必须汇报"
  - "阻断时必须汇报原因和需要的用户操作"
---

# 进展汇报规则

## 汇报约束
- **汇报频率**：{{REPORT_FREQUENCY}}
- **最小汇报间隔**：{{MIN_REPORT_INTERVAL}}

## 汇报格式

### 正常进展汇报
```
{{NORMAL_PROGRESS_FORMAT}}
```

### 阻断汇报
```
{{BLOCKING_REPORT_FORMAT}}
```

## 汇报内容要求
1. **进度总结**：已完成步骤数/总步骤数
2. **当前状态**：正在执行的步骤名称和描述
3. **中间产出**：已完成步骤的输出文件及状态
4. **预计剩余**：待执行步骤数及预计耗时

## 汇报时机
- 每个阶段/步骤**开始**时 — 告知即将做什么
- 每个阶段/步骤**完成**时 — 告知产出和下一步
- 遇到**阻断/异常**时 — 立即汇报问题和需要的用户操作
- 全部执行**完成**时 — 汇报执行总结

---
# Filled Example

## 汇报约束
- **汇报频率**：每个阶段/步骤开始和结束时
- **最小汇报间隔**：每个步骤至少汇报一次

## 汇报格式

### 正常进展汇报
```
📍当前阶段: [步骤名]
✅已完成: [1/4] 需求澄清 → 需求澄清记录.md
🔄进行中: [2/4] 任务规划 — 正在分析需求生成执行计划...
⏳待执行: [3/4] 分析执行, [4/4] 结果汇总
```

### 阻断汇报
```
⛔阻断原因: 执行计划.json Schema校验失败 — tasks字段缺失required属性
📋已尝试动作: 重新生成执行计划1次，仍不符合Schema
🙋需要用户提供: 请确认执行计划的Schema定义或调整任务拆解粒度
```

## 汇报内容要求
1. **进度总结**：已完成步骤数/总步骤数
2. **当前状态**：正在执行的步骤名称和描述
3. **中间产出**：已完成步骤的输出文件及状态
4. **预计剩余**：待执行步骤数及预计耗时

## 汇报时机
- 每个阶段/步骤**开始**时 — 告知即将做什么
- 每个阶段/步骤**完成**时 — 告知产出和下一步
- 遇到**阻断/异常**时 — 立即汇报问题和需要的用户操作
- 全部执行**完成**时 — 汇报执行总结
