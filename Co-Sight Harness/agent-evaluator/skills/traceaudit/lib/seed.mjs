import fs from "node:fs";
import path from "node:path";
import { isDirectory, isFile } from "./cli.mjs";

const LIST_KEYS = ["records", "entries", "seeds", "items", "cases", "data"];
const EXPLICIT_PARENT_KEYS = ["parent_jsonl", "parentJsonl", "parent_jsonl_path", "trace_jsonl", "traceJsonl"];
const EXPLICIT_SUBAGENTS_KEYS = ["subagents_dir", "subagentsDir", "subagents_path"];

export function resolveSeedJsonl(seedDir) {
  if (!seedDir) throw new Error("--seed-dir is required.");
  const resolved = path.resolve(String(seedDir));
  if (!isDirectory(resolved)) throw new Error(`seed-dir not found: ${resolved}`);

  const candidates = [
    path.join(resolved, "eval_datasets", "seed.jsonl"),
    path.join(resolved, "seed.jsonl"),
  ];
  const found = candidates.find((candidate) => isFile(candidate));
  if (!found) {
    throw new Error(`seed.jsonl not found under seed-dir: ${resolved} (tried ${candidates.join(", ")})`);
  }
  return found;
}

export function readSeedRecords(seedJsonlPath) {
  const raw = fs.readFileSync(seedJsonlPath, "utf8").replace(/^﻿/, "");
  const document = tryParseJson(raw);
  const values = document !== undefined ? normalizeDocument(document) : scanTopLevelValues(raw);
  return values.filter((value) => value && typeof value === "object" && !Array.isArray(value));
}

export function extractRunRef(record, index = 0) {
  const run = record?.run;
  const ref = {
    index,
    dataId: firstString(record?.data_id, record?.dataId, record?.id),
    capabilityRef: firstString(record?.capability_ref, record?.capabilityRef),
    dimension: firstString(record?.dimension),
    kind: firstString(record?.kind),
    input: typeof record?.input === "string" ? record.input : null,
    sessionId: null,
    sessionDir: null,
    caseDir: null,
    subagentsDir: null,
    explicitParentJsonl: null,
    error: null,
  };

  if (!run || typeof run !== "object" || Array.isArray(run)) {
    return { ...ref, error: "seed 记录缺少 run 字段" };
  }

  ref.sessionId = firstString(run.session_id, run.sessionId);
  ref.sessionDir = firstString(run.session_dir, run.sessionDir, run.session_path);
  ref.caseDir = firstString(run.case_dir, run.caseDir, run.workspace_dir, run.workspaceDir);
  ref.subagentsDir = firstString(...EXPLICIT_SUBAGENTS_KEYS.map((key) => run[key]));
  ref.explicitParentJsonl = firstString(...EXPLICIT_PARENT_KEYS.map((key) => run[key]));

  if (!ref.sessionId && !ref.sessionDir && !ref.explicitParentJsonl && !ref.caseDir) {
    return { ...ref, error: "seed 记录的 run 字段缺少 session_id / session_dir" };
  }
  return ref;
}

export function resolveParentJsonl({ ref, seedJsonlPath }) {
  const bases = seedBases(seedJsonlPath);

  if (ref.explicitParentJsonl) {
    const explicit = resolveExisting(ref.explicitParentJsonl, bases);
    if (explicit && isFile(explicit)) return explicit;
  }

  const sessionDir = resolveExisting(ref.sessionDir, bases);
  if (sessionDir) {
    if (isFile(sessionDir)) return sessionDir;

    if (ref.sessionId && isFile(path.join(sessionDir, `${ref.sessionId}.jsonl`))) {
      return path.join(sessionDir, `${ref.sessionId}.jsonl`);
    }

    const listed = matchJsonlInDir(sessionDir, ref.sessionId);
    if (listed) return listed;

    if (ref.sessionId) {
      const nested = matchJsonlInDir(path.join(sessionDir, ref.sessionId), ref.sessionId);
      if (nested) return nested;
    }
  }

  const caseDir = resolveExisting(ref.caseDir, bases);
  if (caseDir && isDirectory(caseDir)) {
    const hit = matchJsonlInDir(path.join(caseDir, "sessions"), ref.sessionId)
      ?? matchJsonlInDir(caseDir, ref.sessionId);
    if (hit) return hit;
  }

  return null;
}

export function resolveSubagentsDirPath({ ref, seedJsonlPath }) {
  if (!ref?.subagentsDir) return null;
  const resolved = resolveExisting(ref.subagentsDir, seedBases(seedJsonlPath));
  return resolved && isDirectory(resolved) ? resolved : null;
}

export function seedBases(seedJsonlPath) {
  const seedDir = path.dirname(path.resolve(seedJsonlPath));
  return [...new Set([seedDir, path.dirname(seedDir), process.cwd()])];
}

export function slugify(value, fallback = "case") {
  const text = String(value ?? "")
    .trim()
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^[-._]+|[-._]+$/g, "")
    .slice(0, 60);
  return text || fallback;
}

function normalizeDocument(document) {
  if (Array.isArray(document)) return flattenOneLevel(document);
  if (document && typeof document === "object") {
    for (const key of LIST_KEYS) {
      if (Array.isArray(document[key])) return flattenOneLevel(document[key]);
    }
    return [document];
  }
  return [];
}

function flattenOneLevel(values) {
  const out = [];
  for (const value of values) {
    if (Array.isArray(value)) out.push(...value);
    else out.push(value);
  }
  return out;
}

function tryParseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function scanTopLevelValues(text) {
  const values = [];
  let depth = 0;
  let start = -1;
  let inString = false;
  let escaped = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];

    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
      continue;
    }

    if (char === '"') {
      inString = true;
      continue;
    }

    if (char === "{" || char === "[") {
      if (depth === 0) start = i;
      depth += 1;
      continue;
    }

    if (char === "}" || char === "]") {
      depth -= 1;
      if (depth <= 0 && start !== -1) {
        const chunk = text.slice(start, i + 1);
        const parsed = tryParseJson(chunk);
        if (parsed !== undefined) values.push(parsed);
        start = -1;
        depth = 0;
      }
    }
  }

  return flattenOneLevel(values);
}

function matchJsonlInDir(dir, sessionId) {
  if (!dir || !isDirectory(dir)) return null;

  let names;
  try {
    names = fs.readdirSync(dir);
  } catch {
    return null;
  }

  const jsonls = names.filter((name) => name.endsWith(".jsonl"));
  if (jsonls.length === 0) return null;

  if (sessionId) {
    const exact = jsonls.find((name) => path.basename(name, ".jsonl") === sessionId);
    if (exact) return path.join(dir, exact);
  }

  return jsonls.length === 1 ? path.join(dir, jsonls[0]) : null;
}

function resolveExisting(value, bases) {
  if (!value) return null;
  const text = String(value);
  if (path.isAbsolute(text)) return fs.existsSync(text) ? text : null;
  for (const base of bases) {
    const candidate = path.resolve(base, text);
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function firstString(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim() !== "") return value.trim();
  }
  return null;
}
