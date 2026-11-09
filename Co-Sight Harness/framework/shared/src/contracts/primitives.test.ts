import { describe, expect, test } from 'vitest';

import { absolutePathSchema, httpUrlSchema } from './primitives';

describe('httpUrlSchema', () => {
  test('接受 http 与 https', () => {
    expect(httpUrlSchema.safeParse('http://localhost:4100/x').success).toBe(true);
    expect(httpUrlSchema.safeParse('https://api.example.com/v1').success).toBe(true);
  });

  test('拒绝把 scheme 伪造成主机名的写法', () => {
    // `z.url()` 本身会让这个值通过——`localhost:` 被当成 scheme。
    expect(httpUrlSchema.safeParse('localhost:8080').success).toBe(false);
  });

  test('拒绝 file: 与 javascript:', () => {
    expect(httpUrlSchema.safeParse('file:///etc/passwd').success).toBe(false);
    expect(httpUrlSchema.safeParse('javascript:alert(1)').success).toBe(false);
  });

  test('拒绝普通文本', () => {
    expect(httpUrlSchema.safeParse('not a url').success).toBe(false);
  });
});

describe('absolutePathSchema', () => {
  test('接受 POSIX 绝对路径', () => {
    expect(absolutePathSchema.parse('  /srv/project  ')).toBe('/srv/project');
  });

  test('接受 Windows 绝对路径', () => {
    expect(absolutePathSchema.safeParse('D:\\work\\proj').success).toBe(true);
  });

  test('拒绝相对路径', () => {
    expect(absolutePathSchema.safeParse('./relative').success).toBe(false);
    expect(absolutePathSchema.safeParse('relative/path').success).toBe(false);
  });

  test('拒绝未展开的波浪号', () => {
    expect(absolutePathSchema.safeParse('~/project').success).toBe(false);
  });

  test('拒绝空串', () => {
    expect(absolutePathSchema.safeParse('   ').success).toBe(false);
  });
});
