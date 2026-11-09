import { BadRequestError } from '../errors.js';
import { ClaudeAdapter } from './claude-adapter.js';
import { FakeAdapter } from './fake-adapter.js';
import type { EngineAdapter } from './port.js';

/** 引擎适配器注册表：唯一的绑定点。换引擎 = 加一个适配器文件 + 这里加一行。 */
const ENGINE_ADAPTERS: Record<string, () => EngineAdapter> = {
  fake: () => new FakeAdapter(),
  /** 外部 Claude Code CLI：运行机需自行安装 `claude`，本发行物不携带。 */
  'claude-cli': () => new ClaudeAdapter(),
};

/** 未知引擎立即抛错（fail-fast），不留到运行时报。 */
export function resolveEngineAdapter(engine: string): () => EngineAdapter {
  const factory = ENGINE_ADAPTERS[engine];
  if (!factory) {
    throw new BadRequestError(`未知引擎：${engine}（当前可用：${Object.keys(ENGINE_ADAPTERS).join(' / ')}）`);
  }
  return factory;
}
