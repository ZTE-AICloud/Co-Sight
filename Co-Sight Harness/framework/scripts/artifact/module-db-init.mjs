#!/usr/bin/env node
/**
 * 把随包的**空库模板**拷到用户数据目录；目标已存在时做**结构补齐**（不覆盖数据）。
 *
 * ── 为什么不每次启动都建库 ────────────────────────────────────────────
 *
 * 建库需要模块自己的迁移工具（smart-factory 用 Prisma CLI），那是开发依赖，
 * 体积不小、还可能要求联网。模板在打包机上已经建好，用户机器上只做一次
 * 文件拷贝，既快又离线可用。
 *
 * ── 为什么还要比一次结构（D48）────────────────────────────────────────
 *
 * 只认"文件在不在"会留下一个必然踩到的坑：模块升了 schema（smart-factory 加了
 * `agents.builtin`，还把 `agents.workspace_id` 放宽成可空），而用户的旧库还在，
 * 模板永远不会再被复制，服务启动即报
 * `The column 'main.agents.builtin' does not exist in the current database`
 * 然后整次启动失败（退出码 13）。产物里没有 Prisma CLI，跑不了模块自己的
 * `db.mjs sync`，所以这一步只能由这个脚本完成。
 *
 * 规则是"**让结构追平模板，同时尽量留住数据**"：
 *
 * - 模板里有、旧库里没有的**表** → 按模板建；
 * - 缺的**列**都能用 `ALTER TABLE ADD COLUMN` 补（有默认值或可空）→ 直接补；
 * - 补不了、或**已有列的定义变了**（可空性 / 默认值 / 类型）→ 按模板**重建这张表**：
 *   建新表 → 拷公共列 → 换名。新增的必填无默认列在拷贝历史行时以类型空值补齐；
 * - **索引**以模板为准：缺的补建、定义变了的重建、模板里没有的移除（索引不含数据）。
 *
 * 模板外的**列**（数据目录可能来自别的分支）默认保留；只有当它 `NOT NULL` 又没有
 * 默认值时才失败——那会让模块自己的 INSERT 失败，不如当场说清楚。
 *
 * 真的会改动文件时，先 checkpoint WAL，再把旧库备份成 `<文件名>.bak-<时间戳>`。
 * 没有任何差异时什么都不写，重复启动不会产生备份。
 *
 * ── 幂等与权限 ─────────────────────────────────────────────────────────
 *
 * 目标文件不存在 ⇒ 拷模板。存在 ⇒ 先算差异，没有差异就退出。
 * 数据目录按 0700、库文件按 0600 创建：里面可能有会话与工作区信息。
 * 拷贝先写临时文件再 rename，进程在拷到一半被杀不会留下半个 SQLite 文件。
 *
 * 用法：
 *   node module-db-init.mjs --template db-template.sqlite --file smart-factory.db
 *   （数据目录默认取 COSIGHT_HOME；也可用 --dir 显式指定）
 */

import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';

function usage() {
  return [
    '用法：node module-db-init.mjs --template <模板文件> --file <目标文件名> [--dir <数据目录>]',
    '',
    '  --template  随包的模板库（相对当前目录）',
    '  --file      数据目录里的目标文件名（不能带路径分隔符）',
    '  --dir       数据目录；默认取环境变量 COSIGHT_HOME',
    '',
  ].join('\n');
}

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function warn(message) {
  process.stderr.write(`${message}\n`);
}

function parseArgs(argv) {
  const options = { template: '', file: '', directory: '' };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const takeValue = () => {
      const value = argv[index + 1];
      if (value === undefined || value.startsWith('--')) {
        fail(`${arg} 缺少取值`);
      }
      index += 1;
      return value;
    };

    if (arg === '--help' || arg === '-h') {
      process.stdout.write(usage());
      process.exit(0);
    } else if (arg === '--template') {
      options.template = takeValue();
    } else if (arg === '--file') {
      options.file = takeValue();
    } else if (arg === '--dir') {
      options.directory = takeValue();
    } else {
      fail(`未知参数：${arg}\n\n${usage()}`);
    }
  }

  if (options.template === '') {
    fail('缺少 --template');
  }
  if (options.file === '' || options.file === '.' || options.file === '..' || /[\\/]/.test(options.file)) {
    fail('--file 必须是不带路径分隔符的文件名');
  }

  const directory = options.directory === '' ? process.env.COSIGHT_HOME ?? '' : options.directory;
  if (directory === '') {
    fail('没有数据目录：请设置 COSIGHT_HOME 或传 --dir');
  }

  return {
    template: path.resolve(options.template),
    file: options.file,
    directory: path.resolve(directory),
  };
}

function quoteIdentifier(name) {
  return `"${String(name).replace(/"/g, '""')}"`;
}

/** 模板/旧库里的"业务表"：跳过 SQLite 内部表与 Prisma 自己的迁移记录。 */
function isBusinessTable(name) {
  return !name.startsWith('sqlite_') && !name.startsWith('_prisma');
}

function columnInfo(db, table) {
  return db
    .prepare(`PRAGMA table_info(${quoteIdentifier(table)})`)
    .all()
    .map((row) => ({
      name: row.name,
      type: row.type,
      notNull: row.notnull === 1,
      defaultValue: row.dflt_value,
      primaryKey: row.pk > 0,
    }));
}

function readSchema(db) {
  const tables = new Map();
  for (const row of db.prepare("SELECT name, sql FROM sqlite_master WHERE type = 'table'").all()) {
    if (!isBusinessTable(row.name) || typeof row.sql !== 'string') {
      continue;
    }
    tables.set(row.name.toLowerCase(), { name: row.name, sql: row.sql, columns: columnInfo(db, row.name) });
  }

  const indexes = db
    .prepare("SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL")
    .all()
    .filter((row) => isBusinessTable(row.tbl_name));

  return { tables, indexes };
}

/** SQLite 的 ADD COLUMN 只接受常量默认值；`CURRENT_TIMESTAMP` 这类表达式要走重建。 */
function isConstantDefault(value) {
  return /^(?:NULL|TRUE|FALSE|[-+]?\d+(?:\.\d+)?|'(?:[^']|'')*'|X'[0-9A-Fa-f]*')$/i.test(value);
}

function canAddColumn(column) {
  if (column.primaryKey) {
    return false;
  }
  if (column.notNull && column.defaultValue === null) {
    return false;
  }
  return column.defaultValue === null || isConstantDefault(column.defaultValue);
}

/** 模板外的列：`NOT NULL` 又没有默认值会让模块的 INSERT 失败，其余都能留。 */
function canCarryColumn(column) {
  if (column.primaryKey) {
    return false;
  }
  return !column.notNull || (column.defaultValue !== null && isConstantDefault(column.defaultValue));
}

function columnDefinition(column) {
  const parts = [quoteIdentifier(column.name)];
  if (column.type) {
    parts.push(column.type);
  }
  if (column.notNull) {
    parts.push('NOT NULL');
  }
  if (column.defaultValue !== null) {
    parts.push(`DEFAULT ${column.defaultValue}`);
  }
  return parts.join(' ');
}

/** 重建时把模板外的列原样带过去；可空列上不能保留的表达式默认值（如 CURRENT_TIMESTAMP）丢掉。 */
function carryDefinition(column) {
  if (column.notNull) {
    return columnDefinition(column);
  }
  const defaultValue =
    column.defaultValue !== null && isConstantDefault(column.defaultValue) ? column.defaultValue : null;
  return columnDefinition({ ...column, defaultValue });
}

function normalizeDefault(value) {
  return value === null ? '' : String(value).replace(/\s+/g, ' ').trim().toLowerCase();
}

function sameColumn(left, right) {
  return (
    String(left.type).toUpperCase() === String(right.type).toUpperCase() &&
    left.notNull === right.notNull &&
    left.primaryKey === right.primaryKey &&
    normalizeDefault(left.defaultValue) === normalizeDefault(right.defaultValue)
  );
}

function normalizeSql(sql) {
  return String(sql).replace(/\s+/g, ' ').trim().toLowerCase();
}

/** 新增的必填无默认列在拷贝历史行时用什么值顶上（只用于重建，不写进 schema）。 */
function placeholderValue(column) {
  const type = String(column.type).toUpperCase();
  if (/(INT|BOOL|REAL|FLOA|DOUB|NUM|DEC)/.test(type)) {
    return '0';
  }
  if (type.includes('BLOB')) {
    return "X''";
  }
  return "''";
}

/**
 * 算出需要做的改动。**只读**，不改任何东西；有"不该猜"的差异就放进 problems。
 */
function planSync(targetSchema, templateSchema) {
  const steps = [];
  const summary = [];
  const problems = [];
  const rebuiltTables = new Set();
  const templateIndexNames = new Set(templateSchema.indexes.map((index) => index.name.toLowerCase()));

  for (const [key, templateTable] of templateSchema.tables) {
    const existing = targetSchema.tables.get(key);
    if (!existing) {
      steps.push({ kind: 'create', table: templateTable });
      summary.push(`${templateTable.name}：新建表`);
      continue;
    }

    const existingByName = new Map(existing.columns.map((column) => [column.name.toLowerCase(), column]));
    const templateNames = new Set(templateTable.columns.map((column) => column.name.toLowerCase()));

    const extras = existing.columns.filter((column) => !templateNames.has(column.name.toLowerCase()));
    const unresolvable = extras.filter((column) => !canCarryColumn(column));
    if (unresolvable.length > 0) {
      problems.push(
        `${templateTable.name} 表里有模板外的列无法保留：` +
          `${unresolvable.map((column) => `${column.name}（NOT NULL 且无默认值）`).join(', ')}。` +
          '保留它会让模块自己的 INSERT 失败。',
      );
      continue;
    }

    const missing = templateTable.columns.filter((column) => !existingByName.has(column.name.toLowerCase()));
    const changed = templateTable.columns.filter((column) => {
      const found = existingByName.get(column.name.toLowerCase());
      return found !== undefined && !sameColumn(found, column);
    });

    if (missing.length === 0 && changed.length === 0) {
      continue;
    }

    if (missing.every(canAddColumn) && changed.length === 0) {
      steps.push({ kind: 'add-columns', tableName: templateTable.name, columns: missing });
      summary.push(`${templateTable.name}：新增列 ${missing.map((column) => column.name).join(', ')}`);
      continue;
    }

    const reasons = [];
    if (missing.length > 0) {
      reasons.push(`新增列 ${missing.map((column) => column.name).join(', ')}`);
    }
    if (changed.length > 0) {
      reasons.push(`列定义变化 ${changed.map((column) => column.name).join(', ')}`);
    }
    if (extras.length > 0) {
      reasons.push(`保留模板外的列 ${extras.map((column) => column.name).join(', ')}`);
    }
    steps.push({ kind: 'rebuild', table: templateTable, extras });
    rebuiltTables.add(key);
    summary.push(`${templateTable.name}：重建表（${reasons.join('；')}）`);
  }

  const indexSteps = [];
  for (const index of templateSchema.indexes) {
    const existing = targetSchema.indexes.find((item) => item.name.toLowerCase() === index.name.toLowerCase());
    const rebuilt = rebuiltTables.has(index.tbl_name.toLowerCase());

    if (existing && !rebuilt && normalizeSql(existing.sql) === normalizeSql(index.sql)) {
      continue;
    }

    const statements = [];
    if (existing && !rebuilt) {
      // 同名不同定义：SQLite 没有 ALTER INDEX，只能删了重建。
      statements.push(`DROP INDEX ${quoteIdentifier(existing.name)}`);
    }
    statements.push(index.sql);
    const action = rebuilt ? '重建索引' : existing ? '更新索引' : '新建索引';
    indexSteps.push({ statements, summary: `${index.name}：${action}` });
  }

  for (const index of targetSchema.indexes) {
    if (templateIndexNames.has(index.name.toLowerCase())) {
      continue;
    }
    // 整张表都不在模板里时不碰它；表在模板里时，索引以模板为准。
    if (!templateSchema.tables.has(index.tbl_name.toLowerCase())) {
      continue;
    }
    const rebuilt = rebuiltTables.has(index.tbl_name.toLowerCase());
    indexSteps.push({
      statements: rebuilt ? [] : [`DROP INDEX ${quoteIdentifier(index.name)}`],
      summary: `${index.name}：移除（当前模板中没有）`,
    });
  }

  return { steps, indexSteps, summary, problems };
}

function renameCreateTable(sql, newName) {
  const renamed = sql.replace(
    /^(\s*CREATE\s+TABLE\s+)(?:"[^"]+"|\[[^\]]+\]|`[^`]+`|[A-Za-z_][\w$]*)/i,
    (_match, prefix) => `${prefix}${quoteIdentifier(newName)}`,
  );
  if (renamed === sql) {
    throw new Error('无法解析模板里的建表语句');
  }
  return renamed;
}

function tableRowCount(db, table) {
  const row = db.prepare(`SELECT COUNT(*) AS count FROM ${quoteIdentifier(table)}`).get();
  return Number(row.count);
}

/** 建新表 →（带上模板外的列）→ 拷公共列 → 删旧表 → 换成模板里的名字。返回给用户看的提示。 */
function rebuildTable(db, step) {
  const { table: templateTable, extras } = step;
  const temporary = `__cosight_sync_${templateTable.name}`;
  const rows = tableRowCount(db, templateTable.name);

  db.exec(`DROP TABLE IF EXISTS ${quoteIdentifier(temporary)}`);
  db.exec(renameCreateTable(templateTable.sql, temporary));

  for (const column of extras) {
    db.exec(`ALTER TABLE ${quoteIdentifier(temporary)} ADD COLUMN ${carryDefinition(column)}`);
  }

  const existingNames = new Set(columnInfo(db, templateTable.name).map((column) => column.name.toLowerCase()));
  const shared = templateTable.columns.filter((column) => existingNames.has(column.name.toLowerCase()));
  if (shared.length === 0 && rows > 0) {
    throw new Error(`${templateTable.name} 表里没有一列能与模板对上，重建会丢掉全部数据，已放弃。`);
  }

  const placeholders = templateTable.columns.filter(
    (column) => !existingNames.has(column.name.toLowerCase()) && column.notNull && column.defaultValue === null,
  );
  const insertColumns = [...shared, ...extras, ...placeholders].map((column) => quoteIdentifier(column.name));
  const selectExpressions = [
    ...shared.map((column) => quoteIdentifier(column.name)),
    ...extras.map((column) => quoteIdentifier(column.name)),
    ...placeholders.map((column) => placeholderValue(column)),
  ];

  if (insertColumns.length > 0) {
    db.exec(
      `INSERT INTO ${quoteIdentifier(temporary)} (${insertColumns.join(', ')}) ` +
        `SELECT ${selectExpressions.join(', ')} FROM ${quoteIdentifier(templateTable.name)}`,
    );
  }

  db.exec(`DROP TABLE ${quoteIdentifier(templateTable.name)}`);
  db.exec(`ALTER TABLE ${quoteIdentifier(temporary)} RENAME TO ${quoteIdentifier(templateTable.name)}`);

  if (rows > 0 && placeholders.length > 0) {
    return [
      `${templateTable.name}：${rows} 行历史数据里的新增必填列 ` +
        `${placeholders.map((column) => column.name).join(', ')} 以类型空值补齐`,
    ];
  }
  return [];
}

function applyPlan(db, plan) {
  const notes = [];
  db.exec('PRAGMA foreign_keys = OFF');
  db.exec('BEGIN IMMEDIATE');
  try {
    for (const step of plan.steps) {
      if (step.kind === 'create') {
        db.exec(step.table.sql);
      } else if (step.kind === 'add-columns') {
        for (const column of step.columns) {
          db.exec(`ALTER TABLE ${quoteIdentifier(step.tableName)} ADD COLUMN ${columnDefinition(column)}`);
        }
      } else if (step.kind === 'rebuild') {
        notes.push(...rebuildTable(db, step));
      }
    }
    // 索引统一放在表结构就位之后：重建表时旧索引已随 DROP TABLE 消失。
    for (const step of plan.indexSteps) {
      for (const statement of step.statements) {
        db.exec(statement);
      }
    }
    db.exec('COMMIT');
  } catch (error) {
    try {
      db.exec('ROLLBACK');
    } catch {
      // 回滚失败不掩盖原始错误。
    }
    throw error;
  } finally {
    db.exec('PRAGMA foreign_keys = ON');
  }
  return notes;
}

function backupTarget(target, db) {
  // WAL 里的内容还没落进主文件，先 checkpoint 再拷，否则备份缺最近的事务。
  try {
    db.exec('PRAGMA wal_checkpoint(TRUNCATE)');
  } catch {
    // 不是 WAL 模式或忙：忽略，备份仍是主文件的一致快照（服务此时未启动）。
  }
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..*$/, '');
  const backup = `${target}.bak-${stamp}`;
  fs.copyFileSync(target, backup);
  try {
    fs.chmodSync(backup, 0o600);
  } catch {
    // Windows 不支持 POSIX 权限位，忽略。
  }
  return backup;
}

function syncSchema(template, target) {
  let targetDb;
  try {
    targetDb = new DatabaseSync(target);
    const targetSchema = readSchema(targetDb);
    const templateDb = new DatabaseSync(template, { readOnly: true });
    let templateSchema;
    try {
      templateSchema = readSchema(templateDb);
    } finally {
      templateDb.close();
    }

    const plan = planSync(targetSchema, templateSchema);

    if (plan.problems.length > 0) {
      targetDb.close();
      fail(
        [
          '数据库结构与当前版本不兼容，已保持原样未做任何修改：',
          ...plan.problems.map((item) => `  - ${item}`),
          '',
          `目标库：${target}`,
          '处理：确认这份数据该用哪个版本的产物。若要丢弃旧数据重新开始，',
          `先备份再删除该文件（模块历史数据会丢失）：rm "${target}"，然后重新启动。`,
        ].join('\n'),
      );
    }

    if (plan.steps.length === 0 && plan.indexSteps.length === 0) {
      targetDb.close();
      return;
    }

    const backup = backupTarget(target, targetDb);
    const notes = applyPlan(targetDb, plan);
    targetDb.close();

    process.stdout.write(
      [
        '数据库结构已按当前版本补齐（原有数据保留）：',
        ...plan.summary.map((line) => `  ${line}`),
        ...plan.indexSteps.map((step) => `  ${step.summary}`),
        ...notes.map((line) => `  注意：${line}`),
        `  旧库备份：${backup}`,
      ].join('\n') + '\n',
    );
  } catch (error) {
    if (targetDb !== undefined) {
      try {
        targetDb.close();
      } catch {
        // 已经关过或打开失败，忽略。
      }
    }
    const message = error instanceof Error ? error.message : String(error);
    if (/not a database|file is encrypted|malformed/i.test(message)) {
      // 不是这个脚本能理解的 SQLite 文件：保持"绝不覆盖用户数据"的旧语义，
      // 只提示一声，让模块自己的报错去说明问题。
      warn(`跳过数据库结构检查：${target} 不是可读取的 SQLite 数据库（${message}）`);
      return;
    }
    fail(
      [
        `数据库结构升级失败：${message}`,
        `目标库：${target}`,
        '已回滚，未提交任何改动。处理：确认没有其他进程正在使用该文件后重试；',
        '仍失败时备份并删除该文件，重启会按当前模板重建（模块历史数据会丢失）。',
      ].join('\n'),
    );
  }
}

function main() {
  const { template, file, directory } = parseArgs(process.argv.slice(2));

  let templateSize;
  try {
    templateSize = fs.statSync(template).size;
  } catch {
    fail(`模板库不存在：${template}`);
  }
  if (templateSize === 0) {
    fail(`模板库是空文件：${template}`);
  }

  const target = path.join(directory, file);
  if (fs.existsSync(target)) {
    syncSchema(template, target);
    return;
  }

  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  // mkdir 的 mode 会被 umask 削掉，显式 chmod 一次；已有目录不动（可能是用户自己建的）。
  try {
    fs.chmodSync(directory, 0o700);
  } catch {
    // Windows 不支持 POSIX 权限位，忽略。
  }

  const temporary = `${target}.tmp-${process.pid}`;
  try {
    fs.copyFileSync(template, temporary);
    fs.chmodSync(temporary, 0o600);
    fs.renameSync(temporary, target);
  } catch (error) {
    try {
      fs.rmSync(temporary, { force: true });
    } catch {
      // 清理失败不掩盖原始错误。
    }
    fail(`初始化数据库失败：${error.message}`);
  }
}

main();
