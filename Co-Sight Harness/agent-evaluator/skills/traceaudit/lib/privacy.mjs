/**
 * 改进 5：隐私脱敏模块
 *
 * 设计原则：
 * - 脱敏在**输出边界**执行，不影响内部计算（L0/L1 的 eventIndex 和文件路径校验仍使用原始路径）
 * - `_intermediate/` 目录的文件不脱敏（用于调试），只脱敏 `trajectory-report.json`
 * - 报告输出时脱敏（避免写出的 trace 文本含完整绝对路径）
 * - 保留 `sessionId` / `caseId` 字段不被误脱敏
 */
import os from "node:os";

// 预计算 home 路径的正则（避免每次调用 new RegExp）
const HOME_DIR_ESCAPED = os.homedir().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// 敏感数据模式 → 替换内容
const SENSITIVE_TRANSFORMS = [
  // 1. 用户 home 路径脱敏（保留 ~/ 前缀便于人眼识别）
  { pattern: new RegExp(HOME_DIR_ESCAPED, "g"), replacement: "~" },
  // 2. UUID 脱敏（sessionId 等保护字段见下方的 PROTECTED_KEYS 机制）
  {
    pattern: /\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b/gi,
    replacement: "<UUID>",
  },
  // 3. 非项目 workspace 的绝对路径脱敏（可按需扩展更多前缀）
  {
    pattern: /\/media\/[^\s"'`<>|$(){}\[\]*?!,;:]+/g,
    replacement: "<external-path>",
  },
  // 4. 常见密钥模式
  {
    pattern: /\b(secret|password|passwd|token|api[_-]?key)\s*[:=]\s*\S+/gi,
    replacement: "$1=<REDACTED>",
  },
];

// 保护字段：脱敏后仍需保留的标识符
const PROTECTED_KEYS = ["sessionId", "caseId"];

/**
 * 对文本进行脱敏，保留保护字段不被误脱敏。
 *
 * @param {string} text - 待脱敏的文本
 * @param {object} context - 包含保护字段值的上下文，如 { sessionId, caseId }
 * @returns {string} 脱敏后的文本
 */
export function sanitizeForOutput(text, context = {}) {
  let result = String(text ?? "");

  // 第一步：提取保护字段的值，用占位符替换避免被脱敏
  const placeholders = new Map();
  for (const key of PROTECTED_KEYS) {
    const value = context[key];
    if (typeof value === "string" && value.length >= 4) {
      const placeholder = `__PROTECTED_${key.toUpperCase()}__`;
      placeholders.set(placeholder, value);
      result = result.split(value).join(placeholder);
    }
  }

  // 第二步：执行脱敏
  for (const transform of SENSITIVE_TRANSFORMS) {
    result = result.replace(transform.pattern, transform.replacement);
  }

  // 第三步：还原保护字段
  for (const [placeholder, value] of placeholders) {
    result = result.split(placeholder).join(value);
  }

  return result;
}

/**
 * 递归脱敏对象 / 数组 / 字符串，但排除 `actual` 和 `evidence` 字段
 * （评估证据需保留原始路径用于调试）。
 *
 * @param {*} obj - 待脱敏的对象 / 数组 / 字符串
 * @param {object} context - 保护字段上下文
 * @returns {*} 脱敏后的对象 / 数组 / 字符串
 */
const PROTECTED_FIELDS = new Set(["actual", "evidence"]);

export function sanitizeReport(obj, context = {}) {
  if (typeof obj === "string") {
    return sanitizeForOutput(obj, context);
  }
  if (Array.isArray(obj)) {
    return obj.map((item) => sanitizeReport(item, context));
  }
  if (obj && typeof obj === "object") {
    const result = {};
    for (const [key, value] of Object.entries(obj)) {
      // 保留 checks[].actual 和 checks[].evidence 的原始值
      if (PROTECTED_FIELDS.has(key)) {
        result[key] = value;
      } else {
        result[key] = sanitizeReport(value, context);
      }
    }
    return result;
  }
  return obj;
}

/**
 * 从 trace 中提取保护字段上下文。
 */
export function extractProtectionContext(trace) {
  const meta = trace?.meta ?? {};
  return {
    sessionId: meta.sessionId,
    caseId: meta.caseId,
  };
}
