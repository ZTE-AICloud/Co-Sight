import type { MessageKey } from '../../i18n/types';
import type { IconName } from '../../shared/components/Icon';
import { HARNESS_CREATE, SKILL_OPTIMIZE } from '../../shared/commands/preset-commands';

/**
 * 首页的五类能力。
 *
 * 「能力」是**首页的状态**，不是正文里的命令：输入框开头那颗 chip 显示的就是这里的
 * `label`，正文只写需求。命令（`command`）**不在界面上展示**，只在提交时按能力分流 ——
 * 不靠用户在正文里写命令（写了会被挡下，见 `HomePage`）。
 *
 * 形态上与 `shared/commands/preset-commands.ts` 的词表**不是一回事**：那份是 Composer
 * `/` 菜单的候选；首页不再把 `/` 菜单接进发送框（能力由 chip 定，两套入口只会打架）。
 */
export type CapabilityKey =
  | 'agent.create'
  | 'agent.optimize'
  | 'agent.evaluate'
  | 'skill.create'
  | 'skill.evolve';

export interface CapabilityDef {
  key: CapabilityKey;
  /** chip / 卡片上的短名 */
  labelKey: MessageKey;
  /**
   * 这条能力真正会调的技能。**不展示**，只在提交时拼进 prompt（创建 / 优化智能体）。
   *
   * 字面量与 `preset-commands.ts` 保持同源（`HARNESS_CREATE` / `SKILL_OPTIMIZE`
   * 从那里引），别在这里另写一份命令名。
   */
  command: string;
  /** 卡片上的一句话 */
  subKey: MessageKey;
  icon: IconName;
  tint: string;
  /** 需要先定目标的能力：优化 / 评估智能体要智能体，技能优化要技能 */
  target: 'agent' | 'skill' | null;
}

/**
 * 顺序即卡片与 chip 菜单的顺序。
 *
 * 按「动作成对」排：创建智能体 / 创建技能、优化智能体 / 技能优化，评估智能体最后单独一行 ——
 * 两列网格里这样每一行读起来是一组，而不是按对象分组后把评估和创建技能挤在同一行。
 */
export const CAPABILITIES: readonly CapabilityDef[] = [
  {
    key: 'agent.create',
    labelKey: 'home.capability.agentCreate.label',
    command: HARNESS_CREATE,
    subKey: 'home.capability.agentCreate.sub',
    icon: 'wand',
    tint: '#3d9bf5',
    target: null,
  },
  {
    key: 'skill.create',
    labelKey: 'home.capability.skillCreate.label',
    command: '/agent-genesis:skill-foundry',
    subKey: 'home.capability.skillCreate.sub',
    icon: 'blocks',
    tint: '#22a06b',
    target: null,
  },
  {
    key: 'agent.optimize',
    labelKey: 'home.capability.agentOptimize.label',
    // 优化智能体与创建智能体是**同一个技能**（harness-create 本来就负责改造），
    // 差别只在落点：创建要新建身份，优化落到已有智能体的设计页继续改。
    command: HARNESS_CREATE,
    subKey: 'home.capability.agentOptimize.sub',
    icon: 'refresh',
    tint: '#7a5af5',
    target: 'agent',
  },
  {
    key: 'skill.evolve',
    labelKey: 'home.capability.skillEvolve.label',
    // 优化是评分驱动的另一条线，与「创建技能」的 skill-foundry 不是同一个技能
    command: SKILL_OPTIMIZE,
    subKey: 'home.capability.skillEvolve.sub',
    icon: 'zap',
    tint: '#e8930c',
    target: 'skill',
  },
  {
    key: 'agent.evaluate',
    labelKey: 'home.capability.evaluate.label',
    command: '/goldeval:agent-eval',
    subKey: 'home.capability.evaluate.sub',
    icon: 'gauge',
    tint: '#d9568f',
    target: 'agent',
  },
];

export function capabilityDef(key: CapabilityKey): CapabilityDef {
  return CAPABILITIES.find((cap) => cap.key === key) ?? CAPABILITIES[0];
}

/**
 * 剥掉正文开头那颗能力 chip 的字面量。
 *
 * chip 是 Composer 的命令 token，`readEditorText` 会把它的字面量读进正文（见 Composer
 * 的 TOKEN_TEXT_ATTR）；但能力是页面状态、不是需求文本，发给会话前必须去掉。
 *
 * **只剥开头**：用户正文里真的写了「创建智能体」这四个字（比如「评估一下创建智能体
 * 的那个专家」）不该被误删 —— 旧 demo 用 `replace` 全局第一个匹配，这里收紧到行首。
 */
export function stripCapabilityLabel(text: string, label: string): string {
  const trimmed = text.trimStart();
  const rest = trimmed.startsWith(label) ? trimmed.slice(label.length) : trimmed;
  return rest.trim();
}
