/**
 * 发送框 `/` 菜单的**前端预设词表**。
 *
 * 谁用这一份：首页、生成阶段、评估阶段（2026-10-21 定）。**预览阶段不用** ——
 * 那里应该列「这个智能体自己带了哪些技能」，需要一个按 agentId 查技能的后端接口
 * （还没做）。Composer 的 `commands` 是纯数据口子，接口上线后预览只需换传的数组，
 * 输入组件不用改。
 *
 * 词表为什么在前端而不是扫盘：命令是随产品分发的固定几项，扫 `.claude/skills`
 * 会把用户环境里的插件差异、40+ 官方插件全带进来，与本产品的「技能与指令」不是一回事。
 * 代价是**换版本 / 新装插件不会自动出现** —— 改这里之前先确认真实运行环境里有这个技能。
 *
 * 命令名是插进 prompt 的字面量（`/plugin:skill`），**不翻译**；说明随语言走。
 */

import { useMemo } from 'react';
import { useI18n } from '../../i18n/useI18n';
import type { MessageKey } from '../../i18n/types';
import type { ComposerCommand } from '../components/Composer';

interface PresetCommand {
  value: string;
  description: MessageKey;
}

/**
 * 首页预置需求默认挂的技能：**创建 / 改造智能体本来就是它的职责**。
 *
 * 导出字面量而不是让首页再写一遍：词表与「默认技能」必须是同一个字符串，
 * 将来改命令名时只改这里。
 */
export const HARNESS_CREATE = '/agent-genesis:harness-create';

/**
 * 技能优化的技能：多维评分 → 找缺口 → 改 → 再评分，直到达标。
 *
 * `--mode` 是它的必填入参（不传会当场报错退出），所以和命令名一起定在常量里：
 * 菜单里选一项、工坊拼首条消息，拿到的都是可直接跑的命令；目标路径由调用方接在后面
 * （`--skill-path <SKILL.md>`，见 `compose-prompt.ts`）。
 *
 * 与 `skill-foundry` 的「按点名清单改一轮」不是一回事，别把两者混用：
 * 首页「技能优化」卡与工坊的优化场都走这一个命令。
 */
export const SKILL_OPTIMIZE = '/skill-optimizer:skill_optimize --mode optimize';

/**
 * 顺序即菜单顺序（空查询时原样展示）。
 *
 * 名字带插件前缀：技能在运行时里就是按 `<plugin>:<skill>` 注册的，
 * 少写前缀会变成一个不存在的命令（发送后模型那边只会当成普通文字）。
 */
const PRESET: readonly PresetCommand[] = [
  { value: HARNESS_CREATE, description: 'slashCommands.harnessCreate' },
  { value: '/agent-genesis:skill-foundry', description: 'slashCommands.skillFoundry' },
  { value: SKILL_OPTIMIZE, description: 'slashCommands.skillEvolve' },
  { value: '/goldeval:agent-eval', description: 'slashCommands.agentEval' },
  { value: '/goldeval:goldeval', description: 'slashCommands.goldeval' },
  { value: '/goldeval:traceaudit', description: 'slashCommands.traceaudit' },
];

/**
 * 取预设词表（已翻译）。
 *
 * `t` 在语言切换前是稳定引用，所以数组也稳定 —— Composer 把它放进依赖里，
 * 每次渲染都换新数组会让候选浮层的 effect 反复重挂。
 */
export function usePresetCommands(): ComposerCommand[] {
  const { t } = useI18n();
  return useMemo(
    () => PRESET.map(({ value, description }) => ({ value, description: t(description) })),
    [t],
  );
}
