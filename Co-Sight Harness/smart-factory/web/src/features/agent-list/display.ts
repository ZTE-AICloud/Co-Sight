/**
 * 专家页的展示层纯函数与词表。
 *
 * 单独一个文件是因为多处都要用：卡片、工具条（排序词表）、弹窗（标签文案）、
 * 页面（空态文案）。放进页面文件会造成「卡片 import 页面」的循环依赖。
 *
 * 时间格式（`formatTime` / `timeAgo`）2026-10-22 挪进 `shared/time.ts`：
 * 技能卡也要显示「多久以前」，两边不能各写一套。
 *
 * 头像（封面图 / 名称首字兜底）不在这里：创建页顶栏和弹窗预览也要用，
 * 按「第二个使用者就上升到 shared」挪进了 `shared/components/AgentAvatar.tsx`。
 *
 * 状态词表 2026-10-28 回来了：卡片要在名称下方显示产物状态，并据此决定「使用」能不能点
 * （只有 `completed` 可用）。词条按接口的 `AgentProductionStatus` 一一对应，`null` 归到
 * 「状态未知」—— 那只会出现在读取磁盘状态失败的那一条上。
 *
 * 标签配色（按文本哈希到四档色）2026-10-20 也撤掉了：参考稿的标签是**一色灰**，
 * 彩色的那一版太吵。现在标签只用 `.al-tag` 那一档灰底。
 */
import type { MessageKey } from '../../i18n/types';
import type { AgentProductionStatus } from '../../shared/api/agents';
import type { AgentSource } from '../../shared/agent-source';

type Translate = (key: MessageKey) => string;

/** 来源徽标 / 筛选的文案。「用户建的」在界面上仍叫「自定义」。 */
export function sourceLabel(source: AgentSource, t: Translate): string {
  return t(source === 'builtin' ? 'agentList.source.builtin.label' : 'agentList.source.custom.label');
}

/**
 * 产物状态的展示词。`null` 不是一个合法状态，只是普通行读取失败时的降级值，
 * 界面统一叫「状态未知」。
 */
export function statusLabel(status: AgentProductionStatus | null, t: Translate): string {
  if (status === null) return t('agentList.status.unknown');
  return t(`agentList.status.${status}`);
}

/** 只有生成完成的智能体才能「使用」。读到状态失败（`null`）一律按不可用处理。 */
export function isUsable(status: AgentProductionStatus | null): boolean {
  return status === 'completed';
}

/**
 * 来源下拉的选项（全部 / 内置 / 自定义），2026-10-29 起渲染在 `FilterSelect` 里。
 *
 * 它筛的是**来源**，不是排序；状态是旁边另一颗下拉（见 `statusFilters`）。
 * `user` = 用户建的（首页创建与收养的存量目录都算），`builtin` = 随产品提供。
 * 取值直接就是接口的 `?source=`，不再从标签里猜。
 */
export type SourceKey = 'all' | AgentSource;

/**
 * 状态下拉的选项（全部 / 已就绪 / 生成中 / 未开始 / 已暂停 / 生成失败）。
 *
 * 它筛的是卡片名称下面那行状态，取值直接就是接口的 `?status=`（现算派生，库里没有这一列）。
 * 只列枚举里的五个：`unknown` 是读盘失败的降级值，不是一种状态，接口也不收。
 * 「已就绪」排在最先 —— 那是这个筛选最常见的用法（只看现在能用的）。
 */
export type StatusKey = 'all' | AgentProductionStatus;

/** 词条随语言变化，所以出函数而不是常量 —— 常量只会在模块加载时求值一次。 */
export function statusFilters(t: Translate): { value: StatusKey; label: string }[] {
  return [
    { value: 'all', label: t('agentList.statusFilter.all') },
    { value: 'completed', label: statusLabel('completed', t) },
    { value: 'building', label: statusLabel('building', t) },
    { value: 'not_started', label: statusLabel('not_started', t) },
    { value: 'blocked', label: statusLabel('blocked', t) },
    { value: 'failed', label: statusLabel('failed', t) },
  ];
}

/** 词条随语言变化，所以出函数而不是常量 —— 常量只会在模块加载时求值一次。 */
export function sourceFilters(t: Translate): { value: SourceKey; label: string; hint: string }[] {
  return [
    { value: 'all', label: t('agentList.source.all.label'), hint: t('agentList.source.all.hint') },
    {
      value: 'builtin',
      label: t('agentList.source.builtin.label'),
      hint: t('agentList.source.builtin.hint'),
    },
    {
      value: 'user',
      label: t('agentList.source.custom.label'),
      hint: t('agentList.source.custom.hint'),
    },
  ];
}
