// SPDX-License-Identifier: Apache-2.0
/**
 * @file i18nKeys.test.ts
 * @description Guards against two classes of i18n bug that the UI cannot recover
 * from — i18next renders the raw key when either happens, so users see literal
 * text like "common:statusLabel" or "run.effort":
 *
 *   1. Duplicate keys in a locale JSON file. JSON.parse keeps the last one and
 *      silently drops the first, so a nested object can shadow an unrelated
 *      string that other code depends on.
 *   2. A t() call whose key does not exist, or whose namespace is wrong. Note
 *      that "errors", "settings" and "sessions" exist BOTH as locale
 *      namespaces and as nested objects inside common.json, so the correct form
 *      depends on where the key actually lives and on the file's default
 *      namespace (files calling useTranslation("sessions") must write
 *      t("common:errors.x"), not t("errors.x")).
 */

import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_ROOT = path.resolve(HERE, "../../..");
const LOCALES_DIR = path.join(CLIENT_ROOT, "src/i18n/locales");
const SRC_DIR = path.join(CLIENT_ROOT, "src");

const NAMESPACES = ["common", "sessions", "settings", "errors", "updates"] as const;

const LOCALES = ["en", "zh"] as const;

type Locale = (typeof LOCALES)[number];
type Resources = Record<Locale, Record<string, unknown>>;

function loadResources(): Resources {
  const out = {} as Resources;
  for (const lng of LOCALES) {
    out[lng] = {};
    for (const ns of NAMESPACES) {
      const file = path.join(LOCALES_DIR, lng, `${ns}.json`);
      out[lng][ns] = JSON.parse(fs.readFileSync(file, "utf8"));
    }
  }
  return out;
}

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__tests__" || entry.name === "locales") continue;
      files.push(...collectSourceFiles(full));
    } else if (/\.(tsx?|jsx?)$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

/** Walk a dotted key path inside a namespace's resource object. */
function lookup(resource: unknown, key: string): unknown {
  let cur: unknown = resource;
  for (const part of key.split(".")) {
    if (cur === null || typeof cur !== "object") return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

/**
 * A key resolves when it maps to a string, or — when the call passes a `count`
 * for pluralisation — when any of i18next's plural suffixes exists.
 */
function resolves(resource: unknown, key: string, plural: boolean): boolean {
  if (typeof lookup(resource, key) === "string") return true;
  if (typeof lookup(resource, key) === "object" && lookup(resource, key) !== undefined) {
    return true; // resolved to a group; i18next would still fail, but flag below
  }
  if (!plural) return false;
  return ["_other", "_one", "_zero", "_few", "_many"].some(
    (suffix) => typeof lookup(resource, key + suffix) === "string"
  );
}

/** The namespace a bare (unprefixed) key in this file resolves against. */
function defaultNamespaceOf(source: string): string {
  const match = source.match(/useTranslation\(\s*["']([\w-]+)["']/);
  const ns = match?.[1];
  if (!ns) return "common";
  return NAMESPACES.includes(ns as (typeof NAMESPACES)[number]) ? ns : "common";
}

/**
 * Finds keys repeated *within the same JSON object*. JSON.parse keeps the last
 * occurrence and silently discards the earlier one, which is how a nested
 * `"agent": {...}` can quietly replace an unrelated `"agent": "Agent"` string.
 * Duplicates in different objects are fine, so this walks object scopes.
 */
function findDuplicateKeys(text: string): string[] {
  let i = 0;
  const duplicates: string[] = [];
  const pathStack: string[] = [];

  const skipWs = () => {
    while (i < text.length && /\s/.test(text[i] ?? "")) i++;
  };

  const readString = (): string => {
    let out = "";
    i++; // opening quote
    while (i < text.length) {
      const ch = text[i];
      if (ch === "\\") {
        out += text[i + 1];
        i += 2;
        continue;
      }
      if (ch === '"') {
        i++;
        break;
      }
      out += ch;
      i++;
    }
    return out;
  };

  const parseValue = (): void => {
    skipWs();
    const ch = text[i];
    if (ch === "{") {
      i++;
      parseObject();
      return;
    }
    if (ch === "[") {
      i++;
      parseArray();
      return;
    }
    if (ch === '"') {
      readString();
      return;
    }
    while (i < text.length && !/[,}\]]/.test(text[i] ?? "")) i++; // number / true / false / null
  };

  function parseObject(): void {
    const keys = new Set<string>();
    skipWs();
    if (text[i] === "}") {
      i++;
      return;
    }
    while (i < text.length) {
      skipWs();
      if (text[i] !== '"') break;
      const key = readString();
      if (keys.has(key)) duplicates.push([...pathStack, key].join("."));
      keys.add(key);
      skipWs();
      if (text[i] === ":") i++;
      pathStack.push(key);
      parseValue();
      pathStack.pop();
      skipWs();
      if (text[i] === ",") {
        i++;
        continue;
      }
      if (text[i] === "}") i++;
      break;
    }
  }

  function parseArray(): void {
    skipWs();
    if (text[i] === "]") {
      i++;
      return;
    }
    while (i < text.length) {
      parseValue();
      skipWs();
      if (text[i] === ",") {
        i++;
        continue;
      }
      if (text[i] === "]") i++;
      break;
    }
  }

  parseValue();
  return duplicates;
}

describe("i18n key integrity", () => {
  const resources = loadResources();

  it("has no duplicate keys in any locale file", () => {
    const duplicates: string[] = [];

    for (const lng of LOCALES) {
      for (const ns of NAMESPACES) {
        const raw = fs.readFileSync(path.join(LOCALES_DIR, lng, `${ns}.json`), "utf8");
        for (const keyPath of findDuplicateKeys(raw)) {
          duplicates.push(`${lng}/${ns}.json: duplicate key at "${keyPath}"`);
        }
      }
    }

    expect(duplicates).toEqual([]);
  });

  it("resolves every t() call in src against the en and zh resources", () => {
    const failures: string[] = [];
    const keyPattern = /(?<![\w$.])t\s*\(\s*(["'])((?:(?!\1).)*)\1(\s*,\s*\{([^}]*)\})?/g;

    for (const file of collectSourceFiles(SRC_DIR)) {
      const source = fs.readFileSync(file, "utf8");
      const fileNs = defaultNamespaceOf(source);
      const rel = path.relative(CLIENT_ROOT, file).replace(/\\/g, "/");

      for (const match of source.matchAll(keyPattern)) {
        const raw = match[2];
        // Skip dynamic keys and template literals — they cannot be checked statically.
        if (!raw || raw.includes("${") || /\s/.test(raw)) continue;

        const hasCount = Boolean(match[4] && /\bcount\b/.test(match[4]));
        const sep = raw.indexOf(":");
        const ns = sep === -1 ? fileNs : raw.slice(0, sep);
        const key = sep === -1 ? raw : raw.slice(sep + 1);
        if (!key) continue;

        const line = source.slice(0, match.index).split("\n").length;

        if (!NAMESPACES.includes(ns as (typeof NAMESPACES)[number])) {
          failures.push(`${rel}:${line} — unknown namespace "${ns}" in t("${raw}")`);
          continue;
        }

        for (const lng of LOCALES) {
          if (!resolves(resources[lng][ns], key, hasCount)) {
            failures.push(`${rel}:${line} — "${ns}:${key}" missing in ${lng}`);
          }
        }
      }
    }

    expect(failures).toEqual([]);
  });

  it("keeps en and zh locale files structurally in sync", () => {
    const pathsOf = (value: unknown, prefix: string, out: string[] = []): string[] => {
      if (value && typeof value === "object") {
        for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
          pathsOf(v, prefix ? `${prefix}.${k}` : k, out);
        }
      } else {
        out.push(prefix);
      }
      return out;
    };

    const mismatches: string[] = [];
    for (const ns of NAMESPACES) {
      const en = new Set(pathsOf(resources.en[ns], ""));
      const zh = new Set(pathsOf(resources.zh[ns], ""));
      for (const key of en)
        if (!zh.has(key)) mismatches.push(`${ns}: "${key}" present in en but not zh`);
      for (const key of zh)
        if (!en.has(key)) mismatches.push(`${ns}: "${key}" present in zh but not en`);
    }

    expect(mismatches).toEqual([]);
  });
});
