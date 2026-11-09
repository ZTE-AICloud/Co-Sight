/**
 * 词表一致性检查（不引测试框架）。
 *
 * 守三件事，都是编译期管不到的：
 *   1. 中英叶子键集合一致（`en-US` 的类型标注能保证结构，但有人把某条翻译删成
 *      空串、或两侧同时漏加时，类型系统看不出来）；
 *   2. 每条词条非空；
 *   3. 同一条词条在中英两侧的 `{placeholder}` 集合一致。
 *
 * 用法：`npm run check:i18n`。消息文件没有运行时依赖（只 import type），
 * 所以用 TypeScript 转译后直接 dynamic import，不需要额外构建。
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const here = path.dirname(fileURLToPath(import.meta.url));
const messagesDir = path.resolve(here, '../src/i18n/messages');

async function load(file) {
  const source = fs.readFileSync(path.join(messagesDir, file), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    fileName: file,
  });
  const encoded = Buffer.from(outputText).toString('base64');
  return import(`data:text/javascript;base64,${encoded}`);
}

function leaves(node, prefix = '') {
  const out = new Map();
  for (const [key, value] of Object.entries(node)) {
    const pathKey = prefix === '' ? key : `${prefix}.${key}`;
    if (typeof value === 'string') out.set(pathKey, value);
    else for (const [key, text] of leaves(value, pathKey)) out.set(key, text);
  }
  return out;
}

const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

const zh = leaves((await load('zh-CN.ts')).zhCN);
const en = leaves((await load('en-US.ts')).enUS);

const problems = [];

const missingInEn = [...zh.keys()].filter((key) => !en.has(key));
const extraInEn = [...en.keys()].filter((key) => !zh.has(key));
if (missingInEn.length > 0) problems.push(`en-US 缺少词条：\n  ${missingInEn.join('\n  ')}`);
if (extraInEn.length > 0) problems.push(`en-US 多出词条：\n  ${extraInEn.join('\n  ')}`);

for (const [label, dict] of [
  ['zh-CN', zh],
  ['en-US', en],
]) {
  const blank = [...dict.entries()].filter(([, text]) => text.trim() === '').map(([key]) => key);
  if (blank.length > 0) problems.push(`${label} 有空词条：\n  ${blank.join('\n  ')}`);
}

for (const [key, zhText] of zh) {
  const enText = en.get(key);
  if (enText === undefined) continue;
  const a = placeholders(zhText).join(',');
  const b = placeholders(enText).join(',');
  if (a !== b) {
    problems.push(`占位符不一致 ${key}：zh=[${a}] en=[${b}]`);
  }
}

if (problems.length > 0) {
  console.error(`i18n 检查失败（${String(problems.length)} 项）：\n`);
  for (const problem of problems) console.error(`${problem}\n`);
  process.exit(1);
}

console.log(`i18n 检查通过：${String(zh.size)} 条词条，中英一致。`);
