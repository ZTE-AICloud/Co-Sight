// SPDX-License-Identifier: Apache-2.0
/**
 * @file Unit tests for scripts/selfcheck.js — hook 配置 / 进程与端口 / 环境数据 / --fix 清理。
 *
 * Strategy: 分析函数接收注入的依赖对象(进程查找、探活、健康探测等)与显式 homes,
 * 测试用临时目录写 fixture + fake 依赖,不触发真实的 PowerShell / netstat / HTTP。
 */
const { describe, it, before, after } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

const {
  LEVEL,
  isOurEntry,
  extractCommandPath,
  analyzeHookSettings,
  analyzeHooks,
  analyzeProcesses,
  analyzeEnvironment,
  applyFixes,
  runSelfCheck,
  formatReport,
  getLatestLogMtime,
} = require("../selfcheck");

let TMP_ROOT;
let CLAUDE_HOME;
let COSIGHT_HOME;

before(() => {
  TMP_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), "cosight-selfcheck-"));
  CLAUDE_HOME = path.join(TMP_ROOT, "claude");
  COSIGHT_HOME = path.join(TMP_ROOT, "cosight");
  fs.mkdirSync(CLAUDE_HOME, { recursive: true });
  fs.mkdirSync(COSIGHT_HOME, { recursive: true });
});

after(() => {
  try {
    fs.rmSync(TMP_ROOT, { recursive: true, force: true });
  } catch {}
});

const homes = () => ({ claude: CLAUDE_HOME, cosight: COSIGHT_HOME });

function writeSettings(home, settings) {
  fs.writeFileSync(path.join(home, "settings.json"), JSON.stringify(settings, null, 2));
}

function writeDiscovery(home, servers) {
  const recent = servers[servers.length - 1] || { port: 0, pid: 0, startedAt: "" };
  fs.writeFileSync(
    path.join(home, ".co-sight-viewer.json"),
    JSON.stringify({ port: recent.port, pid: recent.pid, startedAt: recent.startedAt, servers }, null, 2)
  );
}

function fullHookSettings(handlerPath) {
  const entry = (t) => ({ hooks: [{ type: "command", command: `node "${handlerPath}" ${t}` }] });
  const entryWithMatcher = (t) => ({ matcher: "*", hooks: [{ type: "command", command: `node "${handlerPath}" ${t}` }] });
  return {
    hooks: {
      PreToolUse: [entryWithMatcher("PreToolUse")],
      PostToolUse: [entryWithMatcher("PostToolUse")],
      Stop: [entryWithMatcher("Stop")],
      SubagentStop: [entryWithMatcher("SubagentStop")],
      Notification: [entryWithMatcher("Notification")],
      SessionStart: [entry("SessionStart")],
      SessionEnd: [entry("SessionEnd")],
      UserPromptSubmit: [entry("UserPromptSubmit")],
    },
  };
}

// ─── 工具函数 ───

describe("extractCommandPath", () => {
  it("解析双引号路径", () => {
    assert.equal(extractCommandPath('node "C:/a/b/cosight-viewer-hook-handler.js" PreToolUse'), "C:/a/b/cosight-viewer-hook-handler.js");
  });
  it("解析单引号路径", () => {
    assert.equal(extractCommandPath("node '/a/b/cosight-viewer-hook-handler.js' Stop"), "/a/b/cosight-viewer-hook-handler.js");
  });
  it("解析无引号路径", () => {
    assert.equal(
      extractCommandPath("node /a/b/cosight-viewer-hook-handler.js PostToolUse"),
      "/a/b/cosight-viewer-hook-handler.js"
    );
  });
  it("裸 hook-handler.js 不解析（可能是其它工具的脚本）", () => {
    assert.equal(extractCommandPath("node /a/b/hook-handler.js PostToolUse"), null);
  });
  it("无命令返回 null", () => {
    assert.equal(extractCommandPath(null), null);
    assert.equal(extractCommandPath(undefined), null);
    assert.equal(extractCommandPath(""), null);
  });
});

describe("isOurEntry", () => {
  it("识别新版 hooks[] 条目", () => {
    assert.equal(isOurEntry({ hooks: [{ command: 'node "/x/cosight-viewer-hook-handler.js" PreToolUse' }] }), true);
  });
  it("识别旧格式 command 字段条目", () => {
    assert.equal(isOurEntry({ command: 'node "/x/cosight-viewer-hook-handler.js" Stop' }), true);
  });
  it("不误判其他工具的 hook", () => {
    assert.equal(isOurEntry({ hooks: [{ command: "specstory sync claude" }] }), false);
  });
  it("裸 hook-handler.js 不当作我们的条目", () => {
    assert.equal(isOurEntry({ command: 'node "/x/hook-handler.js" Stop' }), false);
  });
  it("空条目返回 false", () => {
    assert.equal(isOurEntry({}), false);
  });
});

// ─── A. Hook 配置检查 ───

describe("analyzeHookSettings", () => {
  it("settings.json 不存在 → FAIL", () => {
    const { results } = analyzeHookSettings(path.join(COSIGHT_HOME, "nonexistent.json"), "cosight");
    assert.ok(results.some((f) => f.level === LEVEL.FAIL));
  });

  it("JSON 解析失败 → FAIL", () => {
    fs.writeFileSync(path.join(COSIGHT_HOME, "bad.json"), "{ not valid");
    const { results } = analyzeHookSettings(path.join(COSIGHT_HOME, "bad.json"), "cosight");
    assert.ok(results.some((f) => f.level === LEVEL.FAIL && /解析失败/.test(f.message)));
  });

  it("缺失必需 hook 类型 → WARN", () => {
    writeSettings(COSIGHT_HOME, { hooks: { PreToolUse: [] } });
    const { results } = analyzeHookSettings(path.join(COSIGHT_HOME, "settings.json"), "cosight");
    assert.ok(results.some((f) => f.level === LEVEL.WARN && /缺少/.test(f.message)));
  });

  it("handler 路径不存在 → FAIL", () => {
    const ghost = path.join(TMP_ROOT, "missing", "cosight-viewer-hook-handler.js");
    writeSettings(COSIGHT_HOME, fullHookSettings(ghost));
    const { results } = analyzeHookSettings(path.join(COSIGHT_HOME, "settings.json"), "cosight");
    assert.ok(results.some((f) => f.level === LEVEL.FAIL && /handler 路径不存在/.test(f.message)));
  });

  it("重复条目 → WARN", () => {
    const handler = path.join(COSIGHT_HOME, "cosight-viewer-hook-handler.js");
    fs.writeFileSync(handler, "");
    const base = fullHookSettings(handler);
    base.hooks.PreToolUse.push(base.hooks.PreToolUse[0]);
    writeSettings(COSIGHT_HOME, base);
    const { results } = analyzeHookSettings(path.join(COSIGHT_HOME, "settings.json"), "cosight");
    assert.ok(results.some((f) => f.level === LEVEL.WARN && /重复 hook 条目/.test(f.message)));
  });

  it("完整合法配置 → 无 FAIL 且 handler 路径通过", () => {
    const handler = path.join(COSIGHT_HOME, "cosight-viewer-hook-handler.js");
    fs.writeFileSync(handler, "");
    writeSettings(COSIGHT_HOME, fullHookSettings(handler));
    const { results } = analyzeHookSettings(path.join(COSIGHT_HOME, "settings.json"), "cosight");
    assert.equal(results.some((f) => f.level === LEVEL.FAIL), false);
    assert.ok(results.some((f) => f.level === LEVEL.PASS && /handler 文件存在/.test(f.message)));
  });
});

describe("analyzeHooks", () => {
  it("两 mode handler 指向不同位置 → WARN(混合安装)", () => {
    const claudeHandler = path.join(CLAUDE_HOME, "node_modules", "co-sight-viewer", "scripts", "cosight-viewer-hook-handler.js");
    const cosightHandler = path.join(COSIGHT_HOME, "repo", "scripts", "cosight-viewer-hook-handler.js");
    fs.mkdirSync(path.dirname(claudeHandler), { recursive: true });
    fs.mkdirSync(path.dirname(cosightHandler), { recursive: true });
    fs.writeFileSync(claudeHandler, "");
    fs.writeFileSync(cosightHandler, "");
    writeSettings(CLAUDE_HOME, fullHookSettings(claudeHandler));
    writeSettings(COSIGHT_HOME, fullHookSettings(cosightHandler));
    const findings = analyzeHooks(homes());
    assert.ok(findings.some((f) => f.level === LEVEL.WARN && /不同位置/.test(f.message)));
  });

  it("两 mode handler 指向同一位置 → PASS", () => {
    const shared = path.join(COSIGHT_HOME, "scripts", "cosight-viewer-hook-handler.js");
    fs.mkdirSync(path.dirname(shared), { recursive: true });
    fs.writeFileSync(shared, "");
    writeSettings(CLAUDE_HOME, fullHookSettings(shared));
    writeSettings(COSIGHT_HOME, fullHookSettings(shared));
    const findings = analyzeHooks(homes());
    assert.ok(findings.some((f) => f.level === LEVEL.PASS && /同一位置/.test(f.message)));
  });
});

// ─── B. 进程与端口检查(注入 fake 依赖) ───

describe("analyzeProcesses", () => {
  function makeDeps(overrides = {}) {
    return {
      findViewerPids: () => [],
      findPidsByPort: () => [],
      readPidFile: () => null,
      isPidAlive: () => true,
      serverInfoPath: (home) => path.join(home, ".co-sight-viewer.json"),
      healthProbe: async () => true,
      ...overrides,
    };
  }

  function cleanHome() {
    // 重置两个 home 的发现文件与 settings
    for (const h of [CLAUDE_HOME, COSIGHT_HOME]) {
      try { fs.rmSync(path.join(h, ".co-sight-viewer.json"), { force: true }); } catch {}
      try { fs.rmSync(path.join(h, "settings.json"), { force: true }); } catch {}
    }
  }

  it("单实例 + 端口一致 + 健康通过 → 无 FAIL", async () => {
    cleanHome();
    const deps = makeDeps({
      findViewerPids: () => [1001],
      findPidsByPort: () => [1001],
      readPidFile: () => ({ pid: 1001, file: "/tmp/co-sight-viewer.pid" }),
      isPidAlive: (pid) => pid === 1001,
    });
    const findings = await analyzeProcesses({ port: "4830", homes: homes(), deps });
    assert.equal(findings.some((f) => f.level === LEVEL.FAIL), false);
    assert.ok(findings.some((f) => f.level === LEVEL.PASS && /健康检查通过/.test(f.message)));
  });

  it("多实例(4830 与 4831 共存) → WARN", async () => {
    cleanHome();
    const deps = makeDeps({
      findViewerPids: () => [1001, 1002],
      findPidsByPort: () => [1001],
      isPidAlive: () => true,
    });
    const findings = await analyzeProcesses({ port: "4830", homes: homes(), deps });
    assert.ok(findings.some((f) => f.level === LEVEL.WARN && /2 个 viewer 进程/.test(f.message)));
    assert.ok(findings.some((f) => f.level === LEVEL.WARN && /未监听端口/.test(f.message)));
  });

  it("端口被非 viewer 进程占用 → FAIL", async () => {
    cleanHome();
    const deps = makeDeps({
      findViewerPids: () => [],
      findPidsByPort: () => [9999],
      isPidAlive: () => true,
    });
    const findings = await analyzeProcesses({ port: "4830", homes: homes(), deps });
    assert.ok(findings.some((f) => f.level === LEVEL.FAIL && /非 viewer 进程占用/.test(f.message)));
  });

  it("PID 文件指向已退出进程 → WARN", async () => {
    cleanHome();
    const deps = makeDeps({
      findViewerPids: () => [1001],
      findPidsByPort: () => [1001],
      readPidFile: () => ({ pid: 12345, file: "/tmp/co-sight-viewer.pid" }),
      isPidAlive: (pid) => pid === 1001,
    });
    const findings = await analyzeProcesses({ port: "4830", homes: homes(), deps });
    assert.ok(findings.some((f) => f.level === LEVEL.WARN && /PID 文件指向已退出进程/.test(f.message)));
  });

  it("发现文件含死进程条目 → WARN", async () => {
    cleanHome();
    writeDiscovery(COSIGHT_HOME, [
      { port: 4830, pid: 1001, startedAt: "2026-08-01T00:00:00Z", mode: "cosight" },
      { port: 4831, pid: 1002, startedAt: "2026-08-02T00:00:00Z", mode: "cosight" },
    ]);
    const deps = makeDeps({
      findViewerPids: () => [1001],
      findPidsByPort: () => [1001],
      isPidAlive: (pid) => pid === 1001,
    });
    const findings = await analyzeProcesses({ port: "4830", homes: homes(), deps });
    assert.ok(findings.some((f) => f.level === LEVEL.WARN && /死进程条目/.test(f.message)));
  });

  it("进程存活但健康检查失败 → FAIL(wedged)", async () => {
    cleanHome();
    writeDiscovery(COSIGHT_HOME, [{ port: 4830, pid: 1001, startedAt: "2026-08-01T00:00:00Z", mode: "cosight" }]);
    const deps = makeDeps({
      findViewerPids: () => [1001],
      findPidsByPort: () => [1001],
      isPidAlive: () => true,
      healthProbe: async () => false,
    });
    const findings = await analyzeProcesses({ port: "4830", homes: homes(), deps });
    assert.ok(findings.some((f) => f.level === LEVEL.FAIL && /健康检查失败/.test(f.message)));
  });
});

// ─── --fix 清理 ───

describe("applyFixes", () => {
  it("删除残留 PID 文件、剔除死条目、清理 .tmp 残留", () => {
    // PID 文件残留(指向死进程)
    const pidFilePath = path.join(TMP_ROOT, "co-sight-viewer.pid");
    fs.writeFileSync(pidFilePath, "12345");
    const deps = {
      readPidFile: () => ({ pid: 12345, file: pidFilePath }),
      isPidAlive: (pid) => pid === 1001,
      serverInfoPath: (home) => path.join(home, ".co-sight-viewer.json"),
    };

    // cosight 发现文件:全部死条目 → 应删除文件
    writeDiscovery(COSIGHT_HOME, [
      { port: 4830, pid: 1002, startedAt: "2026-08-01T00:00:00Z", mode: "cosight" },
    ]);
    // claude 发现文件:一活一死 → 应保留活条目
    writeDiscovery(CLAUDE_HOME, [
      { port: 4830, pid: 1001, startedAt: "2026-08-01T00:00:00Z", mode: "claude" },
      { port: 4831, pid: 1002, startedAt: "2026-08-02T00:00:00Z", mode: "claude" },
    ]);
    // .tmp 残留
    fs.writeFileSync(path.join(COSIGHT_HOME, ".co-sight-viewer.json.111.tmp"), "{}");
    fs.writeFileSync(path.join(CLAUDE_HOME, ".co-sight-viewer.json.222.tmp"), "{}");

    const { fixed, errors } = applyFixes({ homes: homes(), deps });
    assert.deepEqual(errors, []);

    // PID 文件已删
    assert.equal(fs.existsSync(pidFilePath), false);
    assert.ok(fixed.some((m) => /删除残留 PID 文件/.test(m)));

    // cosight 发现文件(全死)已删
    assert.equal(fs.existsSync(path.join(COSIGHT_HOME, ".co-sight-viewer.json")), false);
    assert.ok(fixed.some((m) => /删除发现文件/.test(m)));

    // claude 发现文件只保留活条目 4830@1001
    const claudeInfo = JSON.parse(fs.readFileSync(path.join(CLAUDE_HOME, ".co-sight-viewer.json"), "utf8"));
    assert.deepEqual(
      claudeInfo.servers.map((s) => s.pid),
      [1001]
    );
    assert.ok(fixed.some((m) => /剔除 1 条死条目/.test(m)));

    // .tmp 已清理
    assert.equal(fs.existsSync(path.join(COSIGHT_HOME, ".co-sight-viewer.json.111.tmp")), false);
    assert.equal(fs.existsSync(path.join(CLAUDE_HOME, ".co-sight-viewer.json.222.tmp")), false);
  });
});

// ─── 日志活跃度(轮转文件识别) ───

describe("getLatestLogMtime", () => {
  it("目录不存在返回 null", () => {
    assert.equal(getLatestLogMtime(path.join(TMP_ROOT, "no-such-dir")), null);
  });

  it("取最新文件(含 pino-roll 轮转 .N.log)的 mtime", () => {
    const logDir = path.join(TMP_ROOT, "logs-mtime-test");
    fs.mkdirSync(logDir, { recursive: true });
    const fixed = path.join(logDir, "cosight-viewer.log");
    const rotated = path.join(logDir, "cosight-viewer.33.log");
    fs.writeFileSync(fixed, "old");
    fs.utimesSync(fixed, new Date(Date.now() - 86400000), new Date(Date.now() - 86400000)); // 1天前
    fs.writeFileSync(rotated, "recent");
    const latest = getLatestLogMtime(logDir);
    assert.ok(latest !== null);
    assert.ok(Math.abs(latest - fs.statSync(rotated).mtimeMs) < 1000, "应取到最新轮转文件的 mtime");
  });
});

describe("analyzeEnvironment 日志检查", () => {
  it("轮转文件近期更新 → 日志 PASS(不误报固定旧文件)", () => {
    const isoHome = path.join(TMP_ROOT, "logs-pass-" + Math.random().toString(36).slice(2));
    fs.mkdirSync(isoHome, { recursive: true });
    const logDir = path.join(isoHome, "logs", "cosight-viewer");
    fs.mkdirSync(logDir, { recursive: true });
    const fixed = path.join(logDir, "cosight-viewer.log");
    const rotated = path.join(logDir, "cosight-viewer.33.log");
    fs.writeFileSync(fixed, "old");
    fs.utimesSync(fixed, new Date(Date.now() - 86400000), new Date(Date.now() - 86400000)); // 固定文件旧
    fs.writeFileSync(rotated, "recent"); // 轮转文件新
    const findings = analyzeEnvironment({
      homes: { claude: isoHome, cosight: isoHome },
      deps: { viewerDataDir: () => isoHome },
    });
    assert.ok(
      findings.some((f) => f.level === LEVEL.PASS && /日志近期有写入/.test(f.message)),
      "应识别到近期轮转文件并判定日志活跃"
    );
  });

  it("旧日志 → INFO 而非 WARN(无新请求时日志不更新属正常)", () => {
    const isoHome = path.join(TMP_ROOT, "logs-active-" + Math.random().toString(36).slice(2));
    fs.mkdirSync(isoHome, { recursive: true });
    // 发现文件标记有一个存活 viewer(pid 1001)
    writeDiscovery(isoHome, [{ port: 4830, pid: 1001, startedAt: "2026-08-01T00:00:00Z" }]);
    // 旧日志
    const logDir = path.join(isoHome, "logs", "cosight-viewer");
    fs.mkdirSync(logDir, { recursive: true });
    const p = path.join(logDir, "cosight-viewer.log");
    fs.writeFileSync(p, "old");
    fs.utimesSync(p, new Date(Date.now() - 86400000), new Date(Date.now() - 86400000)); // 1天前
    const findings = analyzeEnvironment({
      homes: { claude: isoHome, cosight: isoHome },
      deps: { findViewerPids: () => [1001], viewerDataDir: () => isoHome },
    });
    assert.ok(findings.some((f) => f.level === LEVEL.INFO && /日志较旧/.test(f.message)));
    assert.equal(findings.some((f) => f.level === LEVEL.WARN && /日志.*未写入/.test(f.message)), false);
  });

  it("无运行进程且日志较旧 → INFO 而非 WARN", () => {
    const isoHome = path.join(TMP_ROOT, "logs-idle-" + Math.random().toString(36).slice(2));
    fs.mkdirSync(isoHome, { recursive: true });
    const logDir = path.join(isoHome, "logs", "cosight-viewer");
    fs.mkdirSync(logDir, { recursive: true });
    const p = path.join(logDir, "cosight-viewer.log");
    fs.writeFileSync(p, "old");
    fs.utimesSync(p, new Date(Date.now() - 86400000), new Date(Date.now() - 86400000)); // 1天前
    const findings = analyzeEnvironment({
      homes: { claude: isoHome, cosight: isoHome },
      deps: { viewerDataDir: () => isoHome },
    });
    assert.ok(findings.some((f) => f.level === LEVEL.INFO && /日志较旧/.test(f.message)));
    assert.equal(findings.some((f) => f.level === LEVEL.WARN && /日志.*未写入/.test(f.message)), false);
  });

  it("数据库长期未写入 → INFO(可能无新会话,正常)而非 WARN", () => {
    const isoHome = path.join(TMP_ROOT, "db-stale-" + Math.random().toString(36).slice(2));
    fs.mkdirSync(isoHome, { recursive: true });
    const dbDir = path.join(isoHome, "task-management");
    fs.mkdirSync(dbDir, { recursive: true });
    const dbPath = path.join(dbDir, "dashboard.db");
    fs.writeFileSync(dbPath, "sqlite");
    fs.utimesSync(dbPath, new Date(Date.now() - 86400000), new Date(Date.now() - 86400000)); // 1天前
    const findings = analyzeEnvironment({
      homes: { claude: isoHome, cosight: isoHome },
      deps: { viewerDataDir: () => isoHome },
    });
    assert.ok(findings.some((f) => f.level === LEVEL.INFO && /数据库文件近期未写入/.test(f.message)));
    assert.equal(findings.some((f) => f.level === LEVEL.WARN && /数据库/.test(f.message)), false);
  });

  it("无日志目录 → INFO(无文件)", () => {
    const cleanHome = path.join(TMP_ROOT, "empty-home-" + Date.now());
    fs.mkdirSync(cleanHome, { recursive: true });
    const findings = analyzeEnvironment({
      homes: { claude: cleanHome, cosight: cleanHome },
      deps: { viewerDataDir: () => cleanHome },
    });
    assert.ok(findings.some((f) => f.level === LEVEL.INFO && /无 viewer 日志文件/.test(f.message)));
  });
});

// ─── 编排 ───

describe("runSelfCheck / formatReport", () => {
  it("runSelfCheck 返回三个分组且不抛出", async () => {
    const result = await runSelfCheck({
      homes: homes(),
      deps: {
        findViewerPids: () => [],
        findPidsByPort: () => [],
        readPidFile: () => null,
        isPidAlive: () => true,
        serverInfoPath: (home) => path.join(home, ".co-sight-viewer.json"),
        healthProbe: async () => false,
      },
    });
    assert.equal(result.groups.length, 3);
    assert.equal(result.fix, null);
  });

  it("formatReport 输出包含结果行与分组标题", () => {
    const report = formatReport({
      groups: [
        {
          group: "Hook 配置检查",
          findings: [
            { level: LEVEL.PASS, message: "ok", details: "" },
            { level: LEVEL.WARN, message: "warn", details: "det" },
          ],
        },
      ],
      fix: { fixed: ["x"], errors: [] },
      opts: { verbose: true },
    });
    assert.ok(report.includes("Hook 配置检查"));
    assert.ok(report.includes("结果:"));
    assert.ok(report.includes("1 通过 | 0 提示 | 1 警告 | 0 失败"));
  });
});
