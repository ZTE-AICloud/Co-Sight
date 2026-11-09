/** 测试用的专家样本；与种子数据无关，避免种子一变测试全红。 */

import type { CreateExpertInput } from 'harness-shared';

export function expertInput(overrides: Partial<CreateExpertInput> = {}): CreateExpertInput {
  return {
    name: '示例专家',
    author: '测试',
    description: '用于测试',
    avatarUrl: null,
    tags: ['测试'],
    isPreset: false,
    ...overrides,
  };
}
