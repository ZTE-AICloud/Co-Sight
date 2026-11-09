import fs from "node:fs";
import path from "node:path";
import {
  formatDurationMs,
  isDirectory,
  isFile,
} from "../lib/cli.mjs";
import { readJsonl, firstTimestamp, lastTimestamp } from "../lib/jsonl.mjs";
import { eventText, extractErrors, extractResultFacts, extractSkillInvocation, extractToolResults, extractToolUses, firstNonMetaUserText, isReviewAgentType } from "../lib/trace-utils.mjs";

export function collectTrace({ sessionId, claudeProjectDir, parentJsonlPath, subagentsDir }) {
  const parent = parseTraceFile(parentJsonlPath);
  const parentToolCalls = parent.events.flatMap(extractToolUses);
  const parentToolResults = parent.events.flatMap(extractToolResults);
  applyToolResultStatus(parentToolCalls, parentToolResults);

  const commands = parent.events.filter((event) => event.type === "user").map((event) => ({
    eventIndex: event.__line,
    timestamp: event.timestamp,
    text: extractCommandText(event),
  })).filter((entry) => entry.text);
  const executePhase = resolveExecutePhase(parent.events, parentToolCalls, commands);
  const interruption = detectInterruption(parent.events, executePhase);
  const phaseToolCalls = parentToolCalls.filter((call) => call.eventIndex >= executePhase.startEvent && call.eventIndex <= executePhase.endEvent);
  const subagents = collectSubagents(subagentsDir, parentToolCalls);
  const sessionStartTime = firstTimestamp(parent.events) ?? firstTimestamp(subagents.flatMap((agent) => agent.events)) ?? new Date(0).toISOString();
  const sessionEndTime = lastTimestamp(parent.events) ?? lastTimestamp(subagents.flatMap((agent) => agent.events)) ?? sessionStartTime;
  const startTime = executePhase.startTime ?? sessionStartTime;
  const endTime = executePhase.endTime ?? sessionEndTime;
  const totalMs = Math.max(0, Date.parse(endTime) - Date.parse(startTime));

  const allSkillCalls = subagents.flatMap((agent) => agent.skillCalls);
  const reviewSpawns = phaseToolCalls.filter((call) => isReviewAgentType(call.subagentType)).length;
  const businessSpawns = phaseToolCalls.filter((call) => call.subagentType && !isReviewAgentType(call.subagentType)).length;
  const caseId = caseIdFromTrigger(executePhase.triggerCommand, sessionId);

  return {
    meta: {
      sessionId,
      caseId,
      claudeProjectDir,
      parentJsonlPath,
      subagentsDir,
      sessionStartTime,
      sessionEndTime,
      startTime,
      endTime,
      totalDuration: formatDurationMs(totalMs),
      totalDurationMs: totalMs,
      parentEventCount: parent.events.length,
      subagentCount: subagents.length,
      collectorVersion: "0.1.0",
      warnings: preflightWarnings({ claudeProjectDir, parentJsonlPath, subagentsDir }),
    },
    raw: {
      parentTrace: {
        path: parentJsonlPath,
        parseErrors: parent.errors,
        toolCalls: parentToolCalls,
        toolResults: parentToolResults,
        commands,
      },
      subagents: subagents.map((agent) => omitEvents(agent)),
    },
    phases: [
      {
        phase: "execute",
        triggerCommand: executePhase.triggerCommand,
        startEvent: executePhase.startEvent,
        endEvent: executePhase.endEvent,
        startTime,
        endTime,
        duration: formatDurationMs(totalMs),
        durationMs: totalMs,
        startSource: executePhase.startSource,
        boundarySource: executePhase.boundarySource,
        interrupted: interruption.interrupted,
        interruptionEvents: interruption.events,
        tasks: [],
      },
    ],
    summary: {
      totalSkillCalls: allSkillCalls.length,
      totalReviewSpawns: reviewSpawns,
      totalAgentSpawns: businessSpawns,
      totalErrors: parentToolResults.filter((result) => result.isError).length + subagents.reduce((sum, agent) => sum + agent.errors.length, 0),
      mcpCalls: phaseToolCalls.filter((call) => /^mcp__/i.test(call.rawName ?? "") || /mcp/i.test(call.rawName ?? "")).length,
      interrupted: interruption.interrupted,
    },
  };
}

// 触发命令只用于给用例命名：任何 `<命名空间>:execute <活动>` 形式都能识别，
// 识别不出来时回退为 session id。
function caseIdFromTrigger(triggerCommand, sessionId) {
  const match = String(triggerCommand ?? "").match(/\b[\w-]+:execute\b[\s:]*([^\s<"'`]+)/);
  return match?.[1] ?? sessionId;
}

function resolveExecutePhase(events, parentToolCalls, commands) {
  const firstAgentEvent = parentToolCalls.find((call) => call.type === "Task")?.eventIndex ?? events[0]?.__line ?? 0;
  const attributionCommands = attributionCommandEvents(events);
  const executeCommand = commands.find((command) => isExecuteCommand(command.text));
  const executeAttribution = attributionCommands.find((command) => isExecuteCommand(command.text));
  const startEvent = executeCommand?.eventIndex ?? executeAttribution?.eventIndex ?? firstAgentEvent;
  const nextBoundary = earliestByEventIndex([
    commands.find((command) => command.eventIndex > startEvent && isPostExecuteBoundary(command.text)),
    attributionCommands.find((command) => command.eventIndex > startEvent && isPostExecuteBoundary(command.text)),
  ]);
  const endEvent = nextBoundary ? nextBoundary.eventIndex - 1 : events.at(-1)?.__line ?? startEvent;
  const startTime = eventAtOrAfter(events, startEvent)?.timestamp ?? executeCommand?.timestamp;
  const endTime = eventAtOrBefore(events, endEvent)?.timestamp ?? events.at(-1)?.timestamp ?? startTime;

  return {
    // 没有触发命令就是没有：不伪造编排框架的命令
    triggerCommand: executeCommand?.text ?? executeAttribution?.text ?? null,
    startEvent,
    endEvent,
    startSource: executeCommand ? "command-tag" : executeAttribution ? "attribution-skill" : "trace-start-fallback",
    boundarySource: nextBoundary?.source ?? null,
    startTime,
    endTime,
  };
}

function isExecuteCommand(text) {
  return /\b[\w-]+:execute\b/.test(String(text));
}

function isPostExecuteBoundary(text) {
  return /\b[\w-]+:(?:evaluate|analyze|plan|start)\b/.test(String(text));
}

function attributionCommandEvents(events) {
  return events
    .map((event) => {
      const skill = event.attributionSkill ?? event.attribution_skill ?? event.attribution?.skill ?? event.attribution?.attributionSkill;
      if (!skill) return null;
      return {
        eventIndex: event.__line,
        timestamp: event.timestamp,
        text: String(skill),
        source: "attribution-skill",
      };
    })
    .filter(Boolean);
}

function earliestByEventIndex(entries) {
  return entries
    .filter(Boolean)
    .sort((a, b) => Number(a.eventIndex ?? 0) - Number(b.eventIndex ?? 0))[0] ?? null;
}

function detectInterruption(events, executePhase) {
  const start = Number(executePhase.startEvent ?? 0);
  const end = Number(executePhase.endEvent ?? Number.POSITIVE_INFINITY);
  const interruptionEvents = events
    .filter((event) => Number(event.__line ?? 0) >= start && Number(event.__line ?? 0) <= end)
    .filter((event) => {
      const text = eventText(event);
      return Boolean(event.interruptedMessageId) || /\[Request interrupted by user\]|Request interrupted by user|用户中断/.test(text);
    })
    .map((event) => ({
      eventIndex: event.__line,
      timestamp: event.timestamp ?? null,
      type: event.type,
      text: eventText(event).slice(0, 200),
    }));

  return {
    interrupted: interruptionEvents.length > 0,
    events: interruptionEvents,
  };
}

function eventAtOrAfter(events, eventIndex) {
  return events.find((event) => Number(event.__line ?? 0) >= eventIndex && event.timestamp);
}

function eventAtOrBefore(events, eventIndex) {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (Number(events[i].__line ?? 0) <= eventIndex && events[i].timestamp) return events[i];
  }
  return null;
}

function parseTraceFile(filePath) {
  const parsed = readJsonl(filePath);
  return parsed;
}

function collectSubagents(subagentsDir, parentToolCalls) {
  if (!isDirectory(subagentsDir)) return [];

  return fs
    .readdirSync(subagentsDir)
    .filter((name) => name.endsWith(".jsonl"))
    .sort()
    .map((name) => {
      const jsonlPath = path.join(subagentsDir, name);
      const agentId = path.basename(name, ".jsonl").replace(/^agent-/, "");
      const metaPath = path.join(subagentsDir, `agent-${agentId}.meta.json`);
      const meta = isFile(metaPath) ? JSON.parse(fs.readFileSync(metaPath, "utf8")) : {};
      const parsed = parseTraceFile(jsonlPath);
      const toolCalls = parsed.events.flatMap(extractToolUses);
      const toolResults = parsed.events.flatMap(extractToolResults);
      applyToolResultStatus(toolCalls, toolResults);

      const skillCalls = [
        ...parsed.events.map(extractSkillInvocation).filter(Boolean),
        ...toolCalls.filter((call) => call.type === "Skill").map((call) => ({
          skill: call.input?.skill ?? call.input?.name ?? call.input?.command ?? call.description ?? "Skill",
          eventIndex: call.eventIndex,
          timestamp: call.timestamp,
          success: call.success,
          source: "tool_use",
        })),
      ];

      const matchedParentCall = parentToolCalls.find((call) => {
        if (meta.toolUseId != null) return call.id === meta.toolUseId;
        if (meta.name != null) return call.input?.name === meta.name;
        // Drive 2.0: meta.json 无 toolUseId/name 时，通过 description 匹配
        if (meta.description != null && call.description != null) {
          return call.description === meta.description;
        }
        return false;
      });
      return {
        agentId,
        agentType: meta.agentType ?? matchedParentCall?.subagentType ?? "unknown",
        description: meta.description ?? matchedParentCall?.description ?? "",
        toolUseId: meta.toolUseId,
        spawnDepth: meta.spawnDepth,
        jsonlPath,
        metaPath: isFile(metaPath) ? metaPath : null,
        meta,
        parentToolCall: matchedParentCall ?? null,
        startEvent: matchedParentCall?.eventIndex ?? parsed.events[0]?.__line ?? 0,
        endEvent: parsed.events.at(-1)?.__line ?? 0,
        startTime: parsed.events[0]?.timestamp ?? matchedParentCall?.timestamp ?? null,
        endTime: parsed.events.at(-1)?.timestamp ?? null,
        prompt: firstNonMetaUserText(parsed.events),
        toolCalls,
        toolResults,
        skillCalls,
        errors: extractErrors(parsed.events),
        parseErrors: parsed.errors,
        events: parsed.events,
      };
    });
}

function applyToolResultStatus(toolCalls, toolResults) {
  const byId = new Map(toolResults.map((result) => [result.toolUseId, result]));
  for (const call of toolCalls) {
    const result = byId.get(call.id);
    if (result) {
      call.success = !result.isError;
      // 改进 8：注入 resultFacts 供 D6 error_recovery_pattern 消费
      call.resultFacts = extractResultFacts(result);
    }
  }
}

function extractCommandText(event) {
  const content = event?.message?.content;
  const text = typeof content === "string" ? content : Array.isArray(content) ? content.map((part) => part.text ?? "").join("\n") : "";
  return text.match(/<command-message>([^<]+)<\/command-message>/)?.[1] ?? text.match(/<command-name>([^<]+)<\/command-name>/)?.[1] ?? "";
}

function omitEvents(agent) {
  const { events, ...rest } = agent;
  return rest;
}

function preflightWarnings({ claudeProjectDir, parentJsonlPath, subagentsDir }) {
  const warnings = [];
  if (!process.env.CLAUDE_PLUGIN_ROOT) warnings.push("CLAUDE_PLUGIN_ROOT is not set; analysis-mode detection may have fallen back.");
  if (!isDirectory(claudeProjectDir)) warnings.push(`claudeProjectDir missing: ${claudeProjectDir}`);
  if (!isFile(parentJsonlPath)) warnings.push(`parent trace missing: ${parentJsonlPath}`);
  if (!isDirectory(subagentsDir)) warnings.push(`subagents dir missing: ${subagentsDir}`);
  return warnings;
}
