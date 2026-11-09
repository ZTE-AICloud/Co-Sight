/**
 * 步骤条上的阶段顺序与短标签。
 *
 * 只放「导航需要知道的东西」。每个阶段自己的标题、说明、空态文案、布局，
 * 都归 `stages/*Stage.tsx`；集中在这里会重新长成一张「谁也不负责」的表。
 *
 * 标签随语言变化，所以出函数而不是常量：常量只会在模块加载时求值一次。
 */

import type { MessageKey, MessageParams } from '../../i18n/types';
import type { StageId } from './types';

export interface StageTab {
  id: StageId;
  label: string;
}

/**
 * 顺序即步骤条顺序，id 与后端的 `InstanceStage` 逐字一致。
 *
 * 后端有四个 stage，创建流程只走其中三个：`runtime` 不是「创建阶段」——
 * 它直接跑开发产物（原地，不拷贝），没有对应的创建面板，因此不出现在步骤条上。
 */
export function stageTabs(t: (key: MessageKey, params?: MessageParams) => string): StageTab[] {
  return [
    { id: 'development', label: t('create.stage.development') },
    { id: 'preview', label: t('create.stage.preview') },
    { id: 'evaluation', label: t('create.stage.evaluation') },
  ];
}
