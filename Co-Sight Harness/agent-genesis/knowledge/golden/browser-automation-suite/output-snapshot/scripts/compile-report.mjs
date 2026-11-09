#!/usr/bin/env node
// compile-report.mjs — 扇出研究汇聚（reduce 步）。
// 读取 OUTPUT_DIR 下全部单目标 .md（格式契约 references/research-file-format.md）,
// 产出 index.html（打分总表 + 逐目标链接）与 results.csv。零依赖。
// 用法: node compile-report.mjs <research-dir>

import { readdirSync, readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join, basename } from 'path';

const dir = process.argv[2];
if (!dir || !existsSync(dir)) { console.error('usage: node compile-report.mjs <research-dir>'); process.exit(2); }

// 解析单目标文件的 YAML 头（字段固定, 按行解析禁引 yaml 依赖）
function parseTarget(file) {
  const txt = readFileSync(join(dir, file), 'utf8');
  const m = txt.match(/^---\n([\s\S]*?)\n---/);
  const head = m ? m[1] : '';
  const get = (k) => (head.match(new RegExp('^' + k + ':\\s*(.*)$', 'm')) || [])[1]?.trim() ?? 'Unknown';
  const getScore = (k) => parseInt((head.match(new RegExp('^' + k + ':\\s*(\\d+)')) || [])[1] || '0', 10);
  const failed = /## 失败记录\n(?!无)/.test(txt) && !/## 失败记录\n无/.test(txt);
  return {
    slug: get('slug') || basename(file, '.md'),
    name: get('name'), product: get('product_description'), industry: get('industry'),
    score: getScore('fit_score'), reasoning: get('reasoning_field_unused', ''),
    file, failed
  };
}

const targets = readdirSync(dir).filter(f => f.endsWith('.md')).map(parseTarget);
if (!targets.length) { console.error('无单目标文件: ' + dir); process.exit(2); }

// CSV（总分降序; fit_reasoning 内逗号转引号由消费者处理, 此处保守替换换行）
const esc = (s) => '"' + String(s).replace(/"/g, '""').replace(/\n/g, ' ') + '"';
const rows = [...targets].sort((a, b) => b.score - a.score);
writeFileSync(join(dir, 'results.csv'),
  'slug,name,product_description,industry,fit_score,failed\n' +
  rows.map(t => [t.slug, t.name, t.product, t.industry, t.score, t.failed].map(esc).join(',')).join('\n') + '\n');

// index.html 总表
const tr = rows.map(t =>
  `<tr${t.failed ? ' style="background:#fee"' : ''}><td>${t.score}</td><td>${t.name}</td>` +
  `<td>${t.product}</td><td>${t.industry}</td><td><a href="${t.file}">${t.slug}</a></td></tr>`).join('\n');
writeFileSync(join(dir, 'index.html'), `<!doctype html><meta charset="utf-8">
<title>研究总表</title><h1>扇出研究总表（${targets.length} 目标）</h1>
<table border="1"><tr><th>fit_score</th><th>name</th><th>product</th><th>industry</th><th>证据档</th></tr>
${tr}</table>`);

console.log(JSON.stringify({ targets: targets.length, failed: targets.filter(t => t.failed).length,
  index: 'index.html', csv: 'results.csv' }));
