import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ClaudeCliNotFoundError, ClaudeCliQuery } from '../src/shared/engine/claude-cli.js';
import type { ClaudeMessage, ClaudeUserMessage } from '../src/shared/engine/claude-protocol.js';
import { readSessionTitle } from '../src/shared/engine/session-title.js';

const FIXTURE = fileURLToPath(new URL('./fixtures/fake-claude.mjs', import.meta.url));

/** 把测试夹具包装成可执行件；Windows 用 .cmd，交给传输层的 cmd.exe 分支。 */
function makeBinary(dir: string): string {
  if (process.platform !== 'win32') {
    const target = join(dir, 'claude');
    copyFileSync(FIXTURE, target);
    chmodSync(target, 0o755);
    return target;
  }
  const target = join(dir, 'claude.cmd');
  writeFileSync(target, `@echo off\r\n"${process.execPath}" "${FIXTURE}" %*\r\n`);
  return target;
}

test('ClaudeCliQuery：initialize → 用户消息 → 审批 → result 完整往返', { timeout: 15_000 }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'fake-claude-test-'));
  const binary = makeBinary(dir);
  let release!: () => void;
  const done = new Promise<void>((resolve) => {
    release = resolve;
  });
  const calls: Array<{ toolName: string; input: Record<string, unknown> }> = [];

  const query = new ClaudeCliQuery({
    prompt: (async function* (): AsyncGenerator<ClaudeUserMessage> {
      yield { type: 'user', message: { role: 'user', content: 'hi' }, parent_tool_use_id: null };
      await done;
    })(),
    options: {
      cwd: dir,
      binary,
      permissionMode: 'acceptEdits',
      canUseTool: async (toolName, input) => {
        calls.push({ toolName, input });
        return {
          behavior: 'allow',
          updatedInput: input,
          toolUseID: 'toolu_fake',
          decisionClassification: 'user_temporary',
        };
      },
    },
  });

  try {
    const init = await query.initializationResult();
    assert.equal(init.claude_code_version, '2.1.300');
    assert.deepEqual(init.commands?.map((command) => command.name), ['fake-builtin', 'fake-skill']);

    const messages: ClaudeMessage[] = [];
    for await (const message of query) {
      messages.push(message);
      if (message.type === 'result') release();
    }

    assert.deepEqual(calls, [{ toolName: 'Bash', input: { command: 'ls' } }]);
    assert.ok(messages.some((message) => message.type === 'assistant'));
    const result = messages.find((message) => message.type === 'result');
    assert.equal(result?.result, 'done');
  } finally {
    query.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('readSessionTitle：优先 customTitle，其次 summary；非法 id 返回 null', async () => {
  const root = mkdtempSync(join(tmpdir(), 'session-title-'));
  const project = join(root, 'projects', 'proj');
  mkdirSync(project, { recursive: true });
  writeFileSync(
    join(project, 'sess-1.jsonl'),
    [
      JSON.stringify({ type: 'summary', summary: 'auto summary' }),
      JSON.stringify({ type: 'meta', customTitle: 'renamed title' }),
    ].join('\n'),
  );
  writeFileSync(join(project, 'sess-2.jsonl'), JSON.stringify({ type: 'summary', summary: 'only summary' }));

  const previous = process.env.CLAUDE_CONFIG_DIR;
  process.env.CLAUDE_CONFIG_DIR = root;
  try {
    assert.equal(await readSessionTitle('sess-1', '/tmp'), 'renamed title');
    assert.equal(await readSessionTitle('sess-2', '/tmp'), 'only summary');
    assert.equal(await readSessionTitle('../etc/passwd', '/tmp'), null);
    assert.equal(await readSessionTitle('missing', '/tmp'), null);
  } finally {
    if (previous === undefined) delete process.env.CLAUDE_CONFIG_DIR;
    else process.env.CLAUDE_CONFIG_DIR = previous;
    rmSync(root, { recursive: true, force: true });
  }
});

test('ClaudeCliQuery：interrupt 走 control 请求并收到回执', { timeout: 15_000 }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'fake-claude-interrupt-'));
  const binary = makeBinary(dir);
  const query = new ClaudeCliQuery({
    prompt: (async function* () {
      await new Promise(() => undefined);
    })(),
    options: { cwd: dir, binary },
  });

  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await query.initializationResult();
    await Promise.race([
      query.interrupt(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error('interrupt 没有收到回执')), 2_000);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    query.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('ClaudeCliQuery：CLI 异常退出时迭代器抛错，而不是正常结束', { timeout: 15_000 }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'fake-claude-fail-'));
  const binary = makeBinary(dir);
  const query = new ClaudeCliQuery({
    prompt: '__fail__',
    options: { cwd: dir, binary },
  });

  try {
    await assert.rejects(
      async () => {
        for await (const _message of query) {
          // 一直消费到异常退出；不应该正常结束
          void _message;
        }
      },
      /异常退出/,
    );
  } finally {
    query.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('ClaudeCliQuery：没有 claude 时初始化给出可操作的安装提示', { timeout: 15_000 }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'fake-claude-missing-'));
  const query = new ClaudeCliQuery({
    prompt: '',
    options: { cwd: dir, binary: join(dir, 'definitely-not-claude') },
  });

  try {
    await assert.rejects(query.initializationResult(), (error: unknown) => {
      assert.ok(error instanceof ClaudeCliNotFoundError);
      assert.match(error.message, /npm install -g @anthropic-ai\/claude-code/);
      return true;
    });
  } finally {
    query.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
