import { layerReport, makeCheck, scoreDimension } from "../lib/scoring.mjs";

// 同层子 Agent 的时间区间重叠超过该容差才算并行执行。
const OVERLAP_TOLERANCE_MS = 60 * 1000;

export function runL0(trace, rubrics) {
  const dimensions = {};
  for (const rubric of rubrics) {
    const id = rubric.dimension.id;
    const ruleChecks = (rubric.rule_checks ?? []);
    if (ruleChecks.length === 0) continue;

    const checks = ruleChecks.map((check) => evaluateRuleCheck(trace, rubric, check));
    const score = scoreDimension(id, checks, { trace });
    dimensions[id] = {
      id,
      name: rubric.dimension.name,
      weight: Number(rubric.dimension.weight ?? 0),
      score: score.score,
      label: score.label,
      applicable: score.applicable !== false,
      evidenceCoverage: score.evidenceCoverage ?? null,
      checks,
    };
  }

  return layerReport({ layer: "L0", trace, rubrics, dimensions });
}

function notApplicable({ evidence, actual = null, expected = null }) {
  return { passed: null, status: "not-applicable", actual, expected, evidence };
}

function evaluateRuleCheck(trace, rubric, check) {
  const dimension = rubric.dimension.id;
  const base = {
    dimension,
    id: check.id,
    name: check.name,
    severity: check.severity ?? "medium",
    layer: "L0",
  };

  const handlers = {
    "process-compliance": evaluateProcess,
    "skill-invocation": evaluateSkill,
    "review-completeness": evaluateReview,
    "rule-compliance": evaluateRuleCompliance,
  };

  const handler = handlers[dimension];
  if (!handler) {
    return makeCheck({ ...base, ...notApplicable({ evidence: `该维度没有 L0 判定器: ${dimension}` }) });
  }

  const result = handler(trace, check);
  return makeCheck({ ...base, ...result });
}

function evaluateProcess(trace, check) {
  const tasks = executeTasks(trace);
  const scope = { businessTasks: tasks.length, subagents: (trace.raw?.subagents ?? []).length };

  if (tasks.length === 0) {
    return notApplicable({
      evidence: "trace 中没有业务子 Agent，SubAgent 侧的流程检查不适用。",
      actual: scope,
      expected: ">= 1 个业务子 Agent",
    });
  }

  if (check.id === "workflow_step_order") {
    const failed = tasks.filter((task) => {
      const sequence = effectiveSequence(task);
      const firstWrite = sequence.findIndex((item) => item === "Write" || item === "Edit");
      const firstReadOrSkill = sequence.findIndex((item) => item === "Read" || item === "Skill" || item === "Bash");
      return firstWrite !== -1 && firstReadOrSkill !== -1 && firstWrite < firstReadOrSkill;
    });
    return {
      passed: failed.length === 0,
      actual: tasks.map((task) => ({ taskId: task.taskId, sequence: effectiveSequence(task) })),
      expected: "Read/Skill/Bash preparation occurs before Write/Edit output.",
      evidence: failed.length ? `Write/Edit appeared before input/tool activity: ${failed.map((task) => task.taskId).join(", ")}` : "Core operation order is plausible.",
    };
  }

  if (check.id === "prompt_contains_agent_def") {
    const relevant = tasks.filter((task) => task.prompt?.fullText);
    if (relevant.length === 0) {
      return notApplicable({
        evidence: "子 Agent 的 prompt 文本不可得，无法判定 Agent 定义内容。",
        actual: { businessTasks: tasks.length, promptsWithText: 0 },
        expected: ">= 1 个可读 prompt",
      });
    }
    const missing = relevant.filter((task) => !task.prompt.hasAgentDefContent);
    return {
      passed: missing.length === 0,
      actual: relevant.map((task) => ({ taskId: task.taskId, hasAgentDefContent: Boolean(task.prompt.hasAgentDefContent) })),
      expected: "SubAgent prompts contain key agent-definition sections.",
      evidence: missing.length
        ? `Prompt lacks key agent-definition sections: ${missing.map((task) => task.taskId).join(", ")}`
        : `${relevant.length} prompt(s) include key agent-definition sections.`,
    };
  }

  if (check.id === "skill_instruction_language") {
    const relevant = tasks.filter((task) => task.skillCalls.length > 0);
    if (relevant.length === 0) {
      return notApplicable({
        evidence: "没有子 Agent 调用 Skill，强制措辞无从判定。",
        actual: { businessTasks: tasks.length, subagentsWithSkillCalls: 0 },
        expected: ">= 1 个调用了 Skill 的子 Agent",
      });
    }
    const missing = relevant.filter((task) => !task.prompt?.hasSkillInstructions);
    return {
      passed: missing.length === 0,
      actual: relevant.map((task) => ({ taskId: task.taskId, hasSkillInstructions: Boolean(task.prompt?.hasSkillInstructions) })),
      expected: "Skill-invoking SubAgent prompts contain mandatory Skill invocation language.",
      evidence: missing.length
        ? `Missing mandatory Skill language: ${missing.map((task) => task.taskId).join(", ")}`
        : `Mandatory Skill language found in ${relevant.length} Skill-invoking prompt(s).`,
    };
  }

  return notApplicable({ evidence: `未支持的流程检查项: ${check.id}`, actual: scope });
}

function evaluateSkill(trace, check) {
  const tasks = executeTasks(trace);

  if (check.id === "skill_success_rate") {
    // 主流程与子 Agent 的 Skill 调用同等计入：只统计子 Agent 会让普通会话得到
    // “无调用即满分”的假通过。
    const parentCalls = parentSkillCalls(trace).map((call) => ({
      skill: call.input?.skill ?? call.input?.name ?? call.input?.command ?? call.description ?? "Skill",
      eventIndex: call.eventIndex,
      success: call.success,
      scope: "parent",
    }));
    const subagentCalls = tasks.flatMap((task) => task.skillCalls.map((call) => ({
      skill: call.skill,
      eventIndex: call.eventIndex,
      success: call.success,
      scope: "subagent",
      taskId: task.taskId,
    })));
    const calls = [...parentCalls, ...subagentCalls];

    if (calls.length === 0) {
      return notApplicable({
        evidence: "整条 trace 没有观测到 Skill 调用，调用成功率不适用。",
        actual: { total: 0, parent: 0, subagent: 0 },
        expected: check.threshold ?? 1,
      });
    }

    const failed = calls.filter((call) => call.success === false);
    const rate = (calls.length - failed.length) / calls.length;
    return {
      passed: rate >= Number(check.threshold ?? 1),
      actual: { total: calls.length, parent: parentCalls.length, subagent: subagentCalls.length, failed: failed.length, rate: Number(rate.toFixed(4)), failedCalls: failed },
      expected: check.threshold ?? 1,
      evidence: failed.length
        ? `Failed Skill calls: ${failed.map((call) => `${call.scope === "parent" ? "main" : call.taskId}:${call.skill}`).join(", ")}`
        : `${calls.length} Skill call(s) observed, none failed.`,
    };
  }

  return notApplicable({ evidence: `未支持的 Skill 调用检查项: ${check.id}` });
}

function evaluateReview(trace, check) {
  const tasks = executeTasks(trace);

  if (check.id === "review_spawn_count") {
    const actual = Number(trace.summary?.totalReviewSpawns ?? 0);
    if (tasks.length === 0) {
      return notApplicable({
        evidence: "trace 中没有业务子 Agent 活动，无从判断是否需要派生审查 Agent。",
        actual: { reviewSpawns: actual, businessTasks: 0 },
        expected: ">= 1 review SubAgent spawn",
      });
    }
    return {
      passed: actual > 0,
      actual: { reviewSpawns: actual, businessTasks: tasks.length },
      expected: ">= 1 review SubAgent spawn",
      evidence: actual > 0
        ? `${actual} review SubAgent spawn(s) observed across ${tasks.length} business task(s).`
        : `No review SubAgent spawn observed despite ${tasks.length} business task(s).`,
    };
  }

  return notApplicable({ evidence: `未支持的审查检查项: ${check.id}` });
}

function evaluateRuleCompliance(trace, check) {
  const base = { hardFail: Boolean(check.hard_fail) };

  if (check.id === "only_task_for_agent_spawn") {
    const subagents = trace.raw?.subagents ?? [];
    if (subagents.length === 0) {
      return { ...base, ...notApplicable({
        evidence: "本次执行没有派生子 Agent，派生方式无从判定。",
        actual: { subagents: 0 },
        expected: "Every subagent has a parent Agent/Task tool_use.",
      }) };
    }
    const missingParentCall = subagents.filter((agent) => agent.parentToolCall?.type !== "Task");
    return {
      ...base,
      passed: missingParentCall.length === 0,
      actual: {
        subagents: subagents.length,
        withoutTaskParent: missingParentCall.map((agent) => agent.agentType),
      },
      expected: "Every subagent has a parent Agent/Task tool_use.",
      evidence: missingParentCall.length
        ? `Subagents without parent Task evidence: ${missingParentCall.map((agent) => agent.agentType).join(", ")}`
        : `All ${subagents.length} subagent(s) were spawned through Agent/Task tool_use.`,
    };
  }

  if (check.id === "serial_execution") {
    const agents = (trace.raw?.subagents ?? [])
      .filter((agent) => Number.isFinite(Number(agent.spawnDepth ?? 0)))
      .map((agent) => ({
        agentType: agent.agentType,
        depth: Number(agent.spawnDepth ?? 0),
        start: Date.parse(agent.startTime ?? ""),
        end: Date.parse(agent.endTime ?? ""),
      }))
      .filter((agent) => Number.isFinite(agent.start) && Number.isFinite(agent.end));

    if (agents.length < 2) {
      return { ...base, ...notApplicable({
        evidence: `可比较时间的子 Agent 少于 2 个（${agents.length} 个），串行/并行无从判定。`,
        actual: { comparableAgents: agents.length },
        expected: "No overlapping intervals",
      }) };
    }

    const overlaps = [];
    for (let i = 0; i < agents.length; i += 1) {
      for (let j = i + 1; j < agents.length; j += 1) {
        const a = agents[i];
        const b = agents[j];
        if (a.depth !== b.depth) continue;
        const overlapMs = Math.min(a.end, b.end) - Math.max(a.start, b.start);
        if (overlapMs > OVERLAP_TOLERANCE_MS) {
          overlaps.push({ pair: `${a.agentType}/${b.agentType}`, depth: a.depth, overlapMs });
        }
      }
    }

    return {
      ...base,
      passed: overlaps.length === 0,
      actual: { comparableAgents: agents.length, overlaps },
      expected: `同层子 Agent 时间区间重叠 <= ${OVERLAP_TOLERANCE_MS}ms`,
      evidence: overlaps.length
        ? `Concurrent same-depth subagents: ${overlaps.map((item) => `${item.pair}=${Math.round(item.overlapMs / 1000)}s`).join(", ")}`
        : `${agents.length} comparable subagent interval(s), no same-depth overlap beyond ${OVERLAP_TOLERANCE_MS / 1000}s.`,
    };
  }

  return { ...base, ...notApplicable({ evidence: `未支持的规则检查项: ${check.id}` }) };
}

function executeTasks(trace) {
  const phase = trace.phases?.find((item) => item.phase === "execute");
  return phase?.tasks ?? [];
}

function parentSkillCalls(trace) {
  return (trace.raw?.parentTrace?.toolCalls ?? []).filter((call) => call.type === "Skill");
}

function effectiveSequence(task) {
  return [
    ...task.toolCalls.map((call) => call.type),
    ...task.skillCalls.map(() => "Skill"),
  ].filter((type) => !["TaskCreate", "TaskUpdate"].includes(type));
}
