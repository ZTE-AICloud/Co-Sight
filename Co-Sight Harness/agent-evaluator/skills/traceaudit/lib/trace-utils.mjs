import { normalizeToolName } from "./cli.mjs";

export function contentText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (typeof part === "string") return part;
      if (part?.type === "text") return part.text ?? "";
      if (part?.type === "tool_result") return String(part.content ?? "");
      if (part?.type === "thinking") return part.thinking ?? "";
      return "";
    })
    .filter(Boolean)
    .join("\n");
}

export function eventText(event) {
  return contentText(event?.message?.content);
}

export function extractToolUses(event) {
  const content = event?.message?.content;
  if (!Array.isArray(content)) return [];

  return content
    .filter((part) => part?.type === "tool_use")
    .map((part) => ({
      id: part.id,
      type: normalizeToolName(part.name),
      rawName: part.name,
      input: part.input ?? {},
      eventIndex: event.__line,
      timestamp: event.timestamp ?? null,
      success: true,
      file: extractToolFile(part.name, part.input ?? {}),
      command: part.input?.command,
      subagentType: part.input?.subagent_type,
      description: part.input?.description,
    }));
}

export function extractToolResults(event) {
  const content = event?.message?.content;
  if (!Array.isArray(content)) return [];

  return content
    .filter((part) => part?.type === "tool_result")
    .map((part) => ({
      toolUseId: part.tool_use_id,
      content: part.content,
      isError: Boolean(part.is_error),
      eventIndex: event.__line,
      timestamp: event.timestamp ?? null,
    }));
}

export function extractSkillInvocation(event) {
  const text = eventText(event);
  const commandName = text.match(/<command-name>([^<]+)<\/command-name>/)?.[1]?.trim();
  const isSkillFormat = /<skill-format>true<\/skill-format>/.test(text);
  if (!commandName || !isSkillFormat) return null;
  return {
    skill: commandName,
    eventIndex: event.__line,
    timestamp: event.timestamp ?? null,
    success: true,
    source: "skill-format-message",
  };
}

export function extractToolFile(name, input) {
  if (!input || typeof input !== "object") return undefined;
  if (input.file_path) return input.file_path;
  if (input.path) return input.path;
  if (input.notebook_path) return input.notebook_path;
  if (name === "Write" || name === "Edit" || name === "Read") return input.file_path;
  return undefined;
}

// 审查类子 Agent 的识别与具体编排框架无关：只看类型名里的审查语义。
export function isReviewAgentType(agentType) {
  return /review/i.test(String(agentType ?? ""));
}

export function isMcpToolCall(toolCall) {
  const name = `${toolCall.rawName ?? toolCall.type ?? ""}`;
  if (/^mcp__/i.test(name) || /mcp/i.test(name)) return true;
  const command = `${toolCall.command ?? ""}`;
  return /\brdc-mcp\b|\bmcp\b/i.test(command);
}

export function firstNonMetaUserText(events) {
  const event = events.find((candidate) => candidate.type === "user" && !candidate.isMeta && !candidate.message?.content?.some?.((part) => part?.type === "tool_result"));
  return event ? eventText(event) : "";
}

export function extractErrors(events) {
  const errors = [];
  for (const event of events) {
    const results = extractToolResults(event);
    for (const result of results) {
      if (result.isError) {
        errors.push({ eventIndex: result.eventIndex, message: String(result.content ?? ""), type: "tool_result" });
      }
    }
  }
  return errors;
}

// 改进 8：tool_result 结果事实解析
// 从 tool_result.content 尾部 8192 字符提取 exitCode、errorMessage、contentLength
// 供 D6 的 error_recovery_pattern 检查消费
export function extractResultFacts(toolResult) {
  const content = String(toolResult?.content ?? "").slice(-8192);
  return {
    hasError: Boolean(toolResult?.isError),
    exitCode: extractExitCode(content),
    errorMessage: extractErrorMessage(content).slice(0, 200),
    contentLength: content.length,
  };
}

function extractExitCode(text) {
  const match = text.match(/exit (?:code|status)[:\s]*(\d+)/i)
    ?? text.match(/returned (\d+)/i)
    ?? text.match(/\b(?:code|status)\s*=\s*(\d+)/i);
  return match ? Number(match[1]) : null;
}

function extractErrorMessage(text) {
  const lines = text.split("\n").filter((line) =>
    /\b(?:error|fail|denied|not found|ENOENT|EACCES|permission denied|no such file)\b/i.test(line)
  );
  return lines[0] ?? "";
}
