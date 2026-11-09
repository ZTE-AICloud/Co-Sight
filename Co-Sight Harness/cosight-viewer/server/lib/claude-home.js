// SPDX-License-Identifier: Apache-2.0
/**
 * @file claude-home.js
 * @description 会话数据源与 viewer 数据目录的统一解析。
 *
 * 这里有两个**互不相干**的概念，不要再混用：
 *
 * 1. **CLI 源目录**（只读，由 CLI 自己决定）：
 *    - Claude  → `CLAUDE_CONFIG_DIR` ?? `~/.claude`
 *    - Cosight → `COSIGHT_CONFIG_DIR` ?? `~/.cosight`
 *    每个源下面有 `projects/`（转录）和 `settings.json`（hook 配置）。
 *    两个源**同时**被监控，不需要“模式”二选一。
 *
 * 2. **viewer 自有数据目录**（可写）：
 *    `DASHBOARD_DATA_DIR` ?? `<COSIGHT_HOME ?? ~/.cosight-harness>/cosight-viewer`
 *    数据库、日志、快照、发现文件、导入会话都放在这里。
 *
 * `COSIGHT_HOME` 是框架的容器根，只用来推导 viewer 自有数据目录；
 * **绝不能**再拿它去拼 `.claude` / `.cosight`（那正是之前转录为空的根因）。
 */
const path = require("path");
const os = require("os");
const fs = require("fs");

const SOURCE_CLAUDE = "claude";
const SOURCE_COSIGHT = "cosight";
const SOURCE_CODEX = "codex";
const SOURCES = [SOURCE_CLAUDE, SOURCE_COSIGHT, SOURCE_CODEX];

/**
 * 源注册表：新增一个 CLI 时在这里加一条描述。
 *
 * `implemented=false` 的源只登记名字：开关里写了它也只给一条明确提示，
 * 不会静默忽略，方便以后接入 Codex 时先占位。
 */
const SOURCE_REGISTRY = [
  {
    id: SOURCE_CLAUDE,
    homeEnv: "CLAUDE_CONFIG_DIR",
    defaultHome: () => path.join(os.homedir(), ".claude"),
    implemented: true,
    supportsHooks: true,
  },
  {
    id: SOURCE_COSIGHT,
    homeEnv: "COSIGHT_CONFIG_DIR",
    defaultHome: () => path.join(os.homedir(), ".cosight"),
    implemented: true,
    supportsHooks: true,
  },
  {
    id: SOURCE_CODEX,
    homeEnv: "CODEX_HOME",
    defaultHome: () => path.join(os.homedir(), ".codex"),
    implemented: false,
    supportsHooks: false,
  },
];

/** 未设置 `VIEWER_SOURCES` 时的默认观测源。 */
const DEFAULT_SOURCES = [SOURCE_CLAUDE];

const warnedSourceValues = new Set();

function warnOnce(key, message) {
  if (warnedSourceValues.has(key)) return;
  warnedSourceValues.add(key);
  console.warn(`[cosight-viewer] ${message}`);
}

/**
 * 解析 `VIEWER_SOURCES`（逗号分隔）并返回已启用、且已实现的源 id。
 *
 * - 未设置 → `[claude]`
 * - 未知 id → 提示后忽略
 * - 已知但未实现（如 codex）→ 提示后忽略
 * - 过滤后为空 → 回退默认 `[claude]`，保证服务始终可用
 */
function getEnabledSourceIds() {
  const raw = process.env.VIEWER_SOURCES;
  if (!raw || !raw.trim()) return [...DEFAULT_SOURCES];

  const requested = [...new Set(
    raw
      .split(",")
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean)
  )];

  const byId = new Map(SOURCE_REGISTRY.map((source) => [source.id, source]));
  const enabled = [];
  for (const id of requested) {
    const source = byId.get(id);
    if (!source) {
      warnOnce(`unknown:${id}`, `VIEWER_SOURCES 含未知源 "${id}"，已忽略`);
      continue;
    }
    if (!source.implemented) {
      warnOnce(`unimplemented:${id}`, `VIEWER_SOURCES 含尚未实现的源 "${id}"，已忽略`);
      continue;
    }
    enabled.push(id);
  }

  if (enabled.length === 0) {
    warnOnce("empty", "VIEWER_SOURCES 没有可用源，回退为默认 claude");
    return [...DEFAULT_SOURCES];
  }
  return enabled;
}

function resolveSourceHome(descriptor) {
  return path.resolve(process.env[descriptor.homeEnv] || descriptor.defaultHome());
}

function toSourceHome(descriptor) {
  const home = resolveSourceHome(descriptor);
  return {
    id: descriptor.id,
    home,
    projectsDir: path.join(home, "projects"),
    settingsPath: path.join(home, "settings.json"),
  };
}

/** viewer 自有数据目录（数据库/日志/快照/发现文件）。 */
function getViewerDataDir() {
  if (process.env.DASHBOARD_DATA_DIR) return process.env.DASHBOARD_DATA_DIR;
  const root = process.env.COSIGHT_HOME
    ? path.resolve(process.env.COSIGHT_HOME)
    : path.join(os.homedir(), ".cosight-harness");
  return path.join(root, "cosight-viewer");
}

/**
 * 依次返回已启用的源（默认只有 claude）。
 * 按 home 去重（`CLAUDE_CONFIG_DIR` 与 `COSIGHT_CONFIG_DIR` 指向同一目录时只保留一条）。
 *
 * @returns {Array<{id: string, home: string, projectsDir: string, settingsPath: string}>}
 */
function getSourceHomes() {
  const byId = new Map(SOURCE_REGISTRY.map((source) => [source.id, source]));
  const seen = new Set();
  const sources = [];
  for (const id of getEnabledSourceIds()) {
    const descriptor = byId.get(id);
    if (!descriptor) continue;
    const source = toSourceHome(descriptor);
    const key = process.platform === "win32" ? source.home.toLowerCase() : source.home;
    if (seen.has(key)) continue;
    seen.add(key);
    sources.push(source);
  }
  return sources;
}

/**
 * 所有**已实现**的源，忽略开关。卸载等需要彻底清理的场景使用。
 */
function getAllSourceHomes() {
  const seen = new Set();
  const sources = [];
  for (const descriptor of SOURCE_REGISTRY) {
    if (!descriptor.implemented) continue;
    const source = toSourceHome(descriptor);
    const key = process.platform === "win32" ? source.home.toLowerCase() : source.home;
    if (seen.has(key)) continue;
    seen.add(key);
    sources.push(source);
  }
  return sources;
}

/** 两个源的 projects 目录（用于跨源查找转录）。 */
function getProjectsDirs() {
  return getSourceHomes().map((source) => source.projectsDir);
}

/** 两个源的 settings.json（用于安装 hook）。 */
function getSettingsPaths() {
  return getSourceHomes().map((source) => source.settingsPath);
}

/** 规范来源标识；非法值返回 null。 */
function normalizeSource(value) {
  const source = String(value || "").toLowerCase();
  return SOURCES.includes(source) ? source : null;
}

/** 从转录绝对路径推断来源（升级前的历史会话兜底用）。 */
function inferSourceFromPath(filePath) {
  if (!filePath || typeof filePath !== "string") return null;
  const normalized = filePath.replace(/\\/g, "/").toLowerCase();
  if (normalized.includes("/.cosight/")) return SOURCE_COSIGHT;
  if (normalized.includes("/.claude/")) return SOURCE_CLAUDE;
  return null;
}

/**
 * 会话来源的默认逻辑：
 *   1. 有 source 字段 → 用它；
 *   2. 没有 → 从 transcript_path 推断；
 *   3. 仍判断不出来 → claude。
 */
function resolveSessionSource(session) {
  return (
    normalizeSource(session?.source) ||
    inferSourceFromPath(session?.transcript_path) ||
    SOURCE_CLAUDE
  );
}

function findDescriptor(id) {
  return SOURCE_REGISTRY.find((source) => source.id === id);
}

/** Claude 源主目录（保留旧接口，不受 VIEWER_SOURCES 开关影响）。 */
function getClaudeHome() {
  const descriptor = findDescriptor(SOURCE_CLAUDE);
  return descriptor ? resolveSourceHome(descriptor) : path.join(os.homedir(), ".claude");
}

/** Cosight 源主目录（保留旧接口，不受 VIEWER_SOURCES 开关影响）。 */
function getCosightHome() {
  const descriptor = findDescriptor(SOURCE_COSIGHT);
  return descriptor ? resolveSourceHome(descriptor) : path.join(os.homedir(), ".cosight");
}

/** 兼容旧接口：Claude 源的 projects 目录。新代码请用 getProjectsDirs()。 */
function getProjectsDir() {
  return path.join(getClaudeHome(), "projects");
}

/** 兼容旧接口：Claude 源的 settings.json。新代码请用 getSettingsPaths()。 */
function getSettingsPath() {
  return path.join(getClaudeHome(), "settings.json");
}

/** 兼容旧接口：返回 viewer 自有数据目录。 */
function getBaseDataDir() {
  return getViewerDataDir();
}

function getTaskManagementRoot() {
  const override = process.env.TASK_MANAGEMENT_ROOT;
  if (override) return override.replace(/^~/, os.homedir());
  return path.join(getViewerDataDir(), "task-management");
}

/** 导入会话 JSONL 的落点（writer 用），在 viewer 数据目录内。 */
function getImportedSessionsDir() {
  return path.join(getTaskManagementRoot(), "imported-sessions");
}

/** viewer 拥有的转录快照目录。 */
function getTranscriptSnapshotDir() {
  return path.join(getViewerDataDir(), "transcripts");
}

/**
 * Claude/Cosight 共用的路径编码：非字母数字全部替换为 "-"。
 * Example: "/Users/txj/.codefuse" → "-Users-txj--codefuse"
 */
function encodeCwd(cwd) {
  return cwd.replace(/[^a-zA-Z0-9]/g, "-");
}

/**
 * 按 sessionId + cwd 在**所有 CLI 源**里找主转录。
 * 顺序：各源 projects → viewer 导入目录 → 全盘扫描。
 */
function getTranscriptPath(sessionId, cwd) {
  if (!cwd) return null;
  const encoded = encodeCwd(cwd);

  for (const projectsDir of getProjectsDirs()) {
    const candidate = path.join(projectsDir, encoded, `${sessionId}.jsonl`);
    if (fs.existsSync(candidate)) return candidate;
  }

  const importedCandidate = path.join(getImportedSessionsDir(), encoded, `${sessionId}.jsonl`);
  if (fs.existsSync(importedCandidate)) return importedCandidate;

  return findTranscriptPath(sessionId);
}

/**
 * 按 sessionId + cwd + agentId 在所有 CLI 源里找子 agent 转录。
 */
function getSubagentTranscriptPath(sessionId, cwd, agentId) {
  if (!cwd) return null;
  const encoded = encodeCwd(cwd);

  for (const projectsDir of getProjectsDirs()) {
    const candidate = path.join(
      projectsDir,
      encoded,
      sessionId,
      "subagents",
      `agent-${agentId}.jsonl`
    );
    if (fs.existsSync(candidate)) return candidate;
  }

  const importedCandidate = path.join(
    getImportedSessionsDir(),
    encoded,
    sessionId,
    "subagents",
    `agent-${agentId}.jsonl`
  );
  if (fs.existsSync(importedCandidate)) return importedCandidate;

  return findSubagentTranscriptPath(sessionId, agentId);
}

/** 不知道 cwd 时，扫描所有源的 projects 目录 + viewer 导入目录。 */
function findTranscriptPath(sessionId) {
  const searchDirs = [...getProjectsDirs(), getImportedSessionsDir()];
  for (const projectsDir of searchDirs) {
    if (!fs.existsSync(projectsDir)) continue;
    try {
      const dirs = fs.readdirSync(projectsDir, { withFileTypes: true });
      for (const d of dirs) {
        if (!d.isDirectory()) continue;
        const candidate = path.join(projectsDir, d.name, `${sessionId}.jsonl`);
        if (fs.existsSync(candidate)) return candidate;
      }
    } catch {
      // Permission or IO error, ignore
    }
  }
  return null;
}

/**
 * 返回本进程可读的转录路径。
 *
 * hook 上报的 `transcript_path` 是 **CLI 进程视角**的路径，可能与本进程
 * 不可读（例如容器里 CLI 的 HOME 与 viewer 不同）。策略：
 *   1. 上报路径存在 → 直接用；
 *   2. 否则按 cwd 在**所有源**里推导，或全盘扫描；
 *   3. 都不行 → 原样返回上报路径（调用方保持旧行为）。
 *
 * @param {string} sessionId
 * @param {{cwd?: string|null, reportedPath?: string|null}} [options]
 * @returns {{path: string|null, corrected: boolean}}
 */
function resolveReadableTranscriptPath(sessionId, { cwd = null, reportedPath = null } = {}) {
  if (reportedPath && fs.existsSync(reportedPath)) {
    return { path: reportedPath, corrected: false };
  }

  const alternative = getTranscriptPath(sessionId, cwd) || findTranscriptPath(sessionId);
  if (alternative && alternative !== reportedPath) {
    return { path: alternative, corrected: true };
  }

  return { path: reportedPath, corrected: false };
}

/** viewer 拥有的快照主转录路径（存在才返回）。 */
function getSnapshotTranscriptPath(sessionId) {
  const candidate = path.join(getTranscriptSnapshotDir(), `${sessionId}.jsonl`);
  return fs.existsSync(candidate) ? candidate : null;
}

/** viewer 拥有的快照子 agent 转录路径（存在才返回）。 */
function getSnapshotSubagentTranscriptPath(sessionId, agentId) {
  const subDir = path.join(getTranscriptSnapshotDir(), sessionId, "subagents");
  if (!fs.existsSync(subDir)) return null;
  const exact = path.join(subDir, `agent-${agentId}.jsonl`);
  if (fs.existsSync(exact)) return exact;
  if (agentId.startsWith("acompact-")) {
    try {
      const match = fs
        .readdirSync(subDir)
        .find((f) => f.startsWith("agent-acompact-") && f.endsWith(".jsonl"));
      if (match) return path.join(subDir, match);
    } catch {
      /* ignore */
    }
  }
  return null;
}

/** 不知道 cwd 时，扫描所有源找子 agent 转录。 */
function findSubagentTranscriptPath(sessionId, agentId) {
  const searchDirs = [...getProjectsDirs(), getImportedSessionsDir()];
  for (const projectsDir of searchDirs) {
    if (!fs.existsSync(projectsDir)) continue;
    try {
      const dirs = fs.readdirSync(projectsDir, { withFileTypes: true });
      for (const d of dirs) {
        if (!d.isDirectory()) continue;
        const subagentsDir = path.join(projectsDir, d.name, sessionId, "subagents");
        if (!fs.existsSync(subagentsDir)) continue;

        const exact = path.join(subagentsDir, `agent-${agentId}.jsonl`);
        if (fs.existsSync(exact)) return exact;

        if (agentId.startsWith("acompact-")) {
          const files = fs.readdirSync(subagentsDir);
          const match = files.find((f) => f.startsWith("agent-acompact-") && f.endsWith(".jsonl"));
          if (match) return path.join(subagentsDir, match);
        }
      }
    } catch {
      // Ignore
    }
  }
  return null;
}

/**
 * 运行时切换 Claude 主目录（保留旧接口）。
 *
 * 只设置 `CLAUDE_CONFIG_DIR`：Claude CLI 只认这个变量；不再写 COSIGHT_HOME，
 * 避免把框架数据根与 CLI 主目录混在一起。
 */
function setClaudeHome(newPath) {
  const resolved = newPath.replace(/^~(?=\/)/, os.homedir());
  if (!path.isAbsolute(resolved)) {
    throw new Error("Claude home directory must be an absolute path");
  }
  if (!fs.existsSync(resolved)) {
    throw new Error(`Directory does not exist: ${resolved}`);
  }
  const stat = fs.statSync(resolved);
  if (!stat.isDirectory()) {
    throw new Error(`Not a directory: ${resolved}`);
  }
  process.env.CLAUDE_CONFIG_DIR = resolved;
  writeEnvFile("CLAUDE_CONFIG_DIR", resolved);
  return resolved;
}

/** 写入 cosight-viewer 的 .env（保留旧接口）。 */
function writeEnvFile(key, value) {
  const envPath = path.resolve(__dirname, "..", "..", ".env");
  let lines = [];
  if (fs.existsSync(envPath)) {
    lines = fs.readFileSync(envPath, "utf8").split("\n");
  }
  let found = false;
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (trimmed.startsWith(`${key}=`)) {
      lines[i] = `${key}=${value}`;
      found = true;
      break;
    }
  }
  if (!found) {
    lines.push(`${key}=${value}`);
  }
  const tempPath = envPath + ".tmp";
  fs.writeFileSync(tempPath, lines.join("\n") + "\n", "utf8");
  fs.renameSync(tempPath, envPath);
}

module.exports = {
  SOURCE_CLAUDE,
  SOURCE_COSIGHT,
  SOURCE_CODEX,
  SOURCES,
  SOURCE_REGISTRY,
  DEFAULT_SOURCES,
  getEnabledSourceIds,
  getViewerDataDir,
  getSourceHomes,
  getAllSourceHomes,
  getProjectsDirs,
  getSettingsPaths,
  normalizeSource,
  inferSourceFromPath,
  resolveSessionSource,
  getBaseDataDir,
  getClaudeHome,
  getCosightHome,
  getProjectsDir,
  getImportedSessionsDir,
  getTaskManagementRoot,
  getTranscriptSnapshotDir,
  getSettingsPath,
  getTranscriptPath,
  getSubagentTranscriptPath,
  getSnapshotTranscriptPath,
  getSnapshotSubagentTranscriptPath,
  findTranscriptPath,
  findSubagentTranscriptPath,
  resolveReadableTranscriptPath,
  encodeCwd,
  setClaudeHome,
  writeEnvFile,
};
