import { durationMsBetween, formatDurationMs } from "../lib/cli.mjs";
import { isMcpToolCall, isReviewAgentType } from "../lib/trace-utils.mjs";

export function preprocessTrace(trace) {
  const executePhase = trace.phases?.find((phase) => phase.phase === "execute") ?? {};
  const subagents = (trace.raw?.subagents ?? []).filter((agent) => inExecutePhase(agent.parentToolCall?.eventIndex ?? agent.startEvent, executePhase));
  const parentToolCalls = (trace.raw?.parentTrace?.toolCalls ?? []).filter((call) => inExecutePhase(call.eventIndex, executePhase));

  const businessAgents = subagents
    .filter(isBusinessAgent)
    .sort((a, b) => Number(a.startEvent ?? 0) - Number(b.startEvent ?? 0));
  const tasks = buildTaskRecords(businessAgents);

  return {
    ...trace,
    meta: {
      ...trace.meta,
      processedAt: new Date().toISOString(),
    },
    phases: [
      {
        ...(trace.phases?.[0] ?? {}),
        phase: "execute",
        tasks,
      },
    ],
    summary: {
      ...trace.summary,
      totalSkillCalls: tasks.reduce((sum, task) => sum + task.skillCalls.length, 0),
      totalReviewSpawns: parentToolCalls.filter((call) => isReviewAgentType(call.subagentType)).length,
      totalAgentSpawns: tasks.length,
      mcpCalls: parentToolCalls.filter(isMcpToolCall).length,
    },
  };
}

function inExecutePhase(eventIndex, executePhase) {
  const index = Number(eventIndex ?? 0);
  const start = Number(executePhase.startEvent ?? 0);
  const end = Number(executePhase.endEvent ?? Number.POSITIVE_INFINITY);
  return index >= start && index <= end;
}

// 业务子 Agent = 非审查类子 Agent。不排除任何框架专属的编排 Agent：
// 凡是被派出去干活的 Agent 都要接受同一套检查。
function isBusinessAgent(agent) {
  if (!agent?.agentType) return false;
  return !isReviewAgentType(agent.agentType);
}

function buildTaskRecords(businessAgents) {
  return businessAgents.map((agent, index) => {
    const durationMs = durationMsBetween(agent.startTime, agent.endTime);
    const toolExecutionDurationMs = estimateToolExecutionMs(agent);
    const thinkingDurationMs = estimateThinkingMs(agent);
    const taskId = extractTaskId(agent.description) ?? extractTaskId(agent.agentType) ?? `agent-${index + 1}`;
    const skillCalls = agent.skillCalls ?? [];

    return {
      id: agent.agentId,
      taskId,
      taskName: extractTaskName(agent.description) ?? agent.agentType,
      subagentType: agent.agentType,
      agentId: agent.agentId,
      prompt: enrichPrompt(agent.prompt),
      toolCalls: agent.toolCalls ?? [],
      skillCalls,
      effectiveToolCalls: countEffectiveToolCalls(agent.toolCalls ?? [], skillCalls),
      startEvent: agent.startEvent,
      endEvent: agent.endEvent,
      startTime: agent.startTime,
      endTime: agent.endTime,
      durationMs,
      duration: formatDurationMs(durationMs),
      thinkingDurationMs,
      toolExecutionDurationMs,
    };
  });
}

function enrichPrompt(promptText) {
  const fullText = promptText ?? "";
  return {
    fullText,
    hasAgentDefContent: /工作流|输出要求|边界约束|任务目标/.test(fullText),
    hasSkillInstructions: /(必须通过 Skill 工具|严禁.*读取.*SKILL\.md|通过 Skill 工具调用|必须调用 Skill|显式调用 Skill)/.test(fullText),
  };
}

function countEffectiveToolCalls(toolCalls, skillCalls) {
  return skillCalls.length + toolCalls.filter((call) => call.type === "Write" || call.type === "Edit" || (call.type === "Bash" && call.success)).length;
}

function estimateThinkingMs(agent) {
  const duration = durationMsBetween(agent.startTime, agent.endTime);
  const tool = estimateToolExecutionMs(agent);
  if (!Number.isFinite(duration)) return 0;
  return Math.max(0, duration - tool);
}

function estimateToolExecutionMs(agent) {
  const resultsById = new Map((agent.toolResults ?? []).map((result) => [result.toolUseId, result]));
  let total = 0;
  for (const call of agent.toolCalls ?? []) {
    const result = resultsById.get(call.id);
    const ms = durationMsBetween(call.timestamp, result?.timestamp);
    if (Number.isFinite(ms)) total += ms;
  }
  return total;
}

function extractTaskId(text) {
  return String(text ?? "").match(/\b(T\d+[A-Za-z]?)\b/)?.[1] ?? null;
}

function extractTaskName(text) {
  const value = String(text ?? "");
  const match = value.match(/\bT\d+[A-Za-z]?\b[^\S\r\n]*[:：-]?[^\S\r\n]*(.+?)(?:[，。,：:\n(（]|$)/);
  return match?.[1]?.trim() ?? null;
}
