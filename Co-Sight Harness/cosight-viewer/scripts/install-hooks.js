#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0

/**
 * 把 hook 安装到**每一个已安装的 CLI 源**的 settings.json：
 *   - Claude  → ~/.claude/settings.json（或 CLAUDE_CONFIG_DIR）
 *   - Cosight → ~/.cosight/settings.json（或 COSIGHT_CONFIG_DIR）
 *
 * 两边的 hook 命令都指向同一个 handler，并用 `--source <id>` 标明来源，
 * 这样 server 不需要靠路径去猜事件来自哪个 CLI。
 *
 * 幂等：每次运行只替换自己的旧条目，不碰用户配置里的其它 hook。
 */

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const { getSourceHomes } = require("../server/lib/claude-home");
const { getHookHandlerPath } = require("../server/lib/hook-config");

const HOOK_HANDLER = getHookHandlerPath().replace(/\\/g, "/");

// Hook types to install. Some support matchers, some don't.
const HOOKS_WITH_MATCHER = ["PreToolUse", "PostToolUse", "Stop", "SubagentStop", "Notification"];
// UserPromptSubmit fires the instant the user hits enter — the only reliable
// signal that the user has resumed for *text-only* turns (no PreToolUse will
// fire until Claude calls a tool, which never happens for plain-text replies).
// Without it the Waiting badge persists through the entire generation of a
// text response. SessionStart / SessionEnd / UserPromptSubmit don't take
// tool-name matchers, hence the separate list.
const HOOKS_WITHOUT_MATCHER = ["SessionStart", "SessionEnd", "UserPromptSubmit"];
const HOOK_TYPES = [...HOOKS_WITH_MATCHER, ...HOOKS_WITHOUT_MATCHER];

function commandExists(name) {
  try {
    const cmd = process.platform === "win32" ? "where" : "which";
    execFileSync(cmd, [name], { stdio: "ignore", windowsHide: true });
    return true;
  } catch {
    return false;
  }
}

/** 一个源是否值得安装 hook：主目录已存在，或对应 CLI 在 PATH 里。 */
function isSourcePresent(source) {
  try {
    if (fs.existsSync(source.home)) return true;
  } catch {
    /* ignore */
  }
  return commandExists(source.id);
}

function makeHookEntry(hookType, sourceId) {
  const entry = {
    hooks: [
      {
        type: "command",
        command: `node "${HOOK_HANDLER}" ${hookType} --source ${sourceId}`,
      },
    ],
  };
  if (HOOKS_WITH_MATCHER.includes(hookType)) {
    entry.matcher = "*";
  }
  return entry;
}

function isOurEntry(entry) {
  // 只认本项目官方 handler 文件名（匹配文件名而非完整路径，安装目录搬家后
  // 仍能替换旧条目）。刻意不匹配裸 `hook-handler.js`：那是其它工具/用户
  // 自己的脚本也可能用的名字，误删会破坏别人的 hook。
  const handlerPattern = /cosight-viewer-hook-handler\.js/;
  if (entry.command && handlerPattern.test(entry.command)) return true;
  if (Array.isArray(entry.hooks)) {
    return entry.hooks.some((h) => h && h.command && handlerPattern.test(h.command));
  }
  return false;
}

/**
 * 给单个 settings.json 安装 hook。
 *
 * @param {string} settingsPath
 * @param {string} sourceId
 * @param {boolean} silent
 * @returns {{ok: boolean, settingsPath: string, installed: number, updated: number}}
 */
function installHooksForSettings(settingsPath, sourceId, silent = false) {
  let settings = {};
  if (fs.existsSync(settingsPath)) {
    try {
      const raw = fs.readFileSync(settingsPath, "utf8");
      settings = JSON.parse(raw);
    } catch (err) {
      if (!silent) console.error(`Failed to parse ${settingsPath}:`, err.message);
      return { ok: false, settingsPath, installed: 0, updated: 0 };
    }
  }

  if (!settings.hooks) settings.hooks = {};

  let installed = 0;
  let updated = 0;

  for (const hookType of HOOK_TYPES) {
    if (!settings.hooks[hookType]) settings.hooks[hookType] = [];

    const entries = settings.hooks[hookType];
    const ourIndices = entries.map((e, i) => (isOurEntry(e) ? i : -1)).filter((i) => i >= 0);

    if (ourIndices.length > 0) {
      // Replace all existing our entries with a single fresh entry
      settings.hooks[hookType] = entries.filter((_, i) => !ourIndices.includes(i));
      updated += ourIndices.length;
    } else {
      installed++;
    }

    // Push a single fresh entry with the current handler path and source tag
    settings.hooks[hookType].push(makeHookEntry(hookType, sourceId));
  }

  const dir = path.dirname(settingsPath);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + "\n", "utf8");

  if (!silent) {
    console.log(`[${sourceId}] Settings file: ${settingsPath}`);
    console.log(`[${sourceId}] Installed: ${installed} new, updated: ${updated} existing`);
  }

  return { ok: true, settingsPath, installed, updated };
}

/**
 * 给所有已存在的 CLI 源安装 hook。
 *
 * @param {boolean} silent
 * @returns {{ok: boolean, results: Array<object>}}
 */
function installHooks(silent = false) {
  const sources = getSourceHomes().filter(isSourcePresent);
  const results = [];
  for (const source of sources) {
    results.push(installHooksForSettings(source.settingsPath, source.id, silent));
  }

  const ok = results.length > 0 && results.every((r) => r.ok);
  if (!silent) {
    console.log(`Hook handler: ${HOOK_HANDLER}`);
    console.log(`Configured sources: ${sources.map((s) => s.id).join(", ") || "(none)"}`);
    console.log("Start a new CLI session to begin tracking.");
  }
  return { ok, results };
}

if (require.main === module) {
  installHooks(false);
}

module.exports = { installHooks, installHooksForSettings, isSourcePresent, HOOK_TYPES };
