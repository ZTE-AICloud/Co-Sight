/**
 * 最小单轮 Messages 调用：无工具、非流式、一次拿全文本。
 *
 * 只给「后台补元数据」这类宿主内生的一次性任务用，**不是引擎** —— 会话仍走
 * `shared/engine/*`（带 cwd、工具、审批与流式事件）。这里刻意不引入 SDK 与工具面。
 *
 * 端点与鉴权口径照 `engine/claude-adapter`：`baseUrl` 等同 `ANTHROPIC_BASE_URL`
 * （SDK 自己补 `/v1/messages`），密钥走 `Authorization: Bearer`。
 */

export interface OneShotModel {
  modelName: string;
  baseUrl: string | null;
  apiKey: string;
}

/** 官方地址只在模型没配 baseUrl 时使用；网关地址由框架原样给出。 */
const OFFICIAL_BASE = 'https://api.anthropic.com';

export async function requestText(input: {
  model: OneShotModel;
  system: string;
  user: string;
  maxTokens: number;
  timeoutMs: number;
}): Promise<string> {
  const base = (input.model.baseUrl ?? OFFICIAL_BASE).replace(/\/+$/u, '');

  let response: Response;
  try {
    response = await fetch(`${base}/v1/messages`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'anthropic-version': '2023-06-01',
        authorization: `Bearer ${input.model.apiKey}`,
      },
      body: JSON.stringify({
        model: input.model.modelName,
        max_tokens: input.maxTokens,
        system: input.system,
        messages: [{ role: 'user', content: input.user }],
      }),
      signal: AbortSignal.timeout(input.timeoutMs),
    });
  } catch (error) {
    throw new Error(`模型调用失败：${error instanceof Error ? error.message : String(error)}`);
  }

  if (!response.ok) throw new Error(`模型返回 HTTP ${response.status}`);

  const body = (await response.json().catch(() => null)) as { content?: unknown } | null;
  const blocks = body?.content;
  if (!Array.isArray(blocks)) throw new Error('模型响应缺少 content');

  const text = blocks
    .map((block) => {
      const record = block as { type?: unknown; text?: unknown };
      return record.type === 'text' && typeof record.text === 'string' ? record.text : '';
    })
    .join('');
  if (text.trim() === '') throw new Error('模型响应没有文本');
  return text;
}
