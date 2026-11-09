/**
 * `<think>…</think>` 文本的归类：把推理段与正文分开。
 *
 * MiniMax（经 vLLM 的 Anthropic 适配）不返回 Anthropic 的 thinking block，而是把推理
 * 直接写进普通 text block 的开头。不处理的话，推理会当正文落库、进历史与评估数据，
 * 界面上还会把 `<think>` 当字面标签画出来。
 *
 * 只认**文本开头**（允许前导空白）的 think 段：模型正文里合法提到这个标签的场景
 * （比如让它讲解 HTML 标签）不该被吞掉。多段连续开头也一并处理。
 */

/** 一段重新归类后的增量：思考或正文 */
export type ThinkTagSegment = { kind: 'thinking'; text: string } | { kind: 'text'; text: string };

const OPEN_PREFIX = '<think';
const OPEN_TAG = /^<think(\s[^>]*)?>$/;
const CLOSE_TAG = '</think>';

/**
 * 完整文本 → 开头的 think 段 + 剩余正文。
 *
 * 落库草稿、中止补落、run 终稿都走这里：它们拿到的是完整文本，不需要流式状态机。
 * 没有闭合的 think 段（模型被截断）整段算思考，正文留空。
 */
export function splitLeadingThinkBlocks(text: string): { thinking: string[]; text: string } {
  const thinking: string[] = [];
  let rest = text;
  let stripped = false;
  for (;;) {
    const trimmed = rest.replace(/^\s+/, '');
    const open = trimmed.startsWith(OPEN_PREFIX) ? trimmed.indexOf('>') : -1;
    if (open < 0 || !OPEN_TAG.test(trimmed.slice(0, open + 1))) break;
    stripped = true;

    const body = trimmed.slice(open + 1);
    const close = body.indexOf(CLOSE_TAG);
    if (close < 0) {
      // 未闭合：剩下的都算思考（截断 / 中止）
      thinking.push(body);
      return { thinking, text: '' };
    }
    thinking.push(body.slice(0, close));
    rest = body.slice(close + CLOSE_TAG.length);
  }
  // 剥过 think 段时去掉残留的开头空白；没见过标签的正文原样返回
  return { thinking, text: stripped ? rest.replace(/^\s+/, '') : rest };
}

/**
 * 流式文本的归类器：按块存在，收到增量就吐出「思考 / 正文」增量。
 *
 * 标签可能被切在任意两帧之间（`<thi` + `nk>`），所以 head 状态要缓冲到能判定为止，
 * 判定成正文后立即放行、不再改判 —— 中途出现 `<think>` 属于正文内容。
 */
export class ThinkTagFilter {
  private buffer = '';
  private mode: 'head' | 'thinking' | 'text' = 'head';

  /** 当前是否处在 think 段内：调用方据此补 start / stop 事件 */
  get insideThinking(): boolean {
    return this.mode === 'thinking';
  }

  /** 文本块开始：每个块独立判断开头 */
  startBlock(): void {
    this.buffer = '';
    this.mode = 'head';
  }

  /** 推入增量；返回值可能同时含思考与正文（例如 `</think>\n\n答案` 一帧到达） */
  push(delta: string): ThinkTagSegment[] {
    if (delta === '') return [];
    this.buffer += delta;
    return this.drain(false);
  }

  /** 文本块结束：把缓冲的残留按当前状态吐出，并复位到下一块 */
  endBlock(): ThinkTagSegment[] {
    const segments = this.drain(true);
    this.startBlock();
    return segments;
  }

  /**
   * `final=false` 时能吐多少吐多少、吐不了的留到下一帧；`final=true` 时全部吐完。
   * thinking 模式未闭合时只留「可能是 `</think>` 前缀」的尾巴（最多 7 个字符），
   * 否则每个字符都要等下一帧，思考内容会以一字一顿的方式显示。
   */
  private drain(final: boolean): ThinkTagSegment[] {
    const segments: ThinkTagSegment[] = [];
    for (;;) {
      if (this.mode === 'text') {
        if (this.buffer !== '') segments.push({ kind: 'text', text: this.buffer });
        this.buffer = '';
        return segments;
      }

      if (this.mode === 'head') {
        const trimmed = this.buffer.replace(/^\s+/, '');
        if (trimmed === '') {
          // 只有空白：正文还是思考取决于下一帧，先攒着
          if (final) this.buffer = '';
          return segments;
        }
        if (!trimmed.startsWith(OPEN_PREFIX)) {
          // `OPEN_PREFIX.startsWith(trimmed)`：目前还只是 `<thi` 这样的真前缀，等更多字符
          if (OPEN_PREFIX.startsWith(trimmed) && !final) return segments;
          // 不是 think 开头：整体按正文放行（保留前导空白，那是正文的一部分），此后不再改判
          segments.push({ kind: 'text', text: this.buffer });
          this.buffer = '';
          this.mode = 'text';
          return segments;
        }
        const end = trimmed.indexOf('>');
        if (end < 0) {
          if (!final) return segments;
          segments.push({ kind: 'text', text: this.buffer });
          this.buffer = '';
          this.mode = 'text';
          return segments;
        }
        if (!OPEN_TAG.test(trimmed.slice(0, end + 1))) {
          // `<think 后面跟着别的东西`：不是标签，按正文
          segments.push({ kind: 'text', text: this.buffer });
          this.buffer = '';
          this.mode = 'text';
          return segments;
        }
        this.buffer = trimmed.slice(end + 1);
        this.mode = 'thinking';
        continue;
      }

      // thinking：找闭合标签
      const close = this.buffer.indexOf(CLOSE_TAG);
      if (close >= 0) {
        if (close > 0) segments.push({ kind: 'thinking', text: this.buffer.slice(0, close) });
        this.buffer = this.buffer.slice(close + CLOSE_TAG.length);
        this.mode = 'text';
        continue;
      }
      if (final) {
        if (this.buffer !== '') segments.push({ kind: 'thinking', text: this.buffer });
        this.buffer = '';
        return segments;
      }
      const keep = Math.min(this.buffer.length, CLOSE_TAG.length - 1);
      const cut = this.buffer.length - keep;
      if (cut > 0) segments.push({ kind: 'thinking', text: this.buffer.slice(0, cut) });
      this.buffer = this.buffer.slice(cut);
      return segments;
    }
  }
}
