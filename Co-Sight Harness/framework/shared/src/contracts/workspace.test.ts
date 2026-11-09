import { describe, expect, test } from 'vitest';

import { createWorkspaceInputSchema, updateWorkspaceInputSchema } from './workspace';

describe('createWorkspaceInputSchema', () => {
  test('只给名称即可创建（D16 = A：目录是可选的）', () => {
    const input = createWorkspaceInputSchema.parse({ name: '个人工作区' });
    expect(input.directory).toBeNull();
    expect(input.defaultModelId).toBeNull();
  });

  test('名称首尾空白被裁掉', () => {
    expect(createWorkspaceInputSchema.parse({ name: '  研发  ' }).name).toBe('研发');
  });

  test('相对路径被拒', () => {
    expect(
      createWorkspaceInputSchema.safeParse({ name: 'w', directory: './relative' }).success,
    ).toBe(false);
  });

  test('POSIX 与 Windows 绝对路径都接受', () => {
    expect(
      createWorkspaceInputSchema.safeParse({ name: 'w', directory: '/srv/project' }).success,
    ).toBe(true);
    expect(
      createWorkspaceInputSchema.safeParse({ name: 'w', directory: 'D:\\work\\proj' }).success,
    ).toBe(true);
  });

  test('空名称被拒', () => {
    expect(createWorkspaceInputSchema.safeParse({ name: '   ' }).success).toBe(false);
  });
});

describe('updateWorkspaceInputSchema', () => {
  test('空补丁被拒，避免无意义的写操作', () => {
    expect(updateWorkspaceInputSchema.safeParse({}).success).toBe(false);
  });

  test('允许把目录解绑回 null', () => {
    expect(updateWorkspaceInputSchema.parse({ directory: null }).directory).toBeNull();
  });

  test('部分字段更新被接受', () => {
    expect(updateWorkspaceInputSchema.parse({ name: '新名' }).name).toBe('新名');
  });
});
