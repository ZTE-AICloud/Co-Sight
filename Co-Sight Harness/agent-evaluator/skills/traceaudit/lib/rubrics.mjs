// 五个评估维度的检查项定义。
// 仅保留纯 trace 可判的检查项；依赖执行计划 / agent 定义 / 产物文件系统的检查项已移除。
// 检查项必须与具体工作流无关：不得编码某个编排框架（如 drive / co-helm）的专属规矩，
// 否则普通会话会被当成违规命中。无可判证据的检查项记为 not-applicable，不参与打分。

const DIMENSIONS = [
  {
    dimension: { id: "process-compliance", name: "流程合规性", weight: 0.30 },
    rule_checks: [
      { id: "workflow_step_order", name: "工作流步骤顺序", severity: "medium" },
      { id: "prompt_contains_agent_def", name: "Prompt 是否包含 Agent 定义内容", severity: "high" },
      { id: "skill_instruction_language", name: "Skill 调用强制措辞检测", severity: "medium" },
    ],
  },
  {
    dimension: { id: "skill-invocation", name: "Skill 调用完整性", weight: 0.20 },
    rule_checks: [
      { id: "skill_success_rate", name: "Skill 调用成功率", severity: "high", threshold: 1.0 },
    ],
  },
  {
    dimension: { id: "review-completeness", name: "审查完整性", weight: 0.20 },
    rule_checks: [
      { id: "review_spawn_count", name: "审查 SubAgent 派生情况", severity: "critical" },
    ],
  },
  {
    dimension: { id: "rule-compliance", name: "规则合规性", weight: 0.15 },
    rule_checks: [
      { id: "only_task_for_agent_spawn", name: "必须通过 Task 调用 SubAgent", severity: "critical", hard_fail: true },
      { id: "serial_execution", name: "严格串行执行", severity: "high", hard_fail: false },
    ],
  },
  {
    dimension: { id: "trace-efficiency", name: "轨迹效率", weight: 0.15 },
    structure_checks: [
      { id: "total_duration", name: "总执行时间", severity: "medium" },
      { id: "per_agent_duration", name: "各 Agent 执行时间", severity: "medium" },
      { id: "thinking_ratio", name: "推理时间占比", severity: "medium", threshold: { warn: 0.7 } },
      { id: "tool_call_density", name: "有效工具调用密度", severity: "medium", threshold: { warn: 0.5 } },
      { id: "hitl_wait_time", name: "HITL 阻断等待时间", severity: "medium" },
      { id: "error_recovery_pattern", name: "错误恢复模式检测", severity: "high", threshold: { blind_retry_ratio: 0.5 } },
      { id: "duplicate_operations", name: "冗余操作检测", severity: "low" },
    ],
  },
];

export function loadRubrics() {
  return DIMENSIONS;
}

export function dimensionKey(id) {
  return {
    "process-compliance": "processCompliance",
    "skill-invocation": "skillInvocation",
    "review-completeness": "reviewCompleteness",
    "rule-compliance": "ruleCompliance",
    "trace-efficiency": "traceEfficiency",
  }[id] ?? camelize(id);
}

export function dimensionLabel(id) {
  return {
    "process-compliance": "流程合规性",
    "skill-invocation": "Skill 调用完整性",
    "review-completeness": "审查完整性",
    "rule-compliance": "规则合规性",
    "trace-efficiency": "轨迹效率",
  }[id] ?? id;
}

export function rubricVersion() {
  return "v3";
}

function camelize(id) {
  return String(id).replace(/-([a-z])/g, (_, char) => char.toUpperCase());
}
