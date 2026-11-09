/**
 * 产物里两个模块侧辅助脚本：静态代理与数据库初始化。
 *
 * 它们不是框架自己的代码，而是**随模块进产物**的装配件（见
 * `docs/modules/smart-factory.artifact.json` 的 `bundle.assets`）。所以测试
 * 直接以子进程方式跑脚本本体，而不是把逻辑导出成函数再测——用户机器上
 * 执行的就是这一份文件，导入路径/CLI 参数写错同样会在这里暴露。
 */

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, it } from 'node:test';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB_SERVER = path.join(HERE, '..', 'artifact', 'module-web-server.mjs');
const DB_INIT = path.join(HERE, '..', 'artifact', 'module-db-init.mjs');

let scratch;
const children = [];

beforeEach(() => {
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-module-helpers-'));
});

afterEach(() => {
  for (const child of children.splice(0)) {
    child.kill('SIGKILL');
  }
  fs.rmSync(scratch, { recursive: true, force: true });
});

/** 拿一个当前空闲的端口：先监听 0，读到号再关。 */
function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function waitForLine(child, pattern, timeoutMs = 10_000) {
  return new Promise((resolve, reject) => {
    let buffer = '';
    const timer = setTimeout(() => reject(new Error(`等待 ${pattern} 超时；输出：${buffer}`)), timeoutMs);
    const onData = (chunk) => {
      buffer += chunk.toString('utf8');
      if (pattern.test(buffer)) {
        clearTimeout(timer);
        child.stdout.off('data', onData);
        resolve(buffer);
      }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', (chunk) => {
      buffer += chunk.toString('utf8');
    });
    child.once('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`脚本提前退出（${code}）；输出：${buffer}`));
    });
  });
}

function request(port, pathname, method = 'GET') {
  return new Promise((resolve, reject) => {
    const call = http.request({ host: '127.0.0.1', port, path: pathname, method }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => {
        resolve({
          status: response.statusCode,
          headers: response.headers,
          body: Buffer.concat(chunks).toString('utf8'),
        });
      });
    });
    call.on('error', reject);
    call.end();
  });
}

describe('module-web-server：静态托管 + 同源代理', () => {
  it('静态文件、SPA 回退、缺资源 404、路径穿越 403', async () => {
    const root = path.join(scratch, 'dist');
    fs.mkdirSync(path.join(root, 'assets'), { recursive: true });
    fs.writeFileSync(path.join(root, 'index.html'), '<!doctype html><title>sf</title>');
    fs.writeFileSync(path.join(root, 'assets', 'app.js'), 'console.info("sf")');
    fs.writeFileSync(path.join(scratch, 'outside.txt'), 'secret');

    const apiPort = await freePort();
    const port = await freePort();
    const child = spawn(process.execPath, [
      WEB_SERVER,
      '--root', root,
      '--port', String(port),
      '--api', `http://127.0.0.1:${apiPort}`,
    ], { stdio: ['ignore', 'pipe', 'pipe'] });
    children.push(child);
    await waitForLine(child, /模块前端已启动/);

    const index = await request(port, '/');
    assert.equal(index.status, 200);
    assert.match(index.headers['content-type'], /text\/html/);
    assert.match(index.body, /<title>sf<\/title>/);

    const asset = await request(port, '/assets/app.js');
    assert.equal(asset.status, 200);
    assert.match(asset.headers['cache-control'], /immutable/);

    // BrowserRouter 的深链接必须回到 index.html。
    const deepLink = await request(port, '/agent-dev/evaluate/123');
    assert.equal(deepLink.status, 200);
    assert.match(deepLink.body, /<title>sf<\/title>/);

    // 缺的是带扩展名的资源时不能回退成 HTML：否则前端拿到一页 HTML 当 JS 执行。
    const missing = await request(port, '/assets/missing.js');
    assert.equal(missing.status, 404);

    const traversal = await request(port, '/..%2foutside.txt');
    assert.equal(traversal.status, 403);
  });

  it('/api 与 WebSocket 升级都转发到模块后端，并把 Host 改写成后端地址', async () => {
    const root = path.join(scratch, 'dist');
    fs.mkdirSync(root, { recursive: true });
    fs.writeFileSync(path.join(root, 'index.html'), '<!doctype html>');

    const seen = [];
    // 升级之后 socket 不再算 server 的"普通连接"，`closeAllConnections()` 收拾不掉；
    // 自己记一份，测试结束时显式销毁，否则 `close()` 的回调永远等不到。
    const upstreamSockets = new Set();
    const upstream = http.createServer((req, res) => {
      seen.push({ url: req.url, host: req.headers.host });
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true, path: req.url }));
    });
    upstream.on('connection', (socket) => {
      upstreamSockets.add(socket);
      socket.on('close', () => upstreamSockets.delete(socket));
    });
    upstream.on('upgrade', (req, socket) => {
      seen.push({ upgrade: req.url, host: req.headers.host });
      socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n');
    });
    const apiPort = await freePort();
    await new Promise((resolve) => upstream.listen(apiPort, '127.0.0.1', resolve));

    const port = await freePort();
    const child = spawn(process.execPath, [
      WEB_SERVER,
      '--root', root,
      '--port', String(port),
      '--api', `http://127.0.0.1:${apiPort}`,
    ], { stdio: ['ignore', 'pipe', 'pipe'] });
    children.push(child);
    await waitForLine(child, /模块前端已启动/);

    const api = await request(port, '/api/smart-factory/v1/health');
    assert.equal(api.status, 200);
    assert.deepEqual(JSON.parse(api.body), { ok: true, path: '/api/smart-factory/v1/health' });
    assert.equal(seen[0].host, `127.0.0.1:${apiPort}`);

    // 非 /api 前缀的升级请求不该被代理（避免把静态端口变成通用转发器）。
    const rejected = await new Promise((resolve) => {
      const socket = net.connect(port, '127.0.0.1', () => {
        socket.write('GET /ws HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n');
      });
      socket.on('close', () => resolve('closed'));
      socket.on('error', () => resolve('error'));
      setTimeout(() => {
        socket.destroy();
        resolve('timeout');
      }, 1000);
    });
    assert.notEqual(rejected, 'timeout');

    const upgrade = await new Promise((resolve, reject) => {
      const socket = net.connect(port, '127.0.0.1', () => {
        socket.write(
          'GET /api/smart-factory/v1/ws HTTP/1.1\r\n' +
            'Host: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n',
        );
      });
      let buffer = '';
      socket.on('data', (chunk) => {
        buffer += chunk.toString('utf8');
        if (buffer.includes('101 Switching Protocols')) {
          socket.destroy();
          resolve(buffer);
        }
      });
      socket.on('error', reject);
      setTimeout(() => reject(new Error(`升级未完成：${buffer}`)), 3000);
    });
    assert.match(upgrade, /101 Switching Protocols/);
    const upgraded = seen.find((item) => item.upgrade !== undefined);
    assert.equal(upgraded.upgrade, '/api/smart-factory/v1/ws');
    assert.equal(upgraded.host, `127.0.0.1:${apiPort}`);

    await new Promise((resolve) => {
      // keep-alive 与已升级的连接都会让 close() 的回调永远不触发；
      // 测试里不需要优雅排空，直接销毁。
      for (const socket of upstreamSockets) {
        socket.destroy();
      }
      upstream.close(resolve);
    });
  });
});

describe('module-db-init：模板拷贝', () => {
  it('首次拷贝模板；再次运行不覆盖已有数据', async () => {
    const template = path.join(scratch, 'db-template.sqlite');
    fs.writeFileSync(template, 'template-bytes');
    const home = path.join(scratch, 'home');

    const run = () => new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [
        DB_INIT,
        '--template', template,
        '--file', 'smart-factory.db',
      ], {
        env: { ...process.env, COSIGHT_HOME: home },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      let stderr = '';
      child.stderr.on('data', (chunk) => {
        stderr += chunk.toString('utf8');
      });
      child.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(stderr))));
    });

    await run();
    const target = path.join(home, 'smart-factory.db');
    assert.equal(fs.readFileSync(target, 'utf8'), 'template-bytes');
    if (process.platform !== 'win32') {
      assert.equal(fs.statSync(target).mode & 0o777, 0o600);
    }

    fs.writeFileSync(target, 'user-data');
    await run();
    assert.equal(fs.readFileSync(target, 'utf8'), 'user-data');
  });

  it('目标文件名带路径分隔符、模板不存在都直接报错', async () => {
    const template = path.join(scratch, 'db-template.sqlite');
    fs.writeFileSync(template, 'x');

    const run = (args, env = { COSIGHT_HOME: scratch }) => new Promise((resolve) => {
      const child = spawn(process.execPath, [DB_INIT, ...args], {
        env: { ...process.env, ...env },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      let stderr = '';
      child.stderr.on('data', (chunk) => {
        stderr += chunk.toString('utf8');
      });
      child.on('exit', (code) => resolve({ code, stderr }));
    });

    const badName = await run(['--template', template, '--file', '../escape.db']);
    assert.notEqual(badName.code, 0);
    assert.match(badName.stderr, /不带路径分隔符的文件名/);

    const noHome = await run(['--template', template, '--file', 'x.db'], { COSIGHT_HOME: '' });
    assert.notEqual(noHome.code, 0);
    assert.match(noHome.stderr, /没有数据目录/);
  });
});

function writeDatabase(file, statements, rows = []) {
  const db = new DatabaseSync(file);
  try {
    for (const statement of statements) {
      db.exec(statement);
    }
    for (const [sql, params] of rows) {
      db.prepare(sql).run(...params);
    }
  } finally {
    db.close();
  }
}

function readAll(file, sql) {
  const db = new DatabaseSync(file, { readOnly: true });
  try {
    return db.prepare(sql).all().map((row) => ({ ...row }));
  } finally {
    db.close();
  }
}

function tableColumns(file, table) {
  return readAll(file, `PRAGMA table_info("${table}")`).map((row) => ({
    name: row.name,
    notNull: row.notnull === 1,
    defaultValue: row.dflt_value,
  }));
}

function indexNames(file) {
  return readAll(
    file,
    "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL ORDER BY name",
  ).map((row) => row.name);
}

function runDbInit(args) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [DB_INIT, ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
    });
    child.on('exit', (code) => resolve({ code, stdout, stderr }));
  });
}

/**
 * 旧库升级：产物里没有 Prisma CLI，模块自己的 `db.mjs sync` 跑不了。
 * 这条路径的实际触发点是模块加列之后老用户启动失败
 * （`The column 'main.agents.builtin' does not exist`），所以断言围绕
 * "结构追平模板 + 数据不丢 + 有备份 + 重复跑无副作用"。
 */
describe('module-db-init：旧库结构升级', () => {
  /** 模板：`agents.workspace_id` 可空，`runs.stage` 必填无默认值。 */
  const TEMPLATE_SQL = [
    'CREATE TABLE "agents" ("id" TEXT NOT NULL PRIMARY KEY, "workspace_id" TEXT, "builtin" BOOLEAN NOT NULL DEFAULT false, "name" TEXT NOT NULL)',
    'CREATE UNIQUE INDEX "agents_workspace_id_name_key" ON "agents"("workspace_id", "name")',
    'CREATE TABLE "runs" ("id" TEXT NOT NULL PRIMARY KEY, "stage" TEXT NOT NULL)',
    'CREATE INDEX "runs_stage_idx" ON "runs"("stage")',
    'CREATE TABLE "messages" ("id" TEXT NOT NULL PRIMARY KEY, "content" TEXT NOT NULL DEFAULT \'\')',
  ];

  /** 旧库：`workspace_id` 还是 NOT NULL，runs 还带着后来被替换掉的 approved_all。 */
  const OLD_SQL = [
    'CREATE TABLE "agents" ("id" TEXT NOT NULL PRIMARY KEY, "workspace_id" TEXT NOT NULL, "name" TEXT NOT NULL)',
    'CREATE TABLE "runs" ("id" TEXT NOT NULL PRIMARY KEY, "approved_all" BOOLEAN NOT NULL DEFAULT false)',
    'CREATE UNIQUE INDEX "uq_runs_one_active_per_instance" ON "runs"("id") WHERE "approved_all" = 0',
  ];

  function preparePair() {
    const home = path.join(scratch, 'home');
    fs.mkdirSync(home, { recursive: true });
    const template = path.join(scratch, 'db-template.sqlite');
    writeDatabase(template, TEMPLATE_SQL);
    writeDatabase(path.join(home, 'smart-factory.db'), OLD_SQL, [
      ['INSERT INTO "agents" ("id", "workspace_id", "name") VALUES (?, ?, ?)', ['a1', 'w1', '旧智能体']],
      ['INSERT INTO "runs" ("id", "approved_all") VALUES (?, ?)', ['r1', 0]],
    ]);
    return { home, template, target: path.join(home, 'smart-factory.db') };
  }

  it('缺列、缺表、列定义变化都追平模板，数据保留、外库列保留、有备份', async () => {
    const { home, template, target } = preparePair();

    const result = await runDbInit(['--template', template, '--file', 'smart-factory.db', '--dir', home]);
    assert.equal(result.code, 0, result.stderr);
    assert.match(result.stdout, /数据库结构已按当前版本补齐/);

    const agents = tableColumns(target, 'agents');
    assert.deepEqual(agents.map((column) => column.name), ['id', 'workspace_id', 'builtin', 'name']);
    assert.equal(agents.find((column) => column.name === 'workspace_id').notNull, false);
    assert.equal(agents.find((column) => column.name === 'builtin').defaultValue, 'false');

    const runs = tableColumns(target, 'runs');
    assert.ok(runs.some((column) => column.name === 'stage' && column.notNull));
    assert.ok(runs.some((column) => column.name === 'approved_all'), '模板外的列要保留');

    // 旧库没有的表按模板建出来。
    assert.deepEqual(tableColumns(target, 'messages').map((column) => column.name), ['id', 'content']);

    // 数据还在；新增的必填列在历史行上以类型空值补齐。
    assert.deepEqual(readAll(target, 'SELECT id, workspace_id, builtin, name FROM agents'), [
      { id: 'a1', workspace_id: 'w1', builtin: 0, name: '旧智能体' },
    ]);
    assert.deepEqual(readAll(target, 'SELECT id, stage, approved_all FROM runs'), [
      { id: 'r1', stage: '', approved_all: 0 },
    ]);

    // 索引以模板为准：旧的被移除，缺的补上。
    const indexes = indexNames(target);
    assert.ok(indexes.includes('agents_workspace_id_name_key'));
    assert.ok(indexes.includes('runs_stage_idx'));
    assert.ok(!indexes.includes('uq_runs_one_active_per_instance'));

    const backups = fs.readdirSync(home).filter((name) => name.includes('.bak-'));
    assert.equal(backups.length, 1);

    // 再跑一次：结构已经追上，什么都不写、也不再产生备份。
    const second = await runDbInit(['--template', template, '--file', 'smart-factory.db', '--dir', home]);
    assert.equal(second.code, 0, second.stderr);
    assert.equal(second.stdout, '');
    assert.equal(fs.readdirSync(home).filter((name) => name.includes('.bak-')).length, 1);
  });

  it('模板外且 NOT NULL 无默认值的列会让升级失败，原库保持原样', async () => {
    const home = path.join(scratch, 'home');
    fs.mkdirSync(home, { recursive: true });
    const template = path.join(scratch, 'db-template.sqlite');
    writeDatabase(template, ['CREATE TABLE "agents" ("id" TEXT NOT NULL PRIMARY KEY)']);
    const target = path.join(home, 'smart-factory.db');
    writeDatabase(
      target,
      ['CREATE TABLE "agents" ("id" TEXT NOT NULL PRIMARY KEY, "legacy" TEXT NOT NULL)'],
      [['INSERT INTO "agents" ("id", "legacy") VALUES (?, ?)', ['a1', 'x']]],
    );

    const result = await runDbInit(['--template', template, '--file', 'smart-factory.db', '--dir', home]);

    assert.equal(result.code, 1);
    assert.match(result.stderr, /不兼容/);
    assert.match(result.stderr, /legacy/);
    assert.deepEqual(tableColumns(target, 'agents').map((column) => column.name), ['id', 'legacy']);
    assert.equal(fs.readdirSync(home).filter((name) => name.includes('.bak-')).length, 0);
  });

  it('只缺可空/带默认值的列时不重建表，数据原样保留', async () => {
    const home = path.join(scratch, 'home');
    fs.mkdirSync(home, { recursive: true });
    const template = path.join(scratch, 'db-template.sqlite');
    writeDatabase(template, [
      'CREATE TABLE "agents" ("id" TEXT NOT NULL PRIMARY KEY, "name" TEXT NOT NULL, "icon" TEXT NOT NULL DEFAULT \'\')',
    ]);
    const target = path.join(home, 'smart-factory.db');
    writeDatabase(
      target,
      ['CREATE TABLE "agents" ("id" TEXT NOT NULL PRIMARY KEY, "name" TEXT NOT NULL)'],
      [['INSERT INTO "agents" ("id", "name") VALUES (?, ?)', ['a1', '旧智能体']]],
    );

    const result = await runDbInit(['--template', template, '--file', 'smart-factory.db', '--dir', home]);

    assert.equal(result.code, 0, result.stderr);
    assert.deepEqual(tableColumns(target, 'agents').map((column) => column.name), ['id', 'name', 'icon']);
    assert.deepEqual(readAll(target, 'SELECT id, name, icon FROM agents'), [
      { id: 'a1', name: '旧智能体', icon: '' },
    ]);
  });
});
