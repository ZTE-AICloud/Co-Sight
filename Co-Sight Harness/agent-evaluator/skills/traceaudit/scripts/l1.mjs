import { durationMsBetween } from "../lib/cli.mjs";
import { layerReport, makeCheck, scoreDimension } from "../lib/scoring.mjs";

export function runL1(trace, rubrics) {
  const dimensions = {};
  for (const rubric of rubrics) {
    const id = rubric.dimension.id;
    const structureChecks = rubric.structure_checks ?? [];
    if (structureChecks.length === 0) continue;

    const checks = structureChecks.map((check) => evaluateStructureCheck(trace, rubric, check));
    const score = scoreDimension(id, checks, {});
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

  return layerReport({ layer: "L1", trace, rubrics, dimensions });
}

function notApplicable({ evidence, actual = null, expected = null }) {
  return { passed: null, status: "not-applicable", actual, expected, evidence };
}

function evaluateStructureCheck(trace, rubric, check) {
  const dimension = rubric.dimension.id;
  const base = {
    dimension,
    id: check.id,
    name: check.name,
    severity: check.severity ?? "medium",
    layer: "L1",
  };

  if (dimension === "trace-efficiency") return makeCheck({ ...base, ...evaluateTraceEfficiency(trace, check) });
  return makeCheck({ ...base, ...notApplicable({ evidence: `该维度没有 L1 判定器: ${dimension}` }) });
}

function evaluateTraceEfficiency(trace, check) {
  const tasks = executeTasks(trace);
  const taskScoped = new Set(["per_agent_duration", "thinking_ratio", "tool_call_density"]);
  if (taskScoped.has(check.id) && tasks.length === 0) {
    return notApplicable({
      evidence: "trace 中没有业务子 Agent，逐 Agent 的效率指标不适用。",
      actual: { businessTasks: 0 },
    });
  }

  if (check.id === "total_duration") {
    const ms = trace.meta?.totalDurationMs ?? durationMsBetween(trace.meta?.startTime, trace.meta?.endTime);
    if (!Number.isFinite(ms)) {
      return notApplicable({
        evidence: "trace 缺少可用的起止时间，总时长无从判定。",
        actual: null,
        expected: "<= 12h soft threshold",
      });
    }
    return {
      passed: ms <= 12 * 60 * 60 * 1000,
      actual: { totalDurationMs: ms, totalDuration: trace.meta?.totalDuration },
      expected: "<= 12h soft threshold",
      evidence: `Total duration ${trace.meta?.totalDuration}`,
    };
  }

  if (check.id === "per_agent_duration") {
    // 阈值仅按任务类型区分：设计/编码类任务基础阈值 45min，其余 30min
    const BASE_THRESHOLD_MIN = 30;
    const DESIGN_THRESHOLD_MIN = 45;
    const DESIGN_TASK_KEYWORDS = ["设计", "编码", "技术", "方案", "design", "code", "technical"];
    const details = tasks.map((task) => {
      const durationMs = Number(task.durationMs ?? 0);
      const durationMin = durationMs / 60000;
      const taskName = String(task.taskName ?? task.taskId ?? "");
      const isDesignTask = DESIGN_TASK_KEYWORDS.some((kw) => taskName.includes(kw));
      const thresholdMin = isDesignTask ? DESIGN_THRESHOLD_MIN : BASE_THRESHOLD_MIN;
      return {
        taskId: task.taskId,
        durationMs,
        duration: task.duration,
        durationMin: Number(durationMin.toFixed(1)),
        thresholdMin,
        isDesignTask,
        passed: durationMin <= thresholdMin,
      };
    });
    const over = details.filter((item) => !item.passed);
    return {
      passed: over.length === 0,
      actual: details.map((item) => ({
        taskId: item.taskId,
        durationMs: item.durationMs,
        duration: item.duration,
        threshold: `${item.thresholdMin}m${item.isDesignTask ? " (design)" : ""}`,
      })),
      expected: "Each business agent within threshold (base 30m, 45m for design tasks)",
      evidence: over.length
        ? `Long-running agents: ${over.map((item) => `${item.taskId}=${item.duration} (threshold ${item.thresholdMin}m)`).join(", ")}`
        : "No business agent exceeded its duration threshold.",
    };
  }

  if (check.id === "thinking_ratio") {
    // 动态阈值：context 续接会放大推理时间占比
    // 基础阈值 0.7；如果任务有多次 context 续接（从 trace 事件推断），阈值放宽到 0.9
    const BASE_THRESHOLD = Number(check.threshold?.warn ?? 0.7);
    const details = tasks.map((task) => {
      const denominator = Number(task.thinkingDurationMs ?? 0) + Number(task.toolExecutionDurationMs ?? 0);
      const ratio = denominator === 0 ? 0 : task.thinkingDurationMs / denominator;
      const durationMin = Number(task.durationMs ?? 0) / 60000;
      const hasContextContinuation = durationMin > 20 && ratio > 0.85;
      const threshold = hasContextContinuation ? 0.9 : BASE_THRESHOLD;
      return {
        taskId: task.taskId,
        ratio: Number(ratio.toFixed(4)),
        thinkingDurationMs: task.thinkingDurationMs,
        toolExecutionDurationMs: task.toolExecutionDurationMs,
        threshold,
        contextContinuationSuspected: hasContextContinuation,
        passed: ratio <= threshold,
      };
    });
    const over = details.filter((item) => !item.passed);
    return {
      passed: over.length === 0,
      actual: {
        maxRatio: Math.max(0, ...details.map((item) => item.ratio)),
        details: details.map((item) => ({
          taskId: item.taskId,
          ratio: item.ratio,
          thinkingDurationMs: item.thinkingDurationMs,
          toolExecutionDurationMs: item.toolExecutionDurationMs,
          threshold: item.threshold,
          contextContinuationSuspected: item.contextContinuationSuspected,
        })),
      },
      expected: `<= ${BASE_THRESHOLD} (or <= 0.9 if context continuation suspected)`,
      evidence: over.length
        ? `High thinking ratio: ${over.map((item) => `${item.taskId}=${item.ratio} (threshold ${item.threshold}${item.contextContinuationSuspected ? ", continuation" : ""})`).join(", ")}`
        : "Thinking ratio within threshold.",
    };
  }

  if (check.id === "tool_call_density") {
    const details = tasks.map((task) => {
      const minutes = Math.max(1 / 60, Number(task.durationMs ?? 0) / 60000);
      const density = Number(task.effectiveToolCalls ?? 0) / minutes;
      return { taskId: task.taskId, density: Number(density.toFixed(4)), effectiveToolCalls: task.effectiveToolCalls, durationMs: task.durationMs };
    });
    const low = details.filter((item) => item.density < 0.5);
    return {
      passed: low.length === 0,
      actual: { minDensity: Math.min(...details.map((item) => item.density)), details },
      expected: ">= 0.5 effective tool calls/minute",
      evidence: low.length ? `Low tool-call density: ${low.map((item) => `${item.taskId}=${item.density}`).join(", ")}` : "Tool-call density within threshold.",
    };
  }

  if (check.id === "hitl_wait_time") {
    const waits = hitlWaits(trace);
    const maxWaitMs = Math.max(0, ...waits.map((wait) => wait.waitMs));
    return {
      passed: maxWaitMs <= 60 * 60 * 1000,
      actual: { maxWaitMs, waits },
      expected: "<= 1h",
      evidence: waits.length ? `Max HITL wait ${Math.round(maxWaitMs / 60000)}m` : "No AskUserQuestion HITL waits detected.",
    };
  }

  if (check.id === "duplicate_operations") {
    const streams = toolCallStreams(trace);
    const fileCalls = streams.flatMap((stream) => stream.calls.filter((call) => call.file));
    if (fileCalls.length === 0) {
      return notApplicable({
        evidence: "整条 trace 没有带文件路径的工具调用，冗余读写无从判定。",
        actual: { fileScopedToolCalls: 0 },
      });
    }

    const findings = [];
    for (const stream of streams) {
      const counts = new Map();
      for (const call of stream.calls.filter((item) => item.file)) {
        const key = `${call.type}:${call.file}`;
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
      for (const [key, count] of counts.entries()) {
        if ((key.startsWith("Read:") && count > 5) || ((key.startsWith("Write:") || key.startsWith("Edit:")) && count > 2)) {
          findings.push({ owner: stream.owner, key, count });
        }
      }
    }
    return {
      passed: findings.length === 0,
      actual: { fileScopedToolCalls: fileCalls.length, findings },
      expected: "Read same file <= 5; Write/Edit same path <= 2",
      evidence: findings.length
        ? `Duplicate operations: ${findings.map((item) => `${item.owner}:${item.key}=${item.count}`).join(", ")}`
        : `No duplicate file operations across ${fileCalls.length} file-scoped tool call(s).`,
    };
  }

  // 错误恢复模式检测（L1 确定性算法），作用于整条 trace 的工具调用流：
  // - 盲目重试（参数完全不变）
  // - 策略调整（参数有调整）
  // - 工具切换（切换工具类型）
  if (check.id === "error_recovery_pattern") {
    const stats = { blindRetries: 0, strategyChanges: 0, toolSwitches: 0, totalErrors: 0, owners: [] };

    for (const stream of toolCallStreams(trace)) {
      const toolCalls = stream.calls ?? [];
      let streamErrors = 0;
      for (let i = 1; i < toolCalls.length; i += 1) {
        const prev = toolCalls[i - 1];
        const curr = toolCalls[i];
        if (prev.success === false) {
          stats.totalErrors += 1;
          streamErrors += 1;
          if (prev.type === curr.type && isSameInput(prev.input, curr.input)) {
            stats.blindRetries += 1;
          } else if (prev.type !== curr.type) {
            stats.toolSwitches += 1;
          } else {
            stats.strategyChanges += 1;
          }
        }
      }
      if (streamErrors > 0) stats.owners.push(`${stream.owner}=${streamErrors}`);
    }

    if (stats.totalErrors === 0) {
      return notApplicable({
        evidence: "整条 trace 没有出现工具调用失败，错误恢复模式无从判定。",
        actual: { totalErrors: 0 },
        expected: "blind_retry_ratio <= 0.5",
      });
    }

    const blindRatio = stats.blindRetries / stats.totalErrors;
    return {
      passed: blindRatio <= 0.5,
      actual: { ...stats, blindRetryRatio: Number(blindRatio.toFixed(4)) },
      expected: "blind_retry_ratio <= 0.5",
      evidence: blindRatio > 0.5
        ? `Blind retry ratio: ${blindRatio.toFixed(2)} (${stats.blindRetries}/${stats.totalErrors})`
        : `Strategy changes: ${stats.strategyChanges}, tool switches: ${stats.toolSwitches}, blind retries: ${stats.blindRetries}`,
    };
  }

  return notApplicable({ evidence: `未支持的效率检查项: ${check.id}` });
}

// 效率检查的作用域覆盖整条 trace：主流程 + 各子 Agent，而不是只看子 Agent。
function toolCallStreams(trace) {
  const streams = [{
    owner: "main",
    calls: trace.raw?.parentTrace?.toolCalls ?? [],
  }];
  for (const agent of trace.raw?.subagents ?? []) {
    streams.push({ owner: agent.agentType ?? agent.agentId ?? "subagent", calls: agent.toolCalls ?? [] });
  }
  return streams;
}

// 改进 4：工具函数 — 判断两次 tool_use 的 input 是否完全相同
function isSameInput(a, b) {
  if (!a || !b) return false;
  try {
    return JSON.stringify(sortKeys(a)) === JSON.stringify(sortKeys(b));
  } catch {
    return false;
  }
}

function sortKeys(obj) {
  if (Array.isArray(obj)) return obj.map(sortKeys);
  if (obj && typeof obj === "object") {
    return Object.keys(obj).sort().reduce((acc, key) => {
      acc[key] = sortKeys(obj[key]);
      return acc;
    }, {});
  }
  return obj;
}

function executeTasks(trace) {
  const phase = trace.phases?.find((item) => item.phase === "execute");
  return phase?.tasks ?? [];
}

function hitlWaits(trace) {
  const calls = trace.raw?.parentTrace?.toolCalls ?? [];
  const results = trace.raw?.parentTrace?.toolResults ?? [];
  const resultById = new Map(results.map((result) => [result.toolUseId, result]));
  return calls
    .filter((call) => call.type === "AskUserQuestion")
    .map((call) => {
      const result = resultById.get(call.id);
      const waitMs = durationMsBetween(call.timestamp, result?.timestamp) ?? 0;
      return { eventIndex: call.eventIndex, timestamp: call.timestamp, resultTimestamp: result?.timestamp, waitMs };
    });
}
