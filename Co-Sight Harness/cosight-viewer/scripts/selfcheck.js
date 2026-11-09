#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
/**
 * Co-Sight Viewer 自检命令
 *
 * 诊断运行环境健康状态:
 *   A. Hook 配置检查  —— cosight / claude 两个 mode 的 settings.json 中 hook 是否正确
 *   B. 进程与端口检查 —— 重复实例(如 4830 与 4831 共存)、端口占用、PID 文件、发现文件、健康
 *   C. 环境与数据完整性 —— Node 版本、数据库、日志活跃度、原子写 .tmp 残留、版本一致性
 *
 * 用法:
 *   node scripts/selfcheck.js                # 全部检查
 *   node scripts/selfcheck.js --json         # 机器可读 JSON
 *   node scripts/selfcheck.js --fix          # 仅做文件系统安全清理(不杀进程、不改 hook)
 *   node scripts/selfcheck.js --verbose      # 显示 PASS/INFO 细节
 *   node scripts/selfcheck.js --port 4830    # 覆盖默认端口
 *   node scripts/selfcheck.js --home cosight=<path> --home claude=<path>  # 覆盖数据目录(测试/调试)
 *
 * 退出码: 0 = 无 FAIL, 1 = 有 WARN 无 FAIL, 2 = 有 FAIL
 */
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const http = require("node:http");

const { getViewerDataDir, getSourceHomes } = require("../server/lib/claude-home");
const { getApiBasePath } = require("../server/lib/hook-config");

const API_BASE = getApiBasePath();

// ─── 常量 ───
const HANDLER_NAME = "cosight-viewer-hook-handler.js";
// 只认官方文件名；裸 `hook-handler.js` 可能是其它工具的脚本，不能当成我们的。
const OUR_HANDLER_RE = /cosight-viewer-hook-handler\.js/;

// 与 scripts/install-hooks.js 保持一致
const HOOK_TYPES = [
  "PreToolUse",
  "PostToolUse",
  "Stop",
  "SubagentStop",
  "Notification",
  "SessionStart",
  "SessionEnd",
  "UserPromptSubmit",
];
const HOOKS_WITH_MATCHER = new Set([
  "PreToolUse",
  "PostToolUse",
  "Stop",
  "SubagentStop",
  "Notification",
]);

const LEVEL = { PASS: "PASS", INFO: "INFO", WARN: "WARN", FAIL: "FAIL" };

const DEFAULT_PORT = process.env.CO_SIGHT_PORT || "4830";

// "活跃"阈值:进程存活但超过 5 分钟无 DB / 日志写入视为可疑(wedged)
const ACTIVE_STALE_MS = 5 * 60 * 1000;

// ─── finding 构造 ───
function finding(level, category, message, details) {
  return { level, category, message, details: details || "" };
}
const pass = (cat, msg, det) => finding(LEVEL.PASS, cat, msg, det);
const info = (cat, msg, det) => finding(LEVEL.INFO, cat, msg, det);
const warn = (cat, msg, det) => finding(LEVEL.WARN, cat, msg, det);
const fail = (cat, msg, det) => finding(LEVEL.FAIL, cat, msg, det);

// ─── home 解析 ───
// 默认只看 VIEWER_SOURCES 启用的源；显式 homes（测试/--homes）优先。
function resolveHomes(overrides = {}) {
  if (overrides && Object.keys(overrides).length > 0) {
    return { ...overrides };
  }
  const homes = {};
  for (const source of getSourceHomes()) {
    homes[source.id] = source.home;
  }
  return homes;
}

// ─── hook 条目判定 ───
function isOurEntry(entry) {
  if (!entry || typeof entry !== "object") return false;
  if (typeof entry.command === "string" && OUR_HANDLER_RE.test(entry.command)) return true;
  if (Array.isArray(entry.hooks)) {
    return entry.hooks.some(
      (h) => h && typeof h.command === "string" && OUR_HANDLER_RE.test(h.command)
    );
  }
  return false;
}

/**
 * 从 hook 命令中解析出 handler 脚本路径。
 * 支持 `node "C:/path/x.js" Type`、`node 'path/x.js' Type`、`node /path/x.js Type`。
 */
function extractCommandPath(command) {
  if (!command) return null;
  const quoted = command.match(/"([^"]+\.js)"|'([^']+\.js)'/);
  if (quoted) return quoted[1] || quoted[2];
  const bare = command.match(/([^\s]+cosight-viewer-hook-handler\.js)/);
  return bare ? bare[1] : null;
}

// ─── A. Hook 配置检查 ───
function analyzeHookSettings(settingsPath, modeLabel) {
  const results = [];
  const cat = `${modeLabel} hook`;

  if (!fs.existsSync(settingsPath)) {
    results.push(
      fail(
        cat,
        `${modeLabel} settings.json 不存在: ${settingsPath}`,
        "无法注入 hook,请运行 npm run install-hooks 后重启会话"
      )
    );
    return { results, handlerPaths: [] };
  }

  let settings;
  try {
    settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  } catch (err) {
    results.push(fail(cat, `${modeLabel} settings.json JSON 解析失败`, err.message));
    return { results, handlerPaths: [] };
  }
  results.push(pass(cat, `${modeLabel} settings.json 存在且 JSON 有效`));

  const hooks = settings.hooks;
  if (!hooks || typeof hooks !== "object") {
    results.push(warn(cat, `${modeLabel} 缺少 hooks 配置`, "运行 npm run install-hooks 即可注入"));
    return { results, handlerPaths: [] };
  }
  results.push(pass(cat, `${modeLabel} hooks 配置已存在`));

  // 必需类型齐全
  const missing = HOOK_TYPES.filter((t) => !Array.isArray(hooks[t]) || hooks[t].length === 0);
  if (missing.length > 0) {
    results.push(
      warn(
        cat,
        `${modeLabel} 缺少 ${missing.length} 种必需 hook: ${missing.join(", ")}`,
        "运行 npm run install-hooks 补齐"
      )
    );
  } else {
    results.push(pass(cat, `${modeLabel} ${HOOK_TYPES.length} 种必需 hook 类型齐全`));
  }

  // 逐类型:重复条目 / handler 路径
  const handlerPaths = [];
  const duplicates = [];
  for (const t of HOOK_TYPES) {
    const entries = hooks[t];
    if (!Array.isArray(entries)) continue;
    const ours = entries.filter(isOurEntry);
    if (ours.length > 1) duplicates.push(`${t}(${ours.length} 条)`);
    for (const e of entries) {
      if (Array.isArray(e.hooks)) {
        for (const h of e.hooks) {
          const p = extractCommandPath(h && h.command);
          if (p) handlerPaths.push(p);
        }
      } else if (e.command) {
        const p = extractCommandPath(e.command);
        if (p) handlerPaths.push(p);
      }
    }
  }

  if (duplicates.length > 0) {
    results.push(
      warn(
        cat,
        `${modeLabel} 存在重复 hook 条目: ${duplicates.join(", ")}`,
        "运行 npm run install-hooks 会去重,或手动清理"
      )
    );
  } else {
    results.push(pass(cat, `${modeLabel} 无重复 hook 条目`));
  }

  const unique = [...new Set(handlerPaths)];
  if (unique.length === 0) {
    results.push(
      warn(cat, `${modeLabel} 未从 hook 命令解析出 handler 路径`, "hook 命令格式可能异常")
    );
  } else {
    const missingPaths = unique.filter((p) => !fs.existsSync(p));
    if (missingPaths.length > 0) {
      results.push(
        fail(
          cat,
          `${modeLabel} ${missingPaths.length} 个 handler 路径不存在`,
          `缺失:\n  ${missingPaths.join("\n  ")}\n  路径漂移:重新执行 npm run install-hooks`
        )
      );
    } else {
      results.push(pass(cat, `${modeLabel} handler 文件存在(${unique.length} 个唯一路径)`));
    }
  }

  return { results, handlerPaths: unique };
}

function analyzeHooks(homes) {
  const findings = [];
  const modes = Object.keys(homes);
  const collected = {};
  for (const mode of modes) {
    const out = analyzeHookSettings(path.join(homes[mode], "settings.json"), mode);
    findings.push(...out.results);
    collected[mode] = out.handlerPaths;
  }

  // 安装位置一致性:各启用源的 handler 是否指向同一安装
  const roots = {};
  for (const mode of modes) {
    if (collected[mode].length > 0) roots[mode] = path.resolve(path.dirname(collected[mode][0]));
  }
  const modesWithRoot = modes.filter((mode) => roots[mode]);
  if (modesWithRoot.length >= 2) {
    const [first, ...rest] = modesWithRoot;
    const mismatched = rest.filter((mode) => roots[mode] !== roots[first]);
    if (mismatched.length > 0) {
      const detail = modesWithRoot
        .map((mode) => `  ${mode} → ${roots[mode]}`)
        .join("\n");
      findings.push(
        warn(
          "安装位置",
          `${modesWithRoot.join(" / ")} 的 hook handler 指向不同位置(混合安装)`,
          `${detail}\n  多处可能是不同版本,建议统一为同一安装,避免多个版本同时收 hook`
        )
      );
    } else {
      findings.push(
        pass("安装位置", `${modesWithRoot.join(" / ")} 的 hook handler 指向同一位置`)
      );
    }
  }
  return findings;
}

// ─── 发现文件读取 ───
function readServerEntries(infoPath) {
  if (!fs.existsSync(infoPath)) return { entries: [], valid: true };
  try {
    const parsed = JSON.parse(fs.readFileSync(infoPath, "utf8"));
    const entries = Array.isArray(parsed.servers)
      ? parsed.servers.filter((s) => s && Number.isInteger(s.port))
      : Number.isInteger(parsed.port)
        ? [{ port: parsed.port, pid: parsed.pid, startedAt: parsed.startedAt }]
        : [];
    return { entries, valid: true };
  } catch {
    return { entries: [], valid: false };
  }
}

// 健康探测:GET ${API_BASE}/health,短超时,永不抛出
function probeHealth(port, timeoutMs = 2000) {
  return new Promise((resolve) => {
    const req = http.get(
      { hostname: "127.0.0.1", port, path: `${API_BASE}/health`, timeout: timeoutMs },
      (res) => {
        res.resume();
        res.on("end", () => resolve(res.statusCode === 200));
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

// ─── 默认依赖(生产环境;测试注入 fake 覆盖) ───
function defaultDeps() {
  const vp = require("./lib/viewer-process.cjs");
  const serverInfo = require("../server/lib/server-info");
  return {
    findViewerPids: () => vp.findViewerPids(),
    findPidsByPort: (port) => vp.findPidsByPort(port),
    readPidFile: () => {
      const pid = vp.readPidFromFile();
      return pid === null ? null : { pid, file: vp.PID_FILE };
    },
    isPidAlive: (pid) => vp.isAlive(pid),
    serverInfoPath: (modeHome) => serverInfo.getServerInfoPath(modeHome),
    viewerDataDir: () => getViewerDataDir(),
    healthProbe: (port) => probeHealth(port),
    resolveDbPath: () =>
      process.env.DASHBOARD_DB_PATH || path.join(getViewerDataDir(), "dashboard.db"),
  };
}

// ─── B. 进程与端口检查 ───
async function analyzeProcesses({ port = DEFAULT_PORT, homes, deps = {} }) {
  const d = { ...defaultDeps(), ...deps };
  const findings = [];
  const cat = "进程/端口";

  const viewerPids = d.findViewerPids();
  const portPids = d.findPidsByPort(port);
  const portNum = parseInt(port, 10);

  // 1. viewer 进程数
  if (viewerPids.length === 0) {
    findings.push(
      info(cat, "未检测到运行中的 viewer 进程", "启动命令: co-sight-viewer start 或 npm start")
    );
  } else if (viewerPids.length === 1) {
    findings.push(pass(cat, `viewer 进程唯一(PID ${viewerPids[0]})`));
  } else {
    findings.push(
      warn(
        cat,
        `检测到 ${viewerPids.length} 个 viewer 进程(PID ${viewerPids.join(", ")})`,
        "正常应只有 1 个。多余实例多来自 dev 与 production 共存,建议 co-sight-viewer stop 后重新 start"
      )
    );
  }

  // 2. 端口占用
  if (portPids.length === 0) {
    findings.push(info(cat, `端口 ${port} 未被监听`));
  } else {
    const foreign = portPids.filter((p) => !viewerPids.includes(p));
    const ours = portPids.filter((p) => viewerPids.includes(p));
    if (foreign.length > 0) {
      findings.push(
        fail(
          cat,
          `端口 ${port} 被非 viewer 进程占用(PID ${foreign.join(", ")})`,
          "启动会 EADDRINUSE,需先释放端口"
        )
      );
    }
    if (ours.length > 0) {
      findings.push(pass(cat, `端口 ${port} 由 viewer 进程监听(PID ${ours.join(", ")})`));
    }
  }

  // 3. 未监听默认端口的 viewer(如 dev 实例 4831)
  const extraPids = viewerPids.filter((p) => !portPids.includes(p));
  if (viewerPids.length > 1 && extraPids.length > 0) {
    findings.push(
      warn(
        cat,
        `存在未监听端口 ${port} 的 viewer 实例(PID ${extraPids.join(", ")})`,
        "疑似 dev(4831 等)与 production(4830)共存,产生重复数据链路"
      )
    );
  } else if (viewerPids.length === 1 && extraPids.length === 1 && portPids.length === 0) {
    findings.push(info(cat, `viewer 进程未监听默认端口 ${port}`, "可能通过 --port 指定了其他端口"));
  }

  // 4. PID 文件一致性
  const pidFile = d.readPidFile();
  if (pidFile && pidFile.pid) {
    if (!d.isPidAlive(pidFile.pid)) {
      findings.push(
        warn(
          cat,
          `PID 文件指向已退出进程(PID ${pidFile.pid})`,
          `残留:${pidFile.file}\n  可运行 --fix 清理`
        )
      );
    } else if (!viewerPids.includes(pidFile.pid) && !portPids.includes(pidFile.pid)) {
      findings.push(
        warn(cat, `PID 文件 PID ${pidFile.pid} 存活但非当前 viewer 进程`, "PID 可能已被复用")
      );
    } else {
      findings.push(pass(cat, `PID 文件一致(PID ${pidFile.pid})`));
    }
  } else {
    findings.push(info(cat, "无 PID 文件"));
  }

  // 5. 发现文件一致性(两个 mode)+ 收集健康检查候选端口
  const candidatePorts = new Set();
  for (const mode of Object.keys(homes)) {
    const infoPath = d.serverInfoPath(homes[mode]);
    if (!fs.existsSync(infoPath)) continue;
    const { entries, valid } = readServerEntries(infoPath);
    if (!valid) {
      findings.push(
        warn(cat, `${mode} 发现文件 JSON 无效: ${infoPath}`, "server-info 读取会退化为默认端口")
      );
      continue;
    }
    if (entries.length === 0) continue;
    const live = entries.filter((s) => Number.isInteger(s.pid) && d.isPidAlive(s.pid));
    const dead = entries.filter((s) => !Number.isInteger(s.pid) || !d.isPidAlive(s.pid));
    if (dead.length > 0) {
      findings.push(
        warn(
          cat,
          `${mode} 发现文件含 ${dead.length} 条死进程条目(${dead.map((s) => `${s.port}@${s.pid}`).join(", ")})`,
          "可运行 --fix 剔除"
        )
      );
    }
    for (const s of live) if (Number.isInteger(s.port)) candidatePorts.add(s.port);
    const ports = [...new Set(live.map((s) => s.port).filter(Number.isInteger))];
    if (ports.length > 1) {
      findings.push(
        warn(
          cat,
          `${mode} 发现文件记录多端口共存: ${ports.join(", ")}`,
          "多实例并存,建议仅保留一个"
        )
      );
    }
  }
  if (portPids.length > 0 && Number.isFinite(portNum)) candidatePorts.add(portNum);

  // 6. 健康检查(只探测有存活进程声称的端口)
  const unhealthy = [];
  const healthy = [];
  for (const cp of [...candidatePorts].filter((p) => Number.isFinite(p) && p > 0)) {
    if ((await d.healthProbe(cp)) === true) healthy.push(cp);
    else unhealthy.push(cp);
  }
  if (unhealthy.length > 0) {
    findings.push(
      fail(
        cat,
        `健康检查失败: ${unhealthy.join(", ")}`,
        "进程存活但 /api/health 无响应,可能 wedged,建议 co-sight-viewer stop 后重启"
      )
    );
  } else if (healthy.length > 0) {
    findings.push(pass(cat, `健康检查通过(${healthy.join(", ")})`));
  } else {
    findings.push(info(cat, "无存活实例,跳过健康检查"));
  }

  return findings;
}

// ─── C. 环境与数据完整性检查 ───

/**
 * 目录下最新的 cosight-viewer 日志文件 mtime。
 * pino-roll 按天轮转会生成 cosight-viewer.<N>.log,固定文件名 cosight-viewer.log
 * 可能长期不变导致误报"未写入",因此取目录内所有匹配文件的最新 mtime。
 * @returns {number|null} 最新 mtime(ms),无任何日志文件返回 null
 */
function getLatestLogMtime(logDir) {
  if (!fs.existsSync(logDir)) return null;
  let latest = null;
  try {
    for (const f of fs.readdirSync(logDir)) {
      if (!/^cosight-viewer.*\.log$/.test(f)) continue;
      const mtime = fs.statSync(path.join(logDir, f)).mtimeMs;
      if (latest === null || mtime > latest) latest = mtime;
    }
  } catch {}
  return latest;
}

/**
 * 检测当前活跃运行的模式(claude / cosight)。
 * 依据: 两个 mode 的发现文件中,与当前存活 viewer 进程 PID 匹配的条目 mode。
 * 无运行中的 viewer 进程时返回 null。
 */
function detectActiveMode(homes, d) {
  const viewerPids = d.findViewerPids();
  if (viewerPids.length === 0) return null;
  for (const mode of Object.keys(homes)) {
    const { entries } = readServerEntries(d.serverInfoPath(homes[mode]));
    if (entries.some((s) => viewerPids.includes(s.pid))) return mode;
  }
  // 发现文件无匹配(可能被 --fix 清理过):退回环境变量
  return process.env.CO_SIGHT_MODE || null;
}

function analyzeEnvironment({ homes, deps = {} }) {
  const d = { ...defaultDeps(), ...deps };
  const viewerDataDir = d.viewerDataDir();
  const findings = [];
  const cat = "环境与数据";

  // Node 版本(对照 engines.node)
  const [majorS, minorS] = process.versions.node.split(".");
  const major = parseInt(majorS, 10);
  const minor = parseInt(minorS, 10);
  const nodeOk = major > 22 || (major === 22 && minor >= 5);
  if (nodeOk) {
    findings.push(pass(cat, `Node 版本 ${process.versions.node} ≥ 22.5.0`));
  } else {
    findings.push(
      warn(
        cat,
        `Node 版本 ${process.versions.node} < 22.5.0`,
        "node:sqlite 回退链路需要 Node ≥22.5"
      )
    );
  }

  // 数据目录
  for (const mode of Object.keys(homes)) {
    const home = homes[mode];
    if (fs.existsSync(home)) {
      findings.push(pass(cat, `${mode} 数据目录存在: ${home}`));
    } else {
      findings.push(info(cat, `${mode} 数据目录不存在: ${home}`, "该模式尚未使用过"));
    }
  }

  // 数据库文件：优先当前 viewer 数据目录；只有它不存在时才回退到历史位置
  // （升级/迁移场景），避免旧位置的近期写入掩盖当前实例。
  const primaryDb = deps.resolveDbPath
    ? d.resolveDbPath()
    : path.join(viewerDataDir, "dashboard.db");
  // 注入 viewerDataDir 时（测试）只看注入的目录，避免真实用户目录里的
  // 数据库干扰断言；生产环境才回退到历史位置。
  const injectedViewerDir = typeof deps.viewerDataDir === "function";
  const legacyDbCandidates = (
    injectedViewerDir
      ? [
          path.join(viewerDataDir, "dashboard.db"),
          ...Object.values(homes).flatMap((home) => [
            path.join(home, "dashboard.db"),
            path.join(home, "task-management", "dashboard.db"),
          ]),
        ]
      : [
          // Viewer-owned data directory (DASHBOARD_DATA_DIR / COSIGHT_HOME)
          path.join(viewerDataDir, "dashboard.db"),
          // New default location: ~/.cosight-harness/cosight-viewer/
          path.join(os.homedir(), ".cosight-harness", "cosight-viewer", "dashboard.db"),
          // Legacy location (for backward compatibility): ~/.cosightharness/cosightviewer/
          path.join(os.homedir(), ".cosightharness", "cosightviewer", "dashboard.db"),
          ...Object.values(homes).flatMap((home) => [
            path.join(home, "dashboard.db"),
            path.join(home, "task-management", "dashboard.db"),
          ]),
          path.join(__dirname, "..", "data", "dashboard.db"),
        ]
  ).filter(Boolean);
  const dbCandidates = fs.existsSync(primaryDb)
    ? [primaryDb]
    : [primaryDb, ...legacyDbCandidates];
  const existingDbs = dbCandidates
    .filter((p) => fs.existsSync(p))
    .map((p) => ({ p, mtime: fs.statSync(p).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);
  if (existingDbs.length > 0) {
    const { p: dbPath, mtime } = existingDbs[0];
    const age = Date.now() - mtime;
    if (age > ACTIVE_STALE_MS) {
      // 无新会话事件时 DB 长时间不写入属正常,仅提示
      findings.push(
        info(
          cat,
          `数据库文件近期未写入(${Math.round(age / 60000)} 分钟): ${dbPath}`,
          "可能近期无新会话事件;若服务在运行且持续无会话,属正常"
        )
      );
    } else {
      findings.push(pass(cat, "数据库文件存在且近期有写入"));
    }
  } else {
    findings.push(info(cat, "未找到数据库文件", "服务启动后会自动创建"));
  }

  // 日志活跃度：双源共用一份 viewer 日志，位置在 viewer 数据目录下。
  {
    const logDir = path.join(viewerDataDir, "logs", "cosight-viewer");
    const latestMtime = getLatestLogMtime(logDir);
    if (latestMtime === null) {
      findings.push(info(cat, "无 viewer 日志文件", "服务从未启动或日志被清理"));
    } else {
      const age = Date.now() - latestMtime;
      if (age <= ACTIVE_STALE_MS) {
        findings.push(pass(cat, "日志近期有写入"));
      } else {
        findings.push(
          info(
            cat,
            `日志较旧(${Math.round(age / 60000)} 分钟未写): ${logDir}`,
            "服务未运行或近期无请求时，日志不更新属正常"
          )
        );
      }
    }
  }

  // 发现文件 .tmp 原子写残留
  for (const mode of Object.keys(homes)) {
    const home = homes[mode];
    if (!fs.existsSync(home)) continue;
    let staleTmp = [];
    try {
      staleTmp = fs
        .readdirSync(home)
        .filter((f) => f.startsWith(".co-sight-viewer.json.") && f.endsWith(".tmp"));
    } catch {}
    if (staleTmp.length > 0) {
      findings.push(
        warn(
          cat,
          `${mode} 存在 ${staleTmp.length} 个原子写残留 .tmp 文件`,
          `${staleTmp.join("\n  ")}\n  可运行 --fix 清理`
        )
      );
    } else {
      findings.push(pass(cat, `${mode} 无发现文件 .tmp 残留`));
    }
  }

  // 版本一致性
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
    const bi = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "build-info.json"), "utf8"));
    if (pkg.version && bi.version && pkg.version !== bi.version) {
      findings.push(
        warn(
          cat,
          `版本不一致: package.json ${pkg.version} vs build-info.json ${bi.version}`,
          "构建产物与包版本不同步"
        )
      );
    } else if (pkg.version) {
      findings.push(pass(cat, `包版本 ${pkg.version}`));
    }
  } catch {}

  return findings;
}

// ─── --fix 安全清理(仅文件系统,不杀进程不改 hook) ───
function applyFixes({ homes, deps = {} }) {
  const d = { ...defaultDeps(), ...deps };
  const fixed = [];
  const errors = [];

  // 1. 残留 PID 文件
  const pidFile = d.readPidFile();
  if (pidFile && pidFile.pid && !d.isPidAlive(pidFile.pid)) {
    try {
      fs.unlinkSync(pidFile.file);
      fixed.push(`删除残留 PID 文件 ${pidFile.file}`);
    } catch (err) {
      errors.push(`删除 PID 文件失败: ${err.message}`);
    }
  }

  // 2. 发现文件死条目剔除
  for (const mode of Object.keys(homes)) {
    const infoPath = d.serverInfoPath(homes[mode]);
    if (!fs.existsSync(infoPath)) continue;
    try {
      const parsed = JSON.parse(fs.readFileSync(infoPath, "utf8"));
      const entries = Array.isArray(parsed.servers)
        ? parsed.servers.filter((s) => s && Number.isInteger(s.port))
        : Number.isInteger(parsed.port)
          ? [{ port: parsed.port, pid: parsed.pid, startedAt: parsed.startedAt }]
          : [];
      const live = entries.filter((s) => Number.isInteger(s.pid) && d.isPidAlive(s.pid));
      if (live.length === entries.length) continue;
      if (live.length === 0) {
        fs.unlinkSync(infoPath);
        fixed.push(`删除发现文件(条目全部已死): ${infoPath}`);
      } else {
        const recent = live.reduce((a, b) => (b.startedAt > (a.startedAt || "") ? b : a), live[0]);
        const payload = JSON.stringify(
          { port: recent.port, pid: recent.pid, startedAt: recent.startedAt, servers: live },
          null,
          2
        );
        fs.writeFileSync(infoPath, payload);
        fixed.push(`剔除 ${entries.length - live.length} 条死条目: ${infoPath}`);
      }
    } catch (err) {
      errors.push(`处理发现文件失败 ${infoPath}: ${err.message}`);
    }
  }

  // 3. .tmp 原子写残留
  for (const mode of Object.keys(homes)) {
    const home = homes[mode];
    if (!fs.existsSync(home)) continue;
    let names = [];
    try {
      names = fs
        .readdirSync(home)
        .filter((f) => f.startsWith(".co-sight-viewer.json.") && f.endsWith(".tmp"));
    } catch {}
    for (const f of names) {
      try {
        fs.unlinkSync(path.join(home, f));
        fixed.push(`删除残留 .tmp 文件 ${f}`);
      } catch (err) {
        errors.push(`删除 ${f} 失败: ${err.message}`);
      }
    }
  }

  return { fixed, errors };
}

// ─── 编排 ───
async function runSelfCheck(opts = {}) {
  const homes = resolveHomes(opts.homes);
  const deps = { ...defaultDeps(), ...(opts.deps || {}) };
  const port = opts.port || DEFAULT_PORT;

  const groups = [
    { group: "Hook 配置检查", findings: analyzeHooks(homes) },
    { group: "进程与端口检查", findings: await analyzeProcesses({ port, homes, deps }) },
    { group: "环境与数据完整性", findings: analyzeEnvironment({ homes, deps }) },
  ];
  const fix = opts.fix ? applyFixes({ homes, deps }) : null;
  return { groups, fix, homes };
}

// ─── 报告输出 ───
function formatReport({ groups, fix, opts = {} }) {
  const ICONS = { PASS: "✅", INFO: "ℹ️", WARN: "⚠️", FAIL: "❌" };
  const lines = ["", "=== Co-Sight Viewer 自检 ===", ""];
  let passCount = 0;
  let infoCount = 0;
  let warnCount = 0;
  let failCount = 0;

  for (const g of groups) {
    lines.push(`【${g.group}】`);
    if (g.findings.length === 0) {
      lines.push("  (无检查项)");
    }
    for (const f of g.findings) {
      if (f.level === LEVEL.PASS) passCount++;
      else if (f.level === LEVEL.INFO) infoCount++;
      else if (f.level === LEVEL.WARN) warnCount++;
      else failCount++;
      if (f.level === LEVEL.PASS && !opts.verbose) continue;
      lines.push(`  ${ICONS[f.level]} [${f.level}] ${f.message}`);
      if (opts.verbose && f.details) {
        lines.push(`      ${String(f.details).replace(/\n/g, "\n      ")}`);
      }
    }
    lines.push("");
  }

  if (fix) {
    lines.push("【--fix 修复】");
    if (fix.errors.length > 0) for (const m of fix.errors) lines.push(`  ❌ ${m}`);
    if (fix.fixed.length > 0) for (const m of fix.fixed) lines.push(`  🛠️  ${m}`);
    if (fix.fixed.length === 0 && fix.errors.length === 0) lines.push("  无需修复");
    lines.push("");
  }

  lines.push(`结果: ${passCount} 通过 | ${infoCount} 提示 | ${warnCount} 警告 | ${failCount} 失败`);
  return lines.join("\n");
}

function countLevel(groups, level) {
  return groups.reduce((n, g) => n + g.findings.filter((f) => f.level === level).length, 0);
}

// ─── CLI 入口 ───
async function runSelfCheckCli(args) {
  const opts = { json: false, fix: false, verbose: false, port: null, homes: {} };
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--json":
        opts.json = true;
        break;
      case "--fix":
        opts.fix = true;
        break;
      case "--verbose":
        opts.verbose = true;
        break;
      case "--port":
        opts.port = args[++i];
        break;
      case "--home": {
        const kv = args[++i];
        const idx = kv.indexOf("=");
        if (idx > 0) opts.homes[kv.slice(0, idx)] = kv.slice(idx + 1);
        break;
      }
      default:
        break;
    }
  }

  try {
    const result = await runSelfCheck(opts);
    if (opts.json) {
      process.stdout.write(
        JSON.stringify({ ts: new Date().toISOString(), ...result }, null, 2) + "\n"
      );
    } else {
      process.stdout.write(formatReport({ ...result, opts }) + "\n");
    }
    const failCount = countLevel(result.groups, LEVEL.FAIL);
    const warnCount = countLevel(result.groups, LEVEL.WARN);
    process.exit(failCount > 0 ? 2 : warnCount > 0 ? 1 : 0);
  } catch (err) {
    console.error(`[selfcheck] 自检失败: ${err.message}`);
    process.exit(2);
  }
}

if (require.main === module) {
  runSelfCheckCli(process.argv.slice(2));
}

module.exports = {
  LEVEL,
  HOOK_TYPES,
  HANDLER_NAME,
  isOurEntry,
  extractCommandPath,
  analyzeHookSettings,
  analyzeHooks,
  analyzeProcesses,
  analyzeEnvironment,
  applyFixes,
  runSelfCheck,
  runSelfCheckCli,
  formatReport,
  probeHealth,
  readServerEntries,
  resolveHomes,
  getLatestLogMtime,
  detectActiveMode,
};
