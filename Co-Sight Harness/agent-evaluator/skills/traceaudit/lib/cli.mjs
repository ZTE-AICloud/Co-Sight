import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export function parseArgs(argv = process.argv.slice(2)) {
  const args = {};
  const positionals = [];

  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) {
      positionals.push(token);
      continue;
    }

    const eqIndex = token.indexOf("=");
    if (eqIndex !== -1) {
      args[token.slice(2, eqIndex)] = token.slice(eqIndex + 1);
      continue;
    }

    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
    } else {
      args[key] = next;
      i += 1;
    }
  }

  args._ = positionals;
  return args;
}

export function parseBoolean(value, defaultValue = false) {
  if (value === undefined || value === null || value === "") return defaultValue;
  if (value === true || value === false) return value;
  const text = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "y", "on"].includes(text)) return true;
  if (["0", "false", "no", "n", "off"].includes(text)) return false;
  return defaultValue;
}

export function readJson(filePath, fallback = undefined) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    if (fallback !== undefined && error.code === "ENOENT") return fallback;
    throw new Error(`Failed to read JSON ${filePath}: ${error.message}`);
  }
}

export function writeJson(filePath, data) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

export function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

export function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

export function isDirectory(dirPath) {
  try {
    return fs.statSync(dirPath).isDirectory();
  } catch {
    return false;
  }
}

export function unique(values) {
  return [...new Set(values.filter((value) => value !== undefined && value !== null && value !== ""))];
}

export function normalizeToolName(name) {
  if (!name) return "Unknown";
  if (name === "Agent") return "Task";
  if (name === "TaskCreate" || name === "TaskUpdate") return name;
  return name;
}

export function formatDurationMs(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "unknown";
  const seconds = Math.round(ms / 1000);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remSeconds = seconds % 60;
  if (hours > 0) return `${hours}h${minutes}m${remSeconds}s`;
  if (minutes > 0) return `${minutes}m${remSeconds}s`;
  return `${remSeconds}s`;
}

export function durationMsBetween(startIso, endIso) {
  const start = Date.parse(startIso ?? "");
  const end = Date.parse(endIso ?? "");
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return Math.max(0, end - start);
}

export function isMainModule(metaUrl) {
  if (!process.argv[1]) return false;
  return path.resolve(process.argv[1]) === fileURLToPath(metaUrl);
}

const SKILL_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export function isInsideDir(dirPath, parentPath) {
  const relative = path.relative(path.resolve(parentPath), path.resolve(dirPath));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

export function resolveWorkspaceDir() {
  const cwd = process.cwd();
  if (!isInsideDir(cwd, SKILL_ROOT)) return cwd;

  const initCwd = process.env.INIT_CWD;
  if (initCwd && isDirectory(initCwd) && !isInsideDir(initCwd, SKILL_ROOT)) return path.resolve(initCwd);

  throw new Error(
    `不能把评测产物写进 skill 自身目录: ${cwd}。`
    + "请在调用方自己的工作目录下用绝对路径执行本脚本（不要 cd 进入 skill 目录），或用 --outputs 指定输出目录。",
  );
}
