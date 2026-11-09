// SPDX-License-Identifier: Apache-2.0
/**
 * @file highlight.ts
 * @description Lightweight, dependency-free syntax highlighter used by the conversation
 * viewer. Tokenizes a string of source code into a flat list of {type, text} tokens for
 * a handful of languages commonly seen in Claude Code transcripts (js/ts, python, json,
 * bash, html, css, sql, yaml, diff). Output is consumed by CodeBlock.tsx which renders
 * each token as a span with a colour class.
 *
 * The goal is "good enough to scan", not full lexical correctness — we accept the
 * occasional mis-tokenization in favour of small bundle size and zero deps.
 *
 */

export type TokenType =
  | "plain"
  | "comment"
  | "string"
  | "number"
  | "keyword"
  | "builtin"
  | "function"
  | "operator"
  | "punctuation"
  | "property"
  | "tag"
  | "attr"
  | "variable"
  | "boolean"
  | "diff-add"
  | "diff-del"
  | "diff-meta";

export interface Token {
  type: TokenType;
  text: string;
}

interface Rule {
  type: TokenType;
  pattern: RegExp;
}

const JS_KEYWORDS = new Set([
  "const",
  "let",
  "var",
  "function",
  "return",
  "if",
  "else",
  "for",
  "while",
  "do",
  "switch",
  "case",
  "break",
  "continue",
  "default",
  "class",
  "extends",
  "super",
  "this",
  "new",
  "delete",
  "typeof",
  "instanceof",
  "in",
  "of",
  "void",
  "yield",
  "async",
  "await",
  "import",
  "export",
  "from",
  "as",
  "try",
  "catch",
  "finally",
  "throw",
  "static",
  "public",
  "private",
  "protected",
  "readonly",
  "interface",
  "type",
  "enum",
  "implements",
  "namespace",
  "declare",
  "abstract",
  "override",
]);

const JS_BUILTINS = new Set([
  "console",
  "window",
  "document",
  "globalThis",
  "process",
  "Math",
  "JSON",
  "Object",
  "Array",
  "String",
  "Number",
  "Boolean",
  "Date",
  "RegExp",
  "Map",
  "Set",
  "Promise",
  "Symbol",
  "Error",
  "Buffer",
  "require",
  "module",
  "exports",
  "__dirname",
  "__filename",
]);

const JS_LITERALS = new Set(["true", "false", "null", "undefined", "NaN", "Infinity"]);

const PY_KEYWORDS = new Set([
  "def",
  "class",
  "if",
  "elif",
  "else",
  "for",
  "while",
  "break",
  "continue",
  "return",
  "yield",
  "import",
  "from",
  "as",
  "pass",
  "raise",
  "try",
  "except",
  "finally",
  "with",
  "lambda",
  "global",
  "nonlocal",
  "in",
  "is",
  "not",
  "and",
  "or",
  "async",
  "await",
  "self",
  "cls",
]);

const PY_BUILTINS = new Set([
  "print",
  "len",
  "range",
  "str",
  "int",
  "float",
  "list",
  "dict",
  "set",
  "tuple",
  "bool",
  "isinstance",
  "type",
  "open",
  "input",
  "enumerate",
  "zip",
  "map",
  "filter",
  "sorted",
  "reversed",
  "abs",
  "min",
  "max",
  "sum",
  "any",
  "all",
  "Exception",
]);

const PY_LITERALS = new Set(["True", "False", "None"]);

const SH_KEYWORDS = new Set([
  "if",
  "then",
  "else",
  "elif",
  "fi",
  "for",
  "in",
  "do",
  "done",
  "while",
  "until",
  "case",
  "esac",
  "function",
  "return",
  "exit",
  "export",
  "local",
  "readonly",
  "declare",
  "set",
  "unset",
  "source",
]);

const SH_BUILTINS = new Set([
  "echo",
  "cd",
  "ls",
  "cat",
  "grep",
  "sed",
  "awk",
  "find",
  "rm",
  "mv",
  "cp",
  "mkdir",
  "touch",
  "chmod",
  "chown",
  "kill",
  "ps",
  "git",
  "npm",
  "node",
  "python",
  "python3",
  "pip",
  "curl",
  "wget",
  "ssh",
  "scp",
  "tar",
  "zip",
  "unzip",
  "head",
  "tail",
  "wc",
  "sort",
  "uniq",
  "xargs",
  "tee",
]);

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Apply an ordered list of rules to source. Earlier rules win. */
function tokenizeWith(source: string, rules: Rule[]): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < source.length) {
    let matched = false;
    for (const rule of rules) {
      rule.pattern.lastIndex = i;
      const m = rule.pattern.exec(source);
      if (m && m.index === i) {
        tokens.push({ type: rule.type, text: m[0] });
        i += m[0].length;
        matched = true;
        break;
      }
    }
    if (!matched) {
      // Append a single plain char; merge with previous plain token to keep the array small.
      const ch = source[i]!;
      const last = tokens[tokens.length - 1];
      if (last && last.type === "plain") last.text += ch;
      else tokens.push({ type: "plain", text: ch });
      i += 1;
    }
  }
  return tokens;
}

function tokenizeJS(source: string): Token[] {
  const rules: Rule[] = [
    { type: "comment", pattern: /\/\/[^\n]*|\/\*[\s\S]*?\*\//y },
    { type: "string", pattern: /"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`/y },
    {
      type: "number",
      pattern: /\b(?:0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b/y,
    },
    { type: "function", pattern: /\b[a-zA-Z_$][\w$]*(?=\s*\()/y },
    { type: "keyword", pattern: /\b[a-zA-Z_$][\w$]*\b/y },
    { type: "operator", pattern: /=>|===|!==|==|!=|<=|>=|&&|\|\||\?\?|\.\.\.|[+\-*/%=<>!&|^~?:]/y },
    { type: "punctuation", pattern: /[{}[\]();,.]/y },
  ];
  // post-process the keyword rule: split into keyword/builtin/boolean/plain
  return refineIdentifiers(tokenizeWith(source, rules), JS_KEYWORDS, JS_BUILTINS, JS_LITERALS);
}

function tokenizePython(source: string): Token[] {
  const rules: Rule[] = [
    { type: "comment", pattern: /#[^\n]*/y },
    {
      type: "string",
      pattern: /"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/y,
    },
    { type: "number", pattern: /\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/y },
    { type: "function", pattern: /\b[a-zA-Z_][\w]*(?=\s*\()/y },
    { type: "keyword", pattern: /\b[a-zA-Z_][\w]*\b/y },
    { type: "operator", pattern: /\*\*|\/\/|<<|>>|<=|>=|==|!=|->|[+\-*/%=<>!&|^~]/y },
    { type: "punctuation", pattern: /[{}[\]():,.]/y },
  ];
  return refineIdentifiers(tokenizeWith(source, rules), PY_KEYWORDS, PY_BUILTINS, PY_LITERALS);
}

function tokenizeJSON(source: string): Token[] {
  const rules: Rule[] = [
    { type: "string", pattern: /"(?:\\.|[^"\\])*"(?=\s*:)/y }, // key
    { type: "string", pattern: /"(?:\\.|[^"\\])*"/y }, // value string
    { type: "number", pattern: /-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b/y },
    { type: "boolean", pattern: /\b(?:true|false|null)\b/y },
    { type: "punctuation", pattern: /[{}[\],:]/y },
  ];
  // Mark "key" strings (those followed by `:`) as `property` instead of `string`
  const tokens = tokenizeWith(source, rules);
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i]!.type === "string") {
      // Look ahead through whitespace plain tokens
      for (let j = i + 1; j < tokens.length; j++) {
        const t = tokens[j]!;
        if (t.type === "plain" && /^\s*$/.test(t.text)) continue;
        if (t.type === "punctuation" && t.text === ":") {
          tokens[i]!.type = "property";
        }
        break;
      }
    }
  }
  return tokens;
}

function tokenizeShell(source: string): Token[] {
  const rules: Rule[] = [
    { type: "comment", pattern: /#[^\n]*/y },
    { type: "string", pattern: /"(?:\\.|[^"\\])*"|'[^']*'/y },
    { type: "variable", pattern: /\$\{[^}]+\}|\$\w+|\$[#?@*$]/y },
    { type: "number", pattern: /\b\d+\b/y },
    { type: "function", pattern: /\b[a-zA-Z_][\w-]*(?=\s)/y },
    { type: "keyword", pattern: /\b[a-zA-Z_][\w-]*\b/y },
    { type: "operator", pattern: /&&|\|\||>>|<<|[|&;<>=!]/y },
    { type: "punctuation", pattern: /[(){}[\];]/y },
  ];
  const tokens = tokenizeWith(source, rules);
  // refine: distinguish keywords vs builtins vs commands
  for (const t of tokens) {
    if (t.type === "keyword" || t.type === "function") {
      if (SH_KEYWORDS.has(t.text)) t.type = "keyword";
      else if (SH_BUILTINS.has(t.text)) t.type = "builtin";
      else if (t.type === "keyword") t.type = "plain";
    }
  }
  return tokens;
}

function tokenizeHTML(source: string): Token[] {
  const tokens: Token[] = [];
  const re =
    /(<!--[\s\S]*?-->)|(<\/?)([a-zA-Z][\w-]*)((?:\s+[a-zA-Z_:][\w:.-]*(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?>)|([^<]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) != null) {
    if (m[1]) tokens.push({ type: "comment", text: m[1] });
    else if (m[2]) {
      tokens.push({ type: "punctuation", text: m[2] });
      tokens.push({ type: "tag", text: m[3]! });
      if (m[4]) tokens.push(...tokenizeHTMLAttrs(m[4]));
      tokens.push({ type: "punctuation", text: m[5]! });
    } else if (m[6]) tokens.push({ type: "plain", text: m[6] });
  }
  return tokens;
}

function tokenizeHTMLAttrs(src: string): Token[] {
  const tokens: Token[] = [];
  const re = /(\s+)([a-zA-Z_:][\w:.-]*)(\s*=\s*)?("[^"]*"|'[^']*'|[^\s>]+)?/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src)) != null) {
    tokens.push({ type: "plain", text: m[1]! });
    tokens.push({ type: "attr", text: m[2]! });
    if (m[3]) tokens.push({ type: "operator", text: m[3] });
    if (m[4]) tokens.push({ type: "string", text: m[4] });
  }
  return tokens;
}

function tokenizeCSS(source: string): Token[] {
  const rules: Rule[] = [
    { type: "comment", pattern: /\/\*[\s\S]*?\*\//y },
    { type: "string", pattern: /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/y },
    { type: "number", pattern: /-?\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|ms|deg)?\b/y },
    { type: "property", pattern: /[a-zA-Z-]+(?=\s*:)/y },
    { type: "tag", pattern: /[.#]?[a-zA-Z_][\w-]*/y },
    { type: "punctuation", pattern: /[{}();:,]/y },
  ];
  return tokenizeWith(source, rules);
}

function tokenizeSQL(source: string): Token[] {
  const KW = new Set([
    "select",
    "from",
    "where",
    "and",
    "or",
    "not",
    "in",
    "is",
    "null",
    "as",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "on",
    "group",
    "by",
    "order",
    "having",
    "limit",
    "offset",
    "insert",
    "into",
    "values",
    "update",
    "set",
    "delete",
    "create",
    "table",
    "drop",
    "alter",
    "add",
    "primary",
    "key",
    "foreign",
    "references",
    "index",
    "unique",
    "with",
    "case",
    "when",
    "then",
    "else",
    "end",
    "distinct",
    "union",
    "all",
    "exists",
    "between",
    "like",
  ]);
  const rules: Rule[] = [
    { type: "comment", pattern: /--[^\n]*|\/\*[\s\S]*?\*\//y },
    { type: "string", pattern: /'(?:''|[^'])*'/y },
    { type: "number", pattern: /\b\d+(?:\.\d+)?\b/y },
    { type: "keyword", pattern: /\b[a-zA-Z_][\w]*\b/y },
    { type: "operator", pattern: /<>|<=|>=|!=|[=<>+\-*/]/y },
    { type: "punctuation", pattern: /[(),;.]/y },
  ];
  const tokens = tokenizeWith(source, rules);
  for (const t of tokens) {
    if (t.type === "keyword") {
      if (!KW.has(t.text.toLowerCase())) t.type = "plain";
    }
  }
  return tokens;
}

function tokenizeYAML(source: string): Token[] {
  const tokens: Token[] = [];
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    if (i > 0) tokens.push({ type: "plain", text: "\n" });
    if (line.trim().startsWith("#")) {
      tokens.push({ type: "comment", text: line });
      continue;
    }
    const m = line.match(/^(\s*-?\s*)([a-zA-Z_][\w-]*)(\s*:)(.*)$/);
    if (m) {
      tokens.push({ type: "plain", text: m[1]! });
      tokens.push({ type: "property", text: m[2]! });
      tokens.push({ type: "punctuation", text: m[3]! });
      const rest = m[4]!;
      if (/^\s*("[^"]*"|'[^']*')\s*$/.test(rest)) {
        tokens.push({ type: "string", text: rest });
      } else if (/^\s*-?\d+(\.\d+)?\s*$/.test(rest)) {
        tokens.push({ type: "number", text: rest });
      } else if (/^\s*(true|false|null|~)\s*$/.test(rest)) {
        tokens.push({ type: "boolean", text: rest });
      } else {
        tokens.push({ type: "plain", text: rest });
      }
    } else {
      tokens.push({ type: "plain", text: line });
    }
  }
  return tokens;
}

function tokenizeDiff(source: string): Token[] {
  const tokens: Token[] = [];
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    if (i > 0) tokens.push({ type: "plain", text: "\n" });
    if (
      line.startsWith("+++") ||
      line.startsWith("---") ||
      line.startsWith("@@") ||
      line.startsWith("diff ")
    ) {
      tokens.push({ type: "diff-meta", text: line });
    } else if (line.startsWith("+")) {
      tokens.push({ type: "diff-add", text: line });
    } else if (line.startsWith("-")) {
      tokens.push({ type: "diff-del", text: line });
    } else {
      tokens.push({ type: "plain", text: line });
    }
  }
  return tokens;
}

function refineIdentifiers(
  tokens: Token[],
  keywords: Set<string>,
  builtins: Set<string>,
  literals: Set<string>
): Token[] {
  for (const t of tokens) {
    if (t.type === "keyword") {
      if (keywords.has(t.text)) t.type = "keyword";
      else if (builtins.has(t.text)) t.type = "builtin";
      else if (literals.has(t.text)) t.type = "boolean";
      else t.type = "plain";
    }
  }
  return tokens;
}

/** Normalize a user-supplied lang tag to a canonical key. */
export function canonicalLang(lang: string): string {
  const l = lang.toLowerCase().trim();
  if (l === "js" || l === "jsx" || l === "javascript" || l === "mjs" || l === "cjs") return "js";
  if (l === "ts" || l === "tsx" || l === "typescript") return "ts";
  if (l === "py" || l === "python") return "python";
  if (l === "json" || l === "jsonc") return "json";
  if (l === "sh" || l === "bash" || l === "zsh" || l === "shell" || l === "console") return "bash";
  if (l === "html" || l === "xml" || l === "svg") return "html";
  if (l === "css" || l === "scss" || l === "less") return "css";
  if (l === "sql") return "sql";
  if (l === "yaml" || l === "yml") return "yaml";
  if (l === "diff" || l === "patch") return "diff";
  return l || "plain";
}

/** Tokenize source code for the given language. Returns plain tokens for unknown languages. */
export function highlight(source: string, lang: string): Token[] {
  const canon = canonicalLang(lang);
  switch (canon) {
    case "js":
    case "ts":
      return tokenizeJS(source);
    case "python":
      return tokenizePython(source);
    case "json":
      return tokenizeJSON(source);
    case "bash":
      return tokenizeShell(source);
    case "html":
      return tokenizeHTML(source);
    case "css":
      return tokenizeCSS(source);
    case "sql":
      return tokenizeSQL(source);
    case "yaml":
      return tokenizeYAML(source);
    case "diff":
      return tokenizeDiff(source);
    default:
      return [{ type: "plain", text: source }];
  }
}

/** Map a token type to a Tailwind colour class. */
export function tokenClass(type: TokenType): string {
  switch (type) {
    case "comment":
      return "text-muted italic";
    case "string":
      return "text-emerald-700";
    case "number":
      return "text-orange-600";
    case "keyword":
      return "text-violet-600";
    case "builtin":
      return "text-sky-600";
    case "function":
      return "text-blue-600";
    case "operator":
      return "text-pink-600";
    case "punctuation":
      return "text-tertiary";
    case "property":
      return "text-cyan-700";
    case "tag":
      return "text-rose-600";
    case "attr":
      return "text-amber-600";
    case "variable":
      return "text-amber-700";
    case "boolean":
      return "text-orange-600";
    case "diff-add":
      return "text-emerald-700 bg-emerald-50";
    case "diff-del":
      return "text-red-700 bg-red-50";
    case "diff-meta":
      return "text-violet-600";
    case "plain":
    default:
      return "text-secondary";
  }
}

// Re-export for convenience
export { escapeRegex as _escapeRegex };
