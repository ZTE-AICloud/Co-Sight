// SPDX-License-Identifier: Apache-2.0
/**
 * @file Express router for handling incoming hook events from Claude CLI. It processes various hook types (PreToolUse, PostToolUse, Stop, SubagentStop, SessionStart, SessionEnd, Notification), updates session and agent states accordingly in the database, extracts token usage from transcripts, detects compaction events, and broadcasts updates to connected clients via WebSocket.
 */

const { Router } = require("express");
const { v4: uuidv4 } = require("uuid");
const dbModule = require("../db");
const { stmts, db } = dbModule;
const { broadcast } = require("../websocket");
const TranscriptCache = require("../lib/transcript-cache");
const { scanAndImportSubagents } = require("../../scripts/import-history");
const { formatPromptForTitle, extractTitlesFromTranscriptAsync } = require("../lib/extract-prompt");
const { log: logToTaskManagement } = require("../watch/logger");
const { createChildLogger } = require("../lib/unified-logger");
const { createHookSummary } = require("../lib/hook-summary");
const {
  resolveReadableTranscriptPath,
  normalizeSource,
  inferSourceFromPath,
} = require("../lib/claude-home");
const sessionCrossLog = createChildLogger("session-cross");

// 低频 hook 接收汇总 —— 每 5 分钟一条 info 日志,用于从日志判断 hook 链路是否中断。
// 进程活着但该计数长期为 0,说明 Claude 的 hook 没进来。窗口可用 HOOK_SUMMARY_MS 覆盖。
const hookSummary = createHookSummary((msg) => sessionCrossLog.info(msg));
hookSummary.start();

// ───── [PERF-DIAG] handler 计时(可选) ─────
let __perf = null;
try {
  __perf = require("../lib/perf-trace");
} catch {}
const __hStart = () => (__perf ? __perf.nowNs() : 0n);
const __hEnd = (req, t0, label) => {
  if (!__perf) return;
  const ms = __perf.msBetween(t0, __perf.nowNs());
  req.__perfHandlerMs = ms;
  // hooks event handler 超过 500ms 就打(正常应该 <50ms)
  if (ms > 500)
    __perf.writeDiag(`[HOOKS_HANDLER] ${label} ${ms.toFixed(1)}ms (processEvent db.transaction)`);
};
// ───── [PERF-DIAG] end ─────

const router = Router();

// Shared cache instance — reused by periodic compaction scanner via router.transcriptCache
const transcriptCache = new TranscriptCache();

// Stale-session threshold for the SessionStart cleanup pass. Mirrors the
// periodic sweep in server/index.js so both code paths agree on what counts
// as "abandoned". Configurable via DASHBOARD_STALE_MINUTES; default 180 (3h).
const STALE_MINUTES = (() => {
  const raw = parseInt(process.env.DASHBOARD_STALE_MINUTES, 10);
  return Number.isFinite(raw) && raw > 0 ? raw : 180;
})();

// Detect Notification messages that indicate Claude Code is blocked waiting
// for the user (permission prompt or "waiting for your input" notice). Idle
// notifications such as "Claude has finished responding" intentionally do
// NOT match — those don't actually block the session.
const WAITING_INPUT_PATTERN =
  /\bpermission\b|waiting (?:for )?(?:your )?(?:input|response|reply|approval)|needs?\s+your\s+(?:input|approval|response|attention)|approval\s+(?:needed|required)|awaiting\s+(?:your\s+)?(?:input|approval|response)/i;

function isWaitingForUserMessage(msg) {
  if (!msg || typeof msg !== "string") return false;
  return WAITING_INPUT_PATTERN.test(msg);
}

/**
 * Best-effort extract a tool name from a Notification message text.
 * Messages like "Tool: Read\nInput: {...}" contain the tool name.
 */
function extractToolNameFromMessage(msg) {
  if (!msg || typeof msg !== "string") return null;
  const match = msg.match(/(?:Tool|tool):\s*(\w+)/);
  return match ? match[1] : null;
}

/**
 * Extract the question text from a PreToolUse hook payload for AskUserQuestion.
 */
function extractQuestionText(data) {
  const input = data.tool_input || data.input;
  if (!input) return null;
  if (input.questions && input.questions.length > 0) {
    return input.questions[0].question || null;
  }
  if (input.question) {
    return input.question;
  }
  return null;
}

/**
 * Extract options from a PreToolUse hook payload for AskUserQuestion.
 */
function extractQuestionOptions(data) {
  const input = data.tool_input || data.input;
  if (!input) return [];
  if (input.questions && input.questions.length > 0) {
    const q = input.questions[0];
    return (q.options || []).map((o) => ({
      label: o.label || "",
      action: o.label || "",
    }));
  }
  return [];
}

function clearAwaitingInput(sessionId, mainAgentId, broadcastUpdates) {
  // Clear waiting flag on the main agent and any other agents on this session
  // (subagents don't normally enter waiting state, but keep them in sync just
  // in case a future notification path stamps one).
  const cleared = stmts.clearSessionAgentsAwaitingInput.run(sessionId);
  const sessCleared = stmts.clearSessionAwaitingInput.run(sessionId);
  if (broadcastUpdates && cleared.changes > 0 && mainAgentId) {
    const refreshedMain = stmts.getAgent.get(mainAgentId);
    if (refreshedMain) broadcast("agent_updated", refreshedMain);
  }
  if (broadcastUpdates && sessCleared.changes > 0) {
    const refreshedSess = stmts.getSession.get(sessionId);
    if (refreshedSess) broadcast("session_updated", refreshedSess);
  }
}

// Reason-aware guarded clear. PreToolUse/PostToolUse clear the waiting flag on
// the assumption that a tool event means the human resumed. That assumption
// breaks when the MAIN agent is blocked on the user (AskUserQuestion /
// permission) while a BACKGROUND subagent keeps firing PreToolUse/PostToolUse:
// the subagent's tool event is not the human responding, yet it wiped the flag
// — so the "waiting for you" signal oscillated on/off in seconds.
//
// We reuse the existing subagent-actor heuristic (findDeepestWorkingAgent):
// when a subagent is the actor we clear ONLY passive waits
// (stop/session_start); a genuine 'notification' wait (main blocked on the
// user) is preserved. When MAIN is the actor we clear unconditionally, exactly
// as before — this keeps the documented permission-mid-tool path (PostToolUse
// clearing an approved prompt) intact.
function clearAwaitingInputRespectingActor(
  sessionId,
  mainAgentId,
  subagentIsActor,
  broadcastUpdates
) {
  if (subagentIsActor) {
    const sess = stmts.getSession.get(sessionId);
    if (sess && sess.awaiting_reason === "notification") {
      // Main is blocked on the user; a subagent tool event must not clear it.
      return;
    }
  }
  clearAwaitingInput(sessionId, mainAgentId, broadcastUpdates);
}

// True when the deepest currently-working agent is a subagent while the main
// agent is in 'waiting' — i.e. an incoming tool event is attributable to a
// subagent, not to the main agent resuming. Mirrors the inline heuristic the
// PreToolUse/PostToolUse cases already use for agent attribution.
function subagentIsActorNow(sessionId, mainAgent) {
  if (!mainAgent || mainAgent.status !== "waiting") return false;
  return !!stmts.findDeepestWorkingAgent.get(sessionId, sessionId);
}

/**
 * True when the session name is still an auto-generated placeholder that a
 * transcript-derived title may safely overwrite. Matches the dashboard's
 * seed name ("Session <id8>") and the cwd-derived labels used by the import
 * pipeline ("folder", "folder - suffix", "folder (slug)"). A custom name the
 * user chose via the dashboard or /rename is never auto and therefore never
 * clobbered.
 */
function isAutoSessionName(name, sessionId, cwd) {
  if (!name || !name.trim()) return true;
  if (name === `Session ${sessionId.slice(0, 8)}`) return true;
  if (cwd) {
    const base = require("path").basename(cwd);
    if (base && (name === base || name.startsWith(`${base} - `) || name.startsWith(`${base} (`))) {
      return true;
    }
  }
  return false;
}

/**
 * Short display label derived from the transcript's first user prompt.
 * Mirrors the 60-char subagent-name truncation used in PreToolUse so
 * descriptor-named rows read consistently across the board.
 */
function firstUserLabel(result) {
  const raw = result && typeof result.firstUserMessage === "string" ? result.firstUserMessage : "";
  const text = raw.trim();
  if (!text) return null;
  return text.length > 60 ? text.slice(0, 57) + "..." : text;
}

/**
 * True when the main agent's name is still an auto-generated label:
 * "Main Agent" (seed/API fallback) or "Main Agent — <auto session label>"
 * (hook / import creation paths). A suffix that is a real title — or the
 * user's own rename — makes the name non-auto and it is never overwritten.
 */
function isAutoMainAgentName(name, sessionId, cwd) {
  if (!name || !name.trim()) return true;
  if (name === "Main Agent") return true;
  const prefix = "Main Agent — ";
  if (name.startsWith(prefix)) return isAutoSessionName(name.slice(prefix.length), sessionId, cwd);
  return false;
}

/**
 * Keep sessions.name in sync with the transcript's human-readable title.
 * Source of truth lives in the JSONL as `custom-title` (explicit /rename,
 * `claude -n`, picker Ctrl+R) and `ai-title` (auto / plan-accept) lines, which
 * the TranscriptCache surfaces on every extract. Precedence: an explicit
 * custom title always wins; an ai-title only fills in when the current name is
 * still an auto/placeholder label (so a name the user set in the dashboard or
 * via /rename is never clobbered by the auto-generated title). A name that
 * equals the first-user-prompt descriptor (applied by
 * applyFirstUserDescriptor when no title existed yet) counts as replaceable
 * too — the descriptor sits BELOW both title kinds, so a later ai-title must
 * still be able to take over. Broadcasts session_updated only on a real
 * change so the UI updates in real time.
 */
function syncSessionName(session, result) {
  if (!session || !result) return;
  const custom = result.customTitle && result.customTitle.trim();
  const ai = result.aiTitle && result.aiTitle.trim();
  const desired = custom || ai || null;
  if (!desired) return;
  const replaceable =
    isAutoSessionName(session.name, session.id, session.cwd) ||
    session.name === firstUserLabel(result);
  if (!custom && !replaceable) return;
  const upd = stmts.updateSessionName.run(desired, session.id, desired);
  if (upd.changes > 0) {
    const refreshed = stmts.getSession.get(session.id);
    if (refreshed) broadcast("session_updated", refreshed);
  }
}

/**
 * Fallback descriptor from the session's first user prompt.
 * Fills sessions.name and the main agent's name/task ONLY while those fields
 * still hold their auto-generated placeholders, so a custom-title, ai-title,
 * or user-set name is never clobbered. Must run strictly AFTER
 * syncSessionName within the same pass: title sync gets first claim on the
 * name, and this helper re-reads the rows so it sees the result. Idempotent —
 * once applied (or once real names exist), every subsequent call is a no-op
 * with no broadcast.
 */
function applyFirstUserDescriptor(sessionId, result) {
  const label = firstUserLabel(result);
  if (!label) return;

  const session = stmts.getSession.get(sessionId);
  if (session && isAutoSessionName(session.name, session.id, session.cwd)) {
    const upd = stmts.updateSessionName.run(label, session.id, label);
    if (upd.changes > 0) {
      const refreshed = stmts.getSession.get(session.id);
      if (refreshed) broadcast("session_updated", refreshed);
    }
  }

  const mainAgent = getMainAgent(sessionId);
  if (!mainAgent) return;
  const desiredName = `Main Agent — ${label}`;
  const fillName =
    isAutoMainAgentName(mainAgent.name, sessionId, session?.cwd) && mainAgent.name !== desiredName;
  const fillTask = !mainAgent.task || !String(mainAgent.task).trim();
  if (!fillName && !fillTask) return;
  // updateAgent writes current_tool VERBATIM (no COALESCE) — pass the
  // existing value through, or this out-of-band update would wipe an
  // in-flight tool mid-turn.
  stmts.updateAgent.run(
    fillName ? desiredName : null,
    null,
    fillTask ? result.firstUserMessage : null,
    mainAgent.current_tool,
    null,
    null,
    mainAgent.id
  );
  const refreshedAgent = stmts.getAgent.get(mainAgent.id);
  if (refreshedAgent) broadcast("agent_updated", refreshedAgent);
}

/**
 * True when the transcript tail is an unrecovered API error: the most recent
 * error timestamp is at or after the most recent turn activity (assistant
 * output or user prompt). An error followed by real turn activity has
 * RECOVERED and must not pin the session in `error` forever. Mirrors the
 * ordering logic using the timestamps the transcript cache already exposes
 * (errors[].timestamp vs lastTurnTs), so it needs no transcript re-parse.
 */
function isErrorAtTail(result) {
  if (!result || !Array.isArray(result.errors) || result.errors.length === 0) return false;
  let lastErrorTs = null;
  for (const e of result.errors) {
    if (e && e.timestamp && (!lastErrorTs || e.timestamp > lastErrorTs)) lastErrorTs = e.timestamp;
  }
  if (!lastErrorTs) return false; // errors without timestamps — can't prove it's current
  if (!result.lastTurnTs) return true; // an error but no turn activity ⇒ unrecovered
  return lastErrorTs >= result.lastTurnTs; // error is the latest activity ⇒ unrecovered
}

function resolveEventSource(data, viewerSource) {
  return (
    normalizeSource(viewerSource) ||
    inferSourceFromPath(data?.transcript_path) ||
    null
  );
}

function ensureSession(sessionId, data, viewerSource) {
  let session = stmts.getSession.get(sessionId);
  if (!session) {
    stmts.insertSession.run(
      sessionId,
      data.session_name || `Session ${sessionId.slice(0, 8)}`,
      "active",
      data.cwd || null,
      data.model || null,
      null
    );
    session = stmts.getSession.get(sessionId);
    if (!session) {
      sessionCrossLog.error(
        `[HOOKS] Failed to create session ${sessionId} — insert returned no row`
      );
      return null;
    }
    broadcast("session_created", session);

    // Create main agent for new session
    const mainAgentId = `${sessionId}-main`;
    const sessionLabel = session.name || `Session ${sessionId.slice(0, 8)}`;
    stmts.insertAgent.run(
      mainAgentId,
      sessionId,
      `Main Agent — ${sessionLabel}`,
      "main",
      null,
      "working",
      null,
      null,
      null
    );
    const mainAgent = stmts.getAgent.get(mainAgentId);
    if (mainAgent) broadcast("agent_created", mainAgent);
  }

  // First-seen transcript_path → write to session row so the periodic sweep
  // doesn't have to scan events for it. Idempotent via the SQL guard
  // (NULL/'' check), so subsequent hooks for the same session are no-ops.
  // Type guard: hook payloads are unvalidated JSON — a non-string value would
  // make the SQLite driver throw inside the surrounding processEvent transaction.
  if (typeof data.transcript_path === "string" && data.transcript_path) {
    stmts.setSessionTranscriptPath.run(data.transcript_path, sessionId);
  }
  // 来源只写一次；升级前的旧行在这一步被新事件补上。
  const source = resolveEventSource(data, viewerSource);
  if (source) {
    stmts.setSessionSource.run(source, sessionId);
  }
  return session;
}

function getMainAgent(sessionId) {
  return stmts.getAgent.get(`${sessionId}-main`);
}

const processEvent = db.transaction((hookType, data, viewerSource) => {
  const sessionId = data.session_id;
  if (!sessionId) return null;

  // ─── [DIAG] Hook接收日志 ───
  try {
    sessionCrossLog.debug(
      {
        highFreq: true,
        hook_type: hookType,
        session_id: sessionId,
        cwd: data.cwd || "",
        model: data.model || "",
      },
      `hook_received: transcript_path=${(data.transcript_path || "").slice(0, 200)}`
    );
  } catch {}

  const session = ensureSession(sessionId, data, viewerSource);
  let mainAgent = getMainAgent(sessionId);
  const mainAgentId = mainAgent?.id ?? null;

  // Reactivate non-active sessions when we receive hook events proving the session is alive.
  // - UserPromptSubmit and PreToolUse always reactivate (user actively retried, even from error).
  // - Other work events (PostToolUse, Notification, SessionStart) reactivate non-error sessions.
  // - Stop/SubagentStop reactivate only if session is completed/abandoned — this handles
  //   sessions imported as "completed" before the server started, where the first hook event
  //   might be a Stop. For error sessions, Stop should NOT reactivate.
  // - SessionEnd never reactivates.
  const isUserAction = hookType === "UserPromptSubmit" || hookType === "PreToolUse";
  const isNonTerminalEvent = hookType !== "SessionEnd";
  const isStopLike = hookType === "Stop" || hookType === "SubagentStop";
  const isImportedOrAbandoned = session.status === "completed" || session.status === "abandoned";
  const needsReactivation =
    session.status !== "active" &&
    isNonTerminalEvent &&
    (isUserAction ||
      (!isStopLike && session.status !== "error") ||
      (isStopLike && isImportedOrAbandoned));
  if (needsReactivation) {
    stmts.reactivateSession.run(sessionId);
    broadcast("session_updated", stmts.getSession.get(sessionId));

    if (mainAgent && mainAgent.status !== "working") {
      stmts.reactivateAgent.run(mainAgentId);
      mainAgent = stmts.getAgent.get(mainAgentId);
      broadcast("agent_updated", mainAgent);
    }
  }

  let eventType = hookType;
  let toolName = data.tool_name || null;
  let summary = null;
  let agentId = mainAgentId;

  // NOTE: clearing of awaiting_input_since is handled per-case below rather
  // than blanket-clearing on every non-Notification event. The blanket rule
  // caused spontaneous waiting → active flips when *any* hook arrived after
  // a Stop — most commonly SubagentStop for backgrounded subagents, but
  // also occasionally a late PostToolUse from a background tool. A subagent
  // or background tool finishing tells us nothing about whether the human
  // has actually responded, so those events must NOT clear the flag.

  switch (hookType) {
    case "PreToolUse": {
      summary = `Using tool: ${toolName}`;

      // PreToolUse means Claude is actively running a tool, ergo the user
      // has resumed (Stop only fires at end of turn — Claude can't start a
      // new tool call without fresh user input). Clear waiting now — UNLESS a
      // background subagent is the actor and main is blocked on the user
      // (reason='notification'), in which case the flag is preserved
      // (clearAwaitingInputRespectingActor). Computed before the clear because
      // the Agent-spawn branch below mutates agent rows.
      clearAwaitingInputRespectingActor(
        sessionId,
        mainAgentId,
        subagentIsActorNow(sessionId, mainAgent),
        true
      );

      // If Claude is asking user a question, log it (task pending removed - session monitoring only)
      if (toolName === "AskUserQuestion") {
        const questionText = extractQuestionText(data);
        const options = extractQuestionOptions(data);
        const toolInput = data.tool_input || data.input || {};
        const firstQuestion = toolInput.questions?.[0] || {};
      }

      // If the tool is Agent, a subagent is being created
      if (toolName === "Agent") {
        const input = data.tool_input || {};
        const subId = uuidv4();
        // Use description, then type, then first line of prompt, then fallback
        const rawName =
          input.description ||
          input.subagent_type ||
          (input.prompt ? input.prompt.split("\n")[0].slice(0, 60) : null) ||
          "Subagent";
        const subName = rawName.length > 60 ? rawName.slice(0, 57) + "..." : rawName;

        // Infer which agent is spawning this subagent.
        // Hook events don't carry an explicit agent ID, so we use a heuristic:
        //   - If the main agent is actively working, it's the one spawning (common case).
        //   - If the main agent is waiting (for user or subagent results),
        //     the spawn must come from an already-running subagent — pick the deepest
        //     working subagent (most recently nested active agent).
        //   - Fallback to main if nothing else matches.
        let parentId = mainAgentId;
        if (mainAgent && mainAgent.status !== "working") {
          const deepest = stmts.findDeepestWorkingAgent.get(sessionId, sessionId);
          if (deepest) {
            parentId = deepest.id;
          }
        }

        // Store tool_use_id in metadata so JSONL scanner can exactly match
        // this agent row later (see findLiveSubagentForJsonl in import-history.js).
        // Without this, the scanner falls back to a heuristic (type + time window)
        // that can produce duplicates when timing is tight.
        const agentMeta = input.metadata ? { ...input.metadata } : {};
        if (data.tool_use_id) agentMeta.tool_use_id = data.tool_use_id;
        stmts.insertAgent.run(
          subId,
          sessionId,
          subName,
          "subagent",
          input.subagent_type || null,
          "working",
          input.prompt ? input.prompt.slice(0, 500) : null,
          parentId,
          Object.keys(agentMeta).length > 0 ? JSON.stringify(agentMeta) : null
        );
        broadcast("agent_created", stmts.getAgent.get(subId));
        agentId = subId;
        summary = `Subagent spawned: ${subName}`;
      }

      // Update main agent status to "working" — but only when main is the likely
      // actor. When main is waiting and working subagents exist, PreToolUse events
      // come from subagents, not main. Incorrectly promoting main to "working"
      // would break parent inference for nested agent spawning.
      //
      // Heuristic: main is waiting + working subagents exist → subagent is the actor.
      //            main is working/waiting with no subagents → main is the actor.
      const deepestWorking =
        mainAgent && mainAgent.status === "waiting"
          ? stmts.findDeepestWorkingAgent.get(sessionId, sessionId)
          : null;
      const subagentIsActor = !!deepestWorking;
      if (subagentIsActor && toolName !== "Agent") {
        agentId = deepestWorking.id;
      }
      if (
        mainAgent &&
        !subagentIsActor &&
        (mainAgent.status === "working" || mainAgent.status === "waiting")
      ) {
        stmts.updateAgent.run(null, "working", null, toolName, null, null, mainAgentId);
        broadcast("agent_updated", stmts.getAgent.get(mainAgentId));
      }
      break;
    }

    case "PostToolUse": {
      summary = `Tool completed: ${toolName}`;

      // Clear waiting too. The non-obvious case this covers: a permission
      // Notification fires *between* PreToolUse and PostToolUse (when Claude
      // Code prompts the user mid-tool). The Notification stamps waiting,
      // the user approves, the tool completes, PostToolUse arrives. Without
      // a clear here, we'd be stuck in waiting until the next PreToolUse.
      // Same actor-guard as PreToolUse: a background subagent's PostToolUse
      // must not clear a genuine 'notification' wait held by the main agent.
      clearAwaitingInputRespectingActor(
        sessionId,
        mainAgentId,
        subagentIsActorNow(sessionId, mainAgent),
        true
      );

      // Only clear pending for AskUserQuestion — it uses interactive UI (no user prompt in JSONL)
      if (toolName === "AskUserQuestion") {
        // clearTaskPending removed
      }

      // NOTE: PostToolUse for "Agent" tool fires immediately when a subagent is
      // backgrounded — it does NOT mean the subagent finished its work.
      // Subagent completion is handled by SubagentStop, not here.

      // Attribute to the working subagent when main is waiting (same heuristic as PreToolUse).
      if (mainAgent && mainAgent.status === "waiting" && toolName !== "Agent") {
        const deepest = stmts.findDeepestWorkingAgent.get(sessionId, sessionId);
        if (deepest) {
          agentId = deepest.id;
        }
      }

      // Only clear current_tool on the main agent if it's actively working.
      // Skip if waiting (waiting for subagents) or already completed.
      if (mainAgent && mainAgent.status === "working") {
        stmts.updateAgent.run(null, null, null, null, null, null, mainAgentId);
        broadcast("agent_updated", stmts.getAgent.get(mainAgentId));
      }
      break;
    }

    case "Stop": {
      const session = stmts.getSession.get(sessionId);
      const sessionLabel = session?.name || `Session ${sessionId.slice(0, 8)}`;
      summary =
        data.stop_reason === "error"
          ? `Error in ${sessionLabel}`
          : `${sessionLabel} — ready for input`;

      // Stop means Claude finished its turn, NOT that the session is closed.
      // Session stays active — user can still send more messages.
      // Background subagents may still be running — do NOT complete them
      // here. They complete via SubagentStop, or all at once on SessionEnd.
      //
      // CRITICAL: do all DB writes BEFORE any broadcast, then broadcast the
      // final state once. An earlier version broadcast agent_updated twice
      // which made the agent flicker out of every Kanban column for a
      // tick — visible to users as "agent skipped waiting and went to
      // completed".
      const now = new Date().toISOString();
      const agentMutable =
        !!mainAgent && mainAgent.status !== "completed" && mainAgent.status !== "error";

      if (data.stop_reason === "error") {
        if (agentMutable) {
          stmts.updateAgent.run(null, "error", null, null, null, null, mainAgentId);
        }
        stmts.updateSession.run(null, "error", now, null, sessionId);
        // Error stop is terminal-ish — drop any waiting flag so the row
        // lands cleanly in the Error column.
        clearAwaitingInput(sessionId, mainAgentId, false);
      } else {
        if (agentMutable) {
          stmts.updateAgent.run(null, "waiting", null, null, null, null, mainAgentId);
        }
        // Stamp the waiting flag in the same DB pass as the status update so
        // the post-write read returns a consistent (waiting, awaiting=set)
        // row. Reason 'stop' is a passive wait — a subagent tool event may
        // clear it (clearAwaitingInputRespectingActor).
        stmts.setSessionAwaitingInput.run(now, "stop", sessionId);
        if (mainAgentId) stmts.setAgentAwaitingInput.run(now, "stop", mainAgentId);
      }

      // Now broadcast — single agent_updated reflecting the final state.
      broadcast("session_updated", stmts.getSession.get(sessionId));
      if (mainAgentId) {
        broadcast("agent_updated", stmts.getAgent.get(mainAgentId));
      }
      break;
    }

    case "SubagentStop": {
      summary = `Subagent completed`;
      const subagents = stmts.listAgentsBySession.all(sessionId);
      let matchingSub = null;

      // Try to identify which subagent stopped using available data.
      // SubagentStop provides: agent_type (e.g. "Explore", "test-engineer"),
      // agent_id (Claude's internal ID), description, last_assistant_message.
      const subDesc = data.description || data.agent_type || data.subagent_type || null;
      if (subDesc) {
        const namePrefix = subDesc.length > 57 ? subDesc.slice(0, 57) : subDesc;
        matchingSub = subagents.find(
          (a) => a.type === "subagent" && a.status === "working" && a.name.startsWith(namePrefix)
        );
      }

      // Try matching by agent_type against stored subagent_type
      if (!matchingSub && data.agent_type) {
        matchingSub = subagents.find(
          (a) =>
            a.type === "subagent" && a.status === "working" && a.subagent_type === data.agent_type
        );
      }

      if (!matchingSub) {
        const prompt = data.prompt ? data.prompt.slice(0, 500) : null;
        if (prompt) {
          matchingSub = subagents.find(
            (a) => a.type === "subagent" && a.status === "working" && a.task === prompt
          );
        }
      }

      // Fallback: oldest working subagent
      if (!matchingSub) {
        matchingSub = subagents.find((a) => a.type === "subagent" && a.status === "working");
      }

      if (matchingSub) {
        stmts.updateAgent.run(
          null,
          "completed",
          null,
          null,
          new Date().toISOString(),
          null,
          matchingSub.id
        );
        broadcast("agent_updated", stmts.getAgent.get(matchingSub.id));
        agentId = matchingSub.id;
        summary = `Subagent completed: ${matchingSub.name}`;

        // Session stays active — SubagentStop just means one subagent finished,
        // the session is not over until the user explicitly closes it.
      }
      break;
    }

    case "SessionStart": {
      summary = data.source === "resume" ? "Session resumed" : "Session started";

      // Claude Code fires SessionStart with source ∈ startup|resume|clear|compact.
      // 'compact' is the odd one out: it fires MID-TURN when auto-compaction
      // kicks in while Claude is actively working, so the session is NOT sitting
      // at an empty prompt. Preserve the pre-compaction state verbatim — a
      // session compacting mid-turn is genuinely Active (main agent 'working',
      // no awaiting flag) and must stay Active; one that compacted while idle was
      // already Waiting (awaiting flag from the prior Stop) and must stay Waiting.
      // Without this guard a mid-turn compact stamps 'session_start' and flips a
      // genuinely-working session to Waiting. startup/resume/clear DO land at a
      // fresh prompt, so they still stamp the Waiting flag below.
      if (data.source !== "compact") {
        // Reactivation is already handled above for non-active sessions.
        // Promote main agent from waiting → working if needed.
        if (mainAgent && mainAgent.status === "waiting") {
          stmts.updateAgent.run(null, "working", null, null, null, null, mainAgentId);
        }

        // A just-started or just-resumed session is sitting at a prompt
        // waiting for the user's first message — Claude Code hasn't done
        // anything yet. Stamp awaiting_input_since so it lands in Waiting
        // from the moment the dashboard sees it. UserPromptSubmit (when the
        // user hits enter) or PreToolUse (when Claude actually runs a tool)
        // will clear the flag. Reason 'session_start' is a passive wait — a
        // subagent tool event may clear it.
        const sessionStartTs = new Date().toISOString();
        stmts.setSessionAwaitingInput.run(sessionStartTs, "session_start", sessionId);
        if (mainAgentId)
          stmts.setAgentAwaitingInput.run(sessionStartTs, "session_start", mainAgentId);
      }

      // Single broadcast pair with the final state — agents and sessions
      // are now connected/active with the waiting flag set, so WS clients
      // see the Waiting badge as soon as the SessionStart event lands.
      broadcast("session_updated", stmts.getSession.get(sessionId));
      if (mainAgentId) broadcast("agent_updated", stmts.getAgent.get(mainAgentId));

      // Clean up orphaned sessions: when a user runs /resume inside a session,
      // the parent session never receives Stop or SessionEnd. Mark any active
      // session that hasn't seen events for STALE_MINUTES as abandoned.
      const staleSessions = stmts.findStaleSessions.all(sessionId, STALE_MINUTES);
      const now = new Date().toISOString();
      for (const stale of staleSessions) {
        const staleAgents = stmts.listAgentsBySession.all(stale.id);
        for (const agent of staleAgents) {
          if (agent.status !== "completed" && agent.status !== "error") {
            stmts.updateAgent.run(null, "completed", null, null, now, null, agent.id);
            broadcast("agent_updated", stmts.getAgent.get(agent.id));
          }
        }
        stmts.updateSession.run(null, "abandoned", now, null, stale.id);
        broadcast("session_updated", stmts.getSession.get(stale.id));
      }
      break;
    }

    case "SessionEnd": {
      const endSession = stmts.getSession.get(sessionId);
      const endLabel = endSession?.name || `Session ${sessionId.slice(0, 8)}`;
      summary = `Session closed: ${endLabel}`;

      // Session is terminating — drop any waiting flag so the row lands in
      // its final column without a leftover yellow overlay.
      clearAwaitingInput(sessionId, mainAgentId, false);

      // SessionEnd is the definitive signal that the CLI process exited.
      // If the session was in error state, keep it there — the user never
      // recovered before exiting. Otherwise mark completed.
      const finalSessionStatus = endSession?.status === "error" ? "error" : "completed";
      const allAgents = stmts.listAgentsBySession.all(sessionId);
      const now = new Date().toISOString();
      for (const agent of allAgents) {
        if (agent.status !== "completed" && agent.status !== "error") {
          const agentFinal = finalSessionStatus === "error" ? "error" : "completed";
          stmts.updateAgent.run(null, agentFinal, null, null, now, null, agent.id);
          broadcast("agent_updated", stmts.getAgent.get(agent.id));
        }
      }
      stmts.updateSession.run(null, finalSessionStatus, now, null, sessionId);

      // Extract custom_title and ai_title from JSONL transcript asynchronously
      // Uses incremental scanning to avoid re-reading the entire file
      const transcriptPath = endSession?.transcript_path || data.transcript_path;
      const lastScannedLine = endSession?.last_scanned_line || 0;

      if (transcriptPath) {
        // Use setImmediate to avoid blocking the main thread
        setImmediate(async () => {
          try {
            const titles = await extractTitlesFromTranscriptAsync(transcriptPath, lastScannedLine);
            if (titles.customTitle || titles.aiTitle || titles.lastLine > lastScannedLine) {
              stmts.updateSessionTitles.run(
                titles.customTitle,
                titles.aiTitle,
                titles.lastLine,
                now,
                sessionId
              );
              logToTaskManagement(
                "titles",
                `Extracted titles for ${sessionId.slice(0, 8)}: custom="${titles.customTitle}", ai="${titles.aiTitle}", scanned ${titles.lastLine - lastScannedLine} new lines`
              );
              // Broadcast update after async work completes
              broadcast("session_updated", stmts.getSession.get(sessionId));
            }
          } catch (err) {
            logToTaskManagement(
              "titles-error",
              `Failed to extract titles for ${sessionId.slice(0, 8)}: ${err.message}`
            );
          }
        });
      }

      broadcast("session_updated", stmts.getSession.get(sessionId));

      break;
    }

    case "UserPromptSubmit": {
      // User just hit enter on a new prompt. This is the unambiguous
      // "session resumed" signal — fires before Claude does anything,
      // unlike PreToolUse which only fires for tool-using turns. Clear
      // the Waiting flag and promote the main agent to Working so the
      // dashboard reflects "Claude is now thinking on this" through the
      // entire response, including text-only replies that emit no
      // PreToolUse before Stop.
      summary = "User prompt submitted";
      clearAwaitingInput(sessionId, mainAgentId, true);

      // User replied — clear pending
      if (mainAgent && mainAgent.status !== "completed" && mainAgent.status !== "error") {
        stmts.updateAgent.run(null, "working", null, null, null, null, mainAgentId);
        broadcast("agent_updated", stmts.getAgent.get(mainAgentId));
      }

      // Write first_prompt (one-time, only if not already set)
      if (typeof data.prompt === "string" && data.prompt.trim()) {
        const formatted = formatPromptForTitle(data.prompt);
        if (formatted) {
          stmts.setSessionFirstPrompt.run(formatted, new Date().toISOString(), sessionId);
          const refreshedSess = stmts.getSession.get(sessionId);
          if (refreshedSess) broadcast("session_updated", refreshedSess);
        }

        // Detect /rename command and extract custom_title
        const prompt = data.prompt.trim();
        const renameMatch = prompt.match(/^\/rename\s+(.+)$/i);
        if (renameMatch && renameMatch[1]) {
          const customTitle = renameMatch[1].trim();
          if (customTitle) {
            logToTaskManagement(
              "rename",
              `Detected /rename command: "${customTitle}" (session: ${sessionId.slice(0, 8)}...)`
            );
            // TODO: Update session custom_title in database (will be implemented after verification)
          }
        }
      }
      break;
    }

    case "Notification": {
      const msg = data.message || "Notification received";
      // Tag compaction-related notifications so they show as Compaction events
      if (/compact|compress|context.*(reduc|truncat|summar)/i.test(msg)) {
        eventType = "Compaction";
        summary = msg;
      } else if (isWaitingForUserMessage(msg)) {
        // Claude Code is blocked waiting for the user (permission prompt or
        // explicit "waiting for input" notice). Stamp session + main agent
        // so the dashboard can surface a yellow "Waiting" badge until the
        // user responds — at which point the next PreToolUse/Stop clears it.
        const ts = new Date().toISOString();
        // Reason 'notification' marks a genuine main-blocked-on-user wait that
        // background subagent tool events must NOT clear (see
        // clearAwaitingInputRespectingActor).
        stmts.setSessionAwaitingInput.run(ts, "notification", sessionId);
        broadcast("session_updated", stmts.getSession.get(sessionId));
        if (mainAgentId) {
          stmts.updateAgent.run(null, "waiting", null, null, null, null, mainAgentId);
          stmts.setAgentAwaitingInput.run(ts, "notification", mainAgentId);
          broadcast("agent_updated", stmts.getAgent.get(mainAgentId));
        }

        // Write pending details to the corresponding task JSON file

        summary = msg;
      } else {
        summary = msg;
      }
      break;
    }

    default: {
      summary = `Event: ${hookType}`;
    }
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // PER-EVENT TRANSCRIPT EXTRACT
  // Extract token usage, titles, compactions, errors, and turn durations from
  // the transcript on every event that provides one. Claude Code hooks don't
  // include usage/model in stdin — the transcript JSONL is the only reliable
  // source. Uses replaceTokenUsage with compaction-aware logic: when the JSONL
  // total drops (compaction rewrote it), the old value rolls into a baseline
  // column so effective_total = current_jsonl + baseline. This ensures tokens
  // from before compaction are never lost.
  //
  // The payload's transcript_path is the path as the *Claude process* sees it,
  // and it can be unreadable here: in a container the agent runtime's HOME
  // differs from COSIGHT_HOME, so the file is simply not at the reported path.
  // Resolve one this process can actually read — the same way the conversation
  // view and the exporter do — or every write below silently stays empty.
  // ─────────────────────────────────────────────────────────────────────────────
  const { path: transcriptPath, corrected: transcriptPathCorrected } =
    resolveReadableTranscriptPath(sessionId, {
      cwd: data.cwd,
      reportedPath: data.transcript_path,
    });

  if (transcriptPathCorrected) {
    // Persist the readable path so the periodic sweep evicts the right cache
    // entry and later readers stop trusting the unusable one. A no-op once it
    // matches, so every later hook event stays quiet.
    stmts.overwriteSessionTranscriptPath.run(transcriptPath, sessionId, transcriptPath);
  }

  if (transcriptPath) {
    const result = transcriptCache.extract(transcriptPath);
    if (result) {
      const { tokensByModel, compaction, latestModel } = result;

      // Keep session.model in sync with the user's *current* model — the
      // transcript's most recent assistant entry is the source of truth, since
      // the /model command rewrites future entries but leaves session.model
      // (set at session creation) alone. The prepared statement is a no-op
      // when the value is unchanged, so we only broadcast on real flips.
      if (latestModel) {
        const upd = stmts.updateSessionModel.run(latestModel, sessionId, latestModel);
        if (upd.changes > 0) {
          const refreshed = stmts.getSession.get(sessionId);
          if (refreshed) broadcast("session_updated", refreshed);
        }
      }

      // Keep the displayed session name in sync with the transcript title
      // (set via /rename, `claude -n`, or the auto ai-title). Re-read the row
      // so we see any name set earlier in this same transaction.
      syncSessionName(stmts.getSession.get(sessionId), result);

      // Then let the first user prompt fill whatever placeholders remain
      // (session name, main agent name/task). Runs on every transcript-bearing
      // event — live on UserPromptSubmit, and as backfill for sessions that
      // never get a title (including imported ones) on any later event.
      applyFirstUserDescriptor(sessionId, result);

      // Register compaction agents and events.
      // Each isCompactSummary entry in the JSONL = one compaction that occurred.
      // Deduplicate by uuid so we only create once per compaction.
      if (compaction) {
        for (const entry of compaction.entries) {
          const compactId = `${sessionId}-compact-${entry.uuid}`;
          if (stmts.getAgent.get(compactId)) continue;

          const ts = entry.timestamp || new Date().toISOString();
          stmts.insertAgent.run(
            compactId,
            sessionId,
            "Context Compaction",
            "subagent",
            "compaction",
            "completed",
            "Automatic conversation context compression",
            mainAgentId,
            null
          );
          // Compaction is an instantaneous transition. Stamp started_at and
          // ended_at to the same transcript timestamp so duration is exactly 0.
          // Without this, insertAgent's default started_at = NOW (ingestion
          // wall clock) is paired with ended_at = ts (transcript time in the
          // past), producing impossible negative durations.
          db.prepare(
            "UPDATE agents SET started_at = ?, ended_at = ?, updated_at = ? WHERE id = ?"
          ).run(ts, ts, ts, compactId);
          broadcast("agent_created", stmts.getAgent.get(compactId));

          const compactSummary = `Context compacted - conversation history compressed (#${compaction.entries.indexOf(entry) + 1})`;
          stmts.insertEvent.run(
            sessionId,
            compactId,
            "Compaction",
            null,
            compactSummary,
            JSON.stringify({
              uuid: entry.uuid,
              timestamp: ts,
              compaction_number: compaction.entries.indexOf(entry) + 1,
              total_compactions: compaction.count,
            })
          );
          broadcast("new_event", {
            session_id: sessionId,
            agent_id: compactId,
            event_type: "Compaction",
            tool_name: null,
            summary: compactSummary,
            created_at: ts,
          });
        }
      }

      if (tokensByModel) {
        // Replace token usage for this session. The replaceTokenUsage statement
        // folds the current JSONL total into baseline columns on compaction, so
        // effective_total = current_jsonl + baseline ensures tokens from before
        // compaction are never lost.
        for (const [model, tokens] of Object.entries(tokensByModel)) {
          stmts.replaceTokenUsage.run(
            sessionId,
            model,
            tokens.input,
            tokens.output,
            tokens.cacheRead,
            tokens.cacheWrite
          );
        }
      }

      // Register API errors from transcript (quota limits, rate limits, overloaded, etc.)
      if (result.errors) {
        let newErrorRecorded = false;
        for (const apiErr of result.errors) {
          // Deduplicate: check if we already recorded this error (same type+message+timestamp)
          const errKey = `${apiErr.type}:${apiErr.timestamp || ""}`;
          const existing = db
            .prepare(
              `SELECT 1 FROM events WHERE session_id = ? AND event_type = 'APIError' 
               AND summary = ? LIMIT 1`
            )
            .get(sessionId, `${apiErr.type}: ${apiErr.message}`);
          if (existing) continue;

          stmts.insertEvent.run(
            sessionId,
            mainAgentId,
            "APIError",
            null,
            `${apiErr.type}: ${apiErr.message}`,
            JSON.stringify(apiErr)
          );
          broadcast("new_event", {
            session_id: sessionId,
            agent_id: mainAgentId,
            event_type: "APIError",
            tool_name: null,
            summary: `${apiErr.type}: ${apiErr.message}`,
            created_at: apiErr.timestamp || new Date().toISOString(),
          });
          newErrorRecorded = true;
        }

        // Flip to error only when we recorded a NEW error this call AND that
        // error is still unrecovered at the transcript tail (isErrorAtTail).
        // The APIError events are always kept for history, but a transient error
        // the CLI already retried past (successful turns after it — e.g.
        // "Connection closed mid-response" mid-run) must NOT trip the whole
        // session to `error`; only a genuinely-current failure should. This is
        // the primary guard against false Error flapping; the self-heal below is
        // the safety net for sessions flipped by older builds. The
        // newErrorRecorded gate also stops re-reads from yanking a recovered
        // session back into error.
        if (newErrorRecorded && isErrorAtTail(result)) {
          const curSession = stmts.getSession.get(sessionId);
          if (curSession && curSession.status === "active") {
            stmts.updateSession.run(null, "error", null, null, sessionId);
            broadcast("session_updated", stmts.getSession.get(sessionId));
          }
          if (mainAgent && mainAgent.status !== "completed" && mainAgent.status !== "error") {
            stmts.updateAgent.run(null, "error", null, null, null, null, mainAgentId);
            clearAwaitingInput(sessionId, mainAgentId, false);
            broadcast("agent_updated", stmts.getAgent.get(mainAgentId));
          }
        }
      }

      // Self-heal a stale error on ANY hook event. If the session is marked
      // `error` but the transcript has progressed past the last API error
      // (successful turns after it — isErrorAtTail false), the error was
      // transient and the session recovered. Normal recovery only fires on
      // UserPromptSubmit/PreToolUse; an actively-running session that only emits
      // Stop / SubagentStop / PostToolUse / Notification would otherwise stay
      // `error` forever even as its transcript (and cost) keeps growing. This
      // complements the watchdog, which only re-examines STALE sessions and so
      // never reaches a busy one. isErrorAtTail is transcript-driven, so a
      // genuinely current error (tail) is left in place.
      {
        const curSession = stmts.getSession.get(sessionId);
        if (curSession && curSession.status === "error" && !isErrorAtTail(result)) {
          stmts.reactivateSession.run(sessionId);
          broadcast("session_updated", stmts.getSession.get(sessionId));
          const curMain = mainAgentId ? stmts.getAgent.get(mainAgentId) : null;
          if (curMain && curMain.status === "error") {
            stmts.reactivateAgent.run(mainAgentId);
            broadcast("agent_updated", stmts.getAgent.get(mainAgentId));
          }
        }
      }

      // Register turn duration events from transcript
      let insertedTurns = 0;
      let insertedTurnMs = 0;
      let reconciledTurnTotals = null;
      if (result.turnDurations) {
        const sessionForTurns = stmts.getSession.get(sessionId);
        const fallbackStart = Date.parse(sessionForTurns?.started_at || "") || Date.now();
        const turns = result.turnDurations.map((td, index) => ({
          durationMs: td.durationMs,
          turnId: td.turnId || null,
          // Some Claude versions omit the timestamp. A session-relative fallback is
          // deterministic across hook replays; turnId remains the primary identity.
          timestamp: td.timestamp || new Date(fallbackStart + index).toISOString(),
        }));

        const insertTurn = (turn) => {
          const summary = `Turn completed in ${(turn.durationMs / 1000).toFixed(1)}s`;
          stmts.insertEventAt.run(
            sessionId,
            mainAgentId,
            "TurnDuration",
            null,
            summary,
            JSON.stringify({ durationMs: turn.durationMs, turnId: turn.turnId }),
            turn.timestamp
          );
          return summary;
        };

        if (result.turnDurationsComplete) {
          // A complete parse is authoritative. Rebuilding a non-canonical set repairs
          // rows and counters inflated by older versions while preserving each real
          // turn, including distinct timestamp-less turns with equal durations.
          const existingTurns = db
            .prepare(
              `SELECT id, created_at, json_extract(data, '$.durationMs') AS duration_ms, 
                      json_extract(data, '$.turnId') AS turn_id 
               FROM events WHERE session_id = ? AND event_type = 'TurnDuration' 
               ORDER BY id ASC`
            )
            .all(sessionId);
          const canonical =
            existingTurns.length === turns.length &&
            turns.every((turn, index) => {
              const row = existingTurns[index];
              return (
                row.turn_id === turn.turnId &&
                Number(row.duration_ms) === Number(turn.durationMs) &&
                row.created_at === turn.timestamp
              );
            });

          if (!canonical) {
            // processEvent already runs in one transaction, so deletion and rebuild
            // commit atomically with the hook event and repaired metadata below.
            db.prepare(
              "DELETE FROM events WHERE session_id = ? AND event_type = 'TurnDuration'"
            ).run(sessionId);
            for (const turn of turns) insertTurn(turn);
          }
          reconciledTurnTotals = {
            count: turns.length,
            durationMs: turns.reduce((total, turn) => total + turn.durationMs, 0),
          };
        } else {
          // A capped parse only contains the newest turns, so it must never delete
          // older persisted rows. Stable turn IDs make this append path replay-safe.
          for (const turn of turns) {
            const existing = turn.turnId
              ? db
                  .prepare(
                    "SELECT 1 FROM events WHERE session_id = ? AND event_type = 'TurnDuration' AND json_extract(data, '$.turnId') = ? LIMIT 1"
                  )
                  .get(sessionId, turn.turnId)
              : db
                  .prepare(
                    "SELECT 1 FROM events WHERE session_id = ? AND event_type = 'TurnDuration' AND created_at = ? AND json_extract(data, '$.durationMs') = ? LIMIT 1"
                  )
                  .get(sessionId, turn.timestamp, turn.durationMs);
            if (existing) continue;

            const summary = insertTurn(turn);
            insertedTurns += 1;
            insertedTurnMs += turn.durationMs;
            broadcast("new_event", {
              session_id: sessionId,
              agent_id: mainAgentId,
              event_type: "TurnDuration",
              tool_name: null,
              summary,
              created_at: turn.timestamp,
            });
          }
        }
      }

      // Update session metadata with enriched data (turn counts)
      if (reconciledTurnTotals || insertedTurns > 0) {
        const session = stmts.getSession.get(sessionId);
        if (session) {
          const meta = session.metadata ? JSON.parse(session.metadata) : {};
          // Count only the turns this fire actually inserted. Adding
          // result.turnDurations.length re-counted the session's whole turn history on
          // every hook fire, inflating turn_count and total_turn_duration_ms in step
          // with the duplicate rows above.
          if (reconciledTurnTotals) {
            meta.turn_count = reconciledTurnTotals.count;
            meta.total_turn_duration_ms = reconciledTurnTotals.durationMs;
          } else if (insertedTurns > 0) {
            meta.turn_count = (meta.turn_count || 0) + insertedTurns;
            meta.total_turn_duration_ms = (meta.total_turn_duration_ms || 0) + insertedTurnMs;
          }
          stmts.updateSession.run(null, null, null, JSON.stringify(meta), sessionId);
        }
      }
    }
  }

  // Evict transcript from cache on SessionEnd — session is done, no more reads expected.
  // Must happen after token extraction above to avoid re-populating the cache.
  // Invalidates the path we actually read (transcriptPath), which is the one the
  // cache is keyed by — data.transcript_path can be the unreadable variant.
  if (hookType === "SessionEnd" && transcriptPath) {
    transcriptCache.invalidate(transcriptPath);
  }

  // Bump session updated_at on every event
  stmts.touchSession.run(sessionId);

  stmts.insertEvent.run(
    sessionId,
    agentId,
    eventType,
    toolName,
    summary,
    JSON.stringify(data)
    // created_at uses default
  );

  const event = {
    session_id: sessionId,
    agent_id: agentId,
    event_type: eventType,
    tool_name: toolName,
    summary,
    created_at: new Date().toISOString(),
  };
  broadcast("new_event", event);
  return event;
});

router.post("/event", (req, res) => {
  const __t0 = __hStart();

  const { hook_type, viewer_source, data } = req.body;
  if (!hook_type || !data) {
    __hEnd(req, __t0, `POST /event MISSING_INPUT`);
    return res.status(400).json({
      error: { code: "INVALID_INPUT", message: "hook_type and data are required" },
    });
  }

  // 统计一次有效到达的 hook(用于 [HOOK_SUMMARY] 低频汇总,判断链路是否中断)
  hookSummary.increment();

  const result = processEvent(hook_type, data, viewer_source);
  if (!result) {
    __hEnd(req, __t0, `POST /event MISSING_SESSION`);
    return res.status(400).json({
      error: { code: "MISSING_SESSION", message: "session_id is required in data" },
    });
  }

  __hEnd(req, __t0, `POST /event ${hook_type} sid=${data.session_id?.slice?.(0, 8) || "?"}`);
  res.json({ ok: true, event: result });

  // After SubagentStop, scan the session's subagent JSONL files and ingest any
  // tool calls that aren't yet in the events table. Subagent tool_use blocks
  // never fire hooks on the parent session — this scan is the only path that
  // attributes them to the subagent's agent_id.
  if (hook_type === "SubagentStop" && data.session_id && data.transcript_path) {
    scanAndImportSubagents(dbModule, data.session_id, data.transcript_path)
      .then(({ created }) => {
        if (created > 0) {
          // Nudge SessionDetail to refetch — the page already debounces
          // bursts of new_event into a single paginated reload.
          broadcast("new_event", {
            session_id: data.session_id,
            agent_id: null,
            event_type: "SubagentJsonlImported",
            tool_name: null,
            summary: `Imported ${created} subagent record(s) from JSONL`,
            created_at: new Date().toISOString(),
          });
        }
      })
      .catch(() => {
        // non-fatal — partial JSONL during a live run is expected
      });
  }
});

router.transcriptCache = transcriptCache;
module.exports = router;
