#!/usr/bin/env node
/**
 * 测试用假 CLI：按 stream-json / control 协议回话，不调模型。
 *
 * 只实现传输层测试需要的分支：initialize、一条用户消息、一次 can_use_tool、
 * interrupt 与 result。stdin 关闭即退出。
 */

import { createInterface } from 'node:readline';

const rl = createInterface({ input: process.stdin });
let permissionToolUseId = null;

function send(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function respond(requestId, response) {
  send({ type: 'control_response', response: { subtype: 'success', request_id: requestId, response } });
}

function finish(outcome) {
  send({
    type: 'result',
    subtype: 'success',
    is_error: outcome === 'deny',
    result: outcome === 'deny' ? 'denied' : 'done',
    session_id: 'fake-session',
  });
}

rl.on('line', (line) => {
  if (line.trim() === '') return;
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    return;
  }

  if (message.type === 'control_request') {
    const request = message.request ?? {};
    if (request.subtype === 'initialize') {
      respond(message.request_id, {
        commands: [
          { name: 'fake-builtin', description: 'builtin', builtin: true },
          { name: 'fake-skill', description: 'skill', argumentHint: '--demo' },
        ],
        claude_code_version: '2.1.300',
      });
      send({ type: 'system', subtype: 'init', session_id: 'fake-session' });
      return;
    }
    if (request.subtype === 'interrupt') {
      respond(message.request_id, {});
      return;
    }
    return;
  }

  if (message.type === 'user') {
    if (message.message?.content === '__fail__') {
      process.stderr.write('fake failure\n');
      process.exit(1);
    }
    send({
      type: 'assistant',
      session_id: 'fake-session',
      message: { role: 'assistant', content: [{ type: 'text', text: 'hello' }] },
    });
    permissionToolUseId = 'toolu_fake';
    send({
      type: 'control_request',
      request_id: 'perm-fake',
      request: {
        subtype: 'can_use_tool',
        tool_name: 'Bash',
        input: { command: 'ls' },
        tool_use_id: permissionToolUseId,
      },
    });
    return;
  }

  if (message.type === 'control_response' && message.response?.request_id === 'perm-fake') {
    const result = message.response.response ?? {};
    finish(result.behavior === 'deny' ? 'deny' : 'allow');
  }
});

rl.on('close', () => {
  process.exit(0);
});
