/**
 * 端到端脚本：用真实 ws 客户端驱动一条完整会话链路。
 *
 * 覆盖五条用例：允许 / 拒绝 / 允许所有（短路）/ 中止 / 需要提问。
 * 依赖一个已在运行的 server，地址由 SF_BASE / SF_WS 指定。
 *
 * 用法：
 *   node tests/e2e/session-flow.mjs                                     # Node 原生加载 .ts
 *   node --import tsx tests/e2e/session-flow.mjs                        # 旧 Node 走 tsx
 *   SF_PROMPT="用 Write 工具创建 e2e.txt" node tests/e2e/session-flow.mjs   # 对真实适配器
 */
import { WebSocket } from 'ws';
// 桩提示词标记直接复用 src 侧常量（Node 原生加载 .ts），不抄写中文标记字面量
import { FAKE_TRIGGER } from '../../src/shared/engine/fake-adapter.ts';

const BASE = process.env.SF_BASE ?? 'http://127.0.0.1:4100';
const WS_URL = process.env.SF_WS ?? 'ws://127.0.0.1:4100/api/smart-factory/v1/ws';
const PROMPT = process.env.SF_PROMPT ?? `${FAKE_TRIGGER.approval}：执行 echo hi`;
const API = `${BASE}/api/smart-factory/v1`;

const TERMINAL = ['succeeded', 'failed', 'aborted'];
let failures = 0;
/** 工作区 id 只取一次：账号下的工作区在 e2e 期间不会变，避免每个场景多一次框架调用。 */
let workspaceIdPromise;

function check(label, condition, extra) {
  if (condition) {
    console.log(`  ✓ ${label}`);
  } else {
    failures += 1;
    console.log(`  ✗ ${label}${extra === undefined ? '' : ` → ${JSON.stringify(extra)}`}`);
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function api(method, path, body) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload = await response.json().catch(() => null);
  return { status: response.status, body: payload };
}

async function waitTerminal(runId, timeoutMs = 120_000) {
  for (let waited = 0; waited < timeoutMs; waited += 250) {
    const { body } = await api('GET', `/runs/detail?runId=${runId}`);
    if (TERMINAL.includes(body.status)) return body;
    await sleep(250);
  }
  throw new Error(`run ${runId} 未在 ${timeoutMs}ms 内落终态`);
}

async function waitPending(sessionId, timeoutMs = 120_000) {
  for (let waited = 0; waited < timeoutMs; waited += 250) {
    const { body } = await api('GET', `/messages/list?sessionId=${sessionId}&status=pending&limit=10`);
    const interactive = body.items.find((m) => m.type === 'approval' || m.type === 'tool_interactive');
    if (interactive) return interactive;
    await sleep(250);
  }
  throw new Error('未等到挂起消息');
}

/** 连接 WS 并收集事件；返回应答式请求器 */
async function connect() {
  const socket = new WebSocket(WS_URL);
  const events = [];
  const pending = new Map();
  let sequence = 0;

  socket.on('message', (raw) => {
    const envelope = JSON.parse(raw.toString());
    if (envelope.type === 'event') {
      events.push(envelope);
    } else {
      pending.get(envelope.id)?.(envelope);
      pending.delete(envelope.id);
    }
  });
  await new Promise((resolve, reject) => {
    socket.on('open', resolve);
    socket.on('error', reject);
  });

  // 心跳由客户端驱动（4.06 §2）：20s 一次，落在服务端 60s 空闲窗口内留足余量；
  // 真机模型偶尔要跑一分钟以上才问权限，不发 ping 会被服务端按契约断线、漏掉事件
  const heartbeat = setInterval(() => {
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ id: `e2e_ping_${Date.now()}`, type: 'request', method: 'ping', timestamp: Date.now(), payload: {} }));
  }, 20_000);

  // 断线不静默：把在途请求就地结算成错误，检查项里能直接看到原因，而不是无限等
  socket.on('close', (code, reason) => {
    clearInterval(heartbeat);
    for (const settle of pending.values()) settle({ error: `连接已关闭：${code} ${String(reason)}` });
    pending.clear();
  });

  return {
    socket,
    events,
    request(method, payload) {
      sequence += 1;
      const id = `e2e_${sequence}`;
      const answer = new Promise((resolve) => pending.set(id, resolve));
      socket.send(JSON.stringify({ id, type: 'request', method, timestamp: Date.now(), payload }));
      return answer;
    },
    async waitEvent(method, predicate = () => true, timeoutMs = 120_000) {
      for (let waited = 0; waited < timeoutMs; waited += 100) {
        const hit = events.find((e) => e.method === method && predicate(e));
        if (hit) return hit;
        await sleep(100);
      }
      throw new Error(`未等到事件 ${method}`);
    },
    close() {
      clearInterval(heartbeat);
      socket.close();
    },
  };
}

/** 框架工作区 id：智能体必须归属一个工作区，取生效项或列表第一项。 */
function workspaceId() {
  workspaceIdPromise ??= (async () => {
    const { status, body } = await api('GET', '/workspaces/list');
    if (status !== 200) throw new Error(`取工作区失败：${status} ${JSON.stringify(body)}`);
    const id = body.activeId ?? body.items?.[0]?.id;
    if (!id) throw new Error('框架没有可用工作区，无法建智能体');
    return id;
  })();
  return workspaceIdPromise;
}

/**
 * 建一个智能体再在它上面建会话。
 *
 * 智能体现在有表了：`sessions/create` 要求 agentId 在 `agents` 表里存在（未知即 404），
 * 而 id 由服务端发（`agt_<uuid>`）、不能再自己拼一个目录名；建智能体还必须带 workspaceId。
 */
async function newSession(label) {
  const created = await api('POST', '/agents', { workspaceId: await workspaceId(), name: `e2e-${label}-${Date.now()}` });
  if (created.status !== 200) throw new Error(`建智能体失败：${created.status} ${JSON.stringify(created.body)}`);

  const { status, body } = await api('POST', '/sessions/create', { agentId: created.body.id });
  if (status !== 200) throw new Error(`建会话失败：${status} ${JSON.stringify(body)}`);
  return body;
}

async function scenario(decide, label) {
  console.log(`\n[用例] ${label}`);
  const session = await newSession(decide);
  const client = await connect();

  const ready = client.events.length;
  const subscribed = await client.request('subscribe', { sessionId: session.id });
  check('subscribe 返回 subscribed:true', subscribed.payload?.subscribed === true, subscribed.error);

  const sent = await client.request('send', { sessionId: session.id, prompt: PROMPT });
  check('send 返回 user 消息与 run', sent.payload?.message?.role === 'user' && !!sent.payload?.run?.id, sent.error);

  await client.waitEvent('run.started');
  const pending = await waitPending(session.id);
  check('收到 pending 的审批消息（WS 事件）', client.events.some((e) => e.method === 'message' && e.payload.id === pending.id), pending.id);

  const hanging = await api('GET', `/runs/detail?runId=${sent.payload.run.id}`);
  check('runs/detail 派生出 waiting', (hanging.body.waiting?.count ?? 0) >= 1, hanging.body.waiting);

  if (decide === 'abort') {
    const aborted = await api('POST', '/runs/abort', { runId: sent.payload.run.id });
    check('runs/abort 返回 aborted', aborted.body.status === 'aborted', aborted.body);
    const settled = await api('GET', `/messages/list?sessionId=${session.id}&status=pending`);
    check('中止后不再有挂起', settled.body.items.length === 0);
  } else {
    const responded = await client.request('message.respond', { messageId: pending.id, decision: decide });
    check(`message.respond(${decide}) 返回结算后的消息`, responded.payload?.message?.status !== 'pending', responded.error);

    const run = await waitTerminal(sent.payload.run.id);
    check('run 落 succeeded', run.status === 'succeeded', run.status);
    check('结算后 waiting 归空', run.waiting === null, run.waiting);

    const updates = client.events.filter((e) => e.method === 'message' && e.payload.id === pending.id);
    check('收到该挂起消息的 upsert 更新事件', updates.length >= 2, updates.length);
  }

  const history = await api('GET', `/messages/list?sessionId=${session.id}&limit=200`);
  const seqs = history.body.items.map((m) => m.seq);
  check('seq 从 1 连续', seqs.every((seq, index) => seq === index + 1), seqs);
  check('事件不重放（订阅后才有事件）', client.events.length > ready - 1);
  check('没有 message 事件早于订阅', client.events.filter((e) => e.method === 'message').length > 0);

  client.close();
  return session;
}

/** 需要提问：tool_interactive 挂起 → WS 应答 answers → 归一答案回给引擎，run 收口 */
async function interactiveScenario() {
  console.log('\n[用例] 需要提问');
  const session = await newSession('interactive');
  const client = await connect();

  const subscribed = await client.request('subscribe', { sessionId: session.id });
  check('subscribe 返回 subscribed:true', subscribed.payload?.subscribed === true, subscribed.error);

  const sent = await client.request('send', { sessionId: session.id, prompt: FAKE_TRIGGER.interactive });
  check('send 返回 user 消息与 run', sent.payload?.message?.role === 'user' && !!sent.payload?.run?.id, sent.error);

  await client.waitEvent('run.started');
  const pending = await waitPending(session.id);
  check('收到 pending 的交互消息（WS 事件）', client.events.some((e) => e.method === 'message' && e.payload.id === pending.id), pending.id);
  check('挂起类型为 tool_interactive', pending.type === 'tool_interactive', pending.type);

  const hanging = await api('GET', `/runs/detail?runId=${sent.payload.run.id}`);
  check('runs/detail 派生出 waiting', (hanging.body.waiting?.count ?? 0) >= 1, hanging.body.waiting);

  const answers = { [pending.content.questions[0].question]: ['CSV'] };
  const responded = await client.request('message.respond', { messageId: pending.id, answers });
  check('message.respond(answers) 返回 answered 的消息', responded.payload?.message?.status === 'answered', responded.error);
  check('结算内容带上归一后的 answers', JSON.stringify(responded.payload?.message?.content?.answers) === JSON.stringify(answers), responded.payload?.message?.content?.answers);

  const run = await waitTerminal(sent.payload.run.id);
  check('run 落 succeeded', run.status === 'succeeded', run.status);
  check('结算后 waiting 归空', run.waiting === null, run.waiting);

  const updates = client.events.filter((e) => e.method === 'message' && e.payload.id === pending.id);
  check('收到该挂起消息的 upsert 更新事件', updates.length >= 2, updates.length);

  const history = await api('GET', `/messages/list?sessionId=${session.id}&limit=200`);
  check('引擎收到归一答案', history.body.items.some((m) => m.content.text === `回答：${JSON.stringify(answers)}`), history.body.items.length);
  const seqs = history.body.items.map((m) => m.seq);
  check('seq 从 1 连续', seqs.every((seq, index) => seq === index + 1), seqs);

  client.close();
  return session;
}

async function main() {
  console.log(`目标：${BASE}`);
  console.log(`提示词：${PROMPT}`);

  await scenario('approved', '允许');
  await scenario('rejected', '拒绝');
  await scenario('approved_all', '允许所有（短路）');
  await scenario('abort', '中止');
  // SF_PROMPT 覆盖时按真实适配器跑：桩标记不适用，跳过交互用例
  if (process.env.SF_PROMPT === undefined) await interactiveScenario();

  console.log(`\n${failures === 0 ? '全部通过' : `失败 ${failures} 项`}`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((error) => {
  console.error(`e2e 异常：${error.message}`);
  process.exit(1);
});
