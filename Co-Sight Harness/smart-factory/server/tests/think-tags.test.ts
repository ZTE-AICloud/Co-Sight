/**
 * `<think>…</think>` 归类：MiniMax 经 vLLM 把推理写在普通 text block 开头，
 * 这里验证「完整文本」与「流式增量」两条路径的拆分口径一致。
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareTestEnv } from './helpers/test-db.js';

prepareTestEnv('think-tags');

const { ThinkTagFilter, splitLeadingThinkBlocks } = await import('../src/shared/engine/think-tags.js');
const { splitDraftThink } = await import('../src/shared/engine/claude-adapter.js');

/** 增量序列拼成完整输出，再按类型分组断言 */
function collect(filter: InstanceType<typeof ThinkTagFilter>, deltas: string[]): { thinking: string; text: string } {
  const thinking: string[] = [];
  const text: string[] = [];
  for (const delta of deltas) {
    for (const segment of filter.push(delta)) {
      (segment.kind === 'thinking' ? thinking : text).push(segment.text);
    }
  }
  for (const segment of filter.endBlock()) {
    (segment.kind === 'thinking' ? thinking : text).push(segment.text);
  }
  return { thinking: thinking.join(''), text: text.join('') };
}

/* ---------- 完整文本 ---------- */

test('splitLeadingThinkBlocks：开头的 think 段进思考，正文只留剩余', () => {
  assert.deepEqual(splitLeadingThinkBlocks('<think>用户问的是今天\n</think>\n\n今天是星期二。'), {
    thinking: ['用户问的是今天\n'],
    text: '今天是星期二。',
  });
});

test('splitLeadingThinkBlocks：前导空白不影响判定，拆除后正文不留空行', () => {
  assert.deepEqual(splitLeadingThinkBlocks('\n<think>想一想</think>\n\n答案'), {
    thinking: ['想一想'],
    text: '答案',
  });
});

test('splitLeadingThinkBlocks：多段连续 think 都收走', () => {
  assert.deepEqual(splitLeadingThinkBlocks('<think>一</think><think>二</think>正文'), {
    thinking: ['一', '二'],
    text: '正文',
  });
});

test('splitLeadingThinkBlocks：未闭合的 think 整段算思考（截断 / 中止）', () => {
  assert.deepEqual(splitLeadingThinkBlocks('<think>想到一半'), { thinking: ['想到一半'], text: '' });
});

test('splitLeadingThinkBlocks：正文中途的 `<think>` 不动，没有标签时原样返回', () => {
  const body = '讲讲 <think> 标签：它常见于推理模型。';
  assert.deepEqual(splitLeadingThinkBlocks(body), { thinking: [], text: body });
  assert.deepEqual(splitLeadingThinkBlocks('  缩进的正文'), { thinking: [], text: '  缩进的正文' });
});

test('splitLeadingThinkBlocks：不是 think 开头（只像前缀）不算标签', () => {
  assert.deepEqual(splitLeadingThinkBlocks('<thinker>不是标签</thinker>'), {
    thinking: [],
    text: '<thinker>不是标签</thinker>',
  });
});

test('splitLeadingThinkBlocks：带属性的开标签也算', () => {
  assert.deepEqual(splitLeadingThinkBlocks('<think type="reasoning">推理</think>答案'), {
    thinking: ['推理'],
    text: '答案',
  });
});

/* ---------- 流式增量 ---------- */

test('ThinkTagFilter：标签被切在帧之间也能正确归类', () => {
  const filter = new ThinkTagFilter();
  // 正文的前导换行照原样保留（流式不做 trim；渲染层无所谓这一两个换行）
  assert.deepEqual(collect(filter, ['<thi', 'nk>思考', '中</thi', 'nk>', '\n\n答案']), {
    thinking: '思考中',
    text: '\n\n答案',
  });
});

test('ThinkTagFilter：闭合标签与正文同一帧到达', () => {
  const filter = new ThinkTagFilter();
  assert.deepEqual(collect(filter, ['<think>想</think>答案']), { thinking: '想', text: '答案' });
});

test('ThinkTagFilter：不是 think 开头时逐字放行，保留前导空白', () => {
  const filter = new ThinkTagFilter();
  assert.deepEqual(collect(filter, ['  ', '你', '<thi', 'nk>是正文']), {
    thinking: '',
    text: '  你<think>是正文',
  });
});

test('ThinkTagFilter：判定前的缓冲不会丢字符；insideThinking 随段落翻转', () => {
  const filter = new ThinkTagFilter();
  assert.equal(filter.insideThinking, false);
  assert.deepEqual(filter.push('<think>'), []);
  assert.equal(filter.insideThinking, true);
  assert.deepEqual(filter.push('思考中</think>'), [{ kind: 'thinking', text: '思考中' }]);
  assert.equal(filter.insideThinking, false);
  assert.deepEqual(filter.push('答案'), [{ kind: 'text', text: '答案' }]);
});

test('ThinkTagFilter：未闭合时 endBlock 把残留吐成思考，并复位下一个块', () => {
  const filter = new ThinkTagFilter();
  // 短于闭合标签长度的内容整个攒着（可能是 `</thi` 的前缀），等 endBlock 收尾
  assert.deepEqual(filter.push('<think>想到一半'), []);
  assert.deepEqual(filter.endBlock(), [{ kind: 'thinking', text: '想到一半' }]);
  assert.equal(filter.insideThinking, false);
  assert.deepEqual(collect(filter, ['新块的正文']), { thinking: '', text: '新块的正文' });
});

test('ThinkTagFilter：每个块独立判断——上一块是思考，下一块仍是正文', () => {
  const filter = new ThinkTagFilter();
  const first = filter.push('<think>想</think>答');
  const rest = [...first.flatMap((segment) => [segment]), ...filter.endBlock()];
  assert.deepEqual(rest.map((segment) => segment.kind), ['thinking', 'text']);
  assert.deepEqual(collect(filter, ['第二块正文']), { thinking: '', text: '第二块正文' });
});

/* ---------- 落库草稿 ---------- */

test('splitDraftThink：text 草稿拆成思考 + 正文两条，角色保持 assistant', () => {
  assert.deepEqual(splitDraftThink({ role: 'assistant', type: 'text', content: { text: '<think>想</think>\n\n答' } }), [
    { role: 'assistant', type: 'thinking', content: { text: '想' } },
    { role: 'assistant', type: 'text', content: { text: '答' } },
  ]);
});

test('splitDraftThink：正文被吃空时只落思考，不留空文本消息', () => {
  assert.deepEqual(splitDraftThink({ role: 'assistant', type: 'text', content: { text: '<think>只有思考</think>' } }), [
    { role: 'assistant', type: 'thinking', content: { text: '只有思考' } },
  ]);
});

test('splitDraftThink：普通文本与非文本草稿原样返回', () => {
  const plain = { role: 'assistant', type: 'text', content: { text: '直接回答' } };
  assert.deepEqual(splitDraftThink(plain), [plain]);
  const tool = { role: 'assistant', type: 'tool_use', content: { toolCallId: 'tu_1', toolName: 'Bash', input: {} } };
  assert.deepEqual(splitDraftThink(tool), [tool]);
});
