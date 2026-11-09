/**
 * SearchInput 测试。
 *
 * 组件是受控的（值存在调用方），所以每个用例都套一层 useState 壳：不套的话，
 * "敲完以后框里显示什么""清空后焦点回到哪"看到的都是没有回流的静态 DOM，
 * 断言等于没测。
 */

import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { SearchInput } from '../src/components/ui/SearchInput';
import { renderWithProviders } from './helpers/render';

/** 受控壳：把值照常报给用例，同时自己存一份，才能断言输入框里真实显示的内容。 */
function Harness({ onChange }: { onChange: (value: string) => void }) {
  const [value, setValue] = useState('');
  return (
    <SearchInput
      value={value}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
      ariaLabel="搜索专家"
      clearLabel="清空搜索"
      placeholder="按名称搜索"
    />
  );
}

describe('SearchInput', () => {
  it('是 searchbox，名字来自 aria-label', () => {
    const { getByRole, getByPlaceholderText } = renderWithProviders(
      <Harness onChange={vi.fn()} />,
    );

    // type="search" 让读屏软件报"搜索框"而不是"文本输入框"，按 role 查顺带把它钉住。
    expect(getByRole('searchbox', { name: '搜索专家' })).toBeInTheDocument();
    // 占位文字敲第一个字就消失了，当不了标签，所以 aria-label 是必需的；
    // placeholder 只负责给还没输入的人一个提示。
    expect(getByPlaceholderText('按名称搜索')).toBeInTheDocument();
  });

  it('每敲一个字回调一次，不做防抖', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { getByRole } = renderWithProviders(<Harness onChange={onChange} />);
    const input = getByRole('searchbox', { name: '搜索专家' });

    await user.type(input, 'abc');

    /*
     * 防抖属于"什么时候发请求"的策略，是调用方（专家列表 hook）的事。
     * 放在这里的话，同一个框换成"本地过滤"的用法也得跟着等 300ms，
     * 而且组件会同时承担输入与调度两件事。
     */
    expect(onChange).toHaveBeenCalledTimes(3);
    expect(onChange).toHaveBeenLastCalledWith('abc');
    expect(input).toHaveValue('abc');
  });

  it('空值时没有清空按钮', async () => {
    const user = userEvent.setup();
    const { getByRole, queryByRole } = renderWithProviders(<Harness onChange={vi.fn()} />);

    // 空框上挂一个"清空"是死按钮：键盘用户 Tab 过去按一下，什么都没发生。
    expect(queryByRole('button')).toBeNull();

    await user.type(getByRole('searchbox', { name: '搜索专家' }), '知');

    // 有内容才出现，且名字是调用方给的那句（不同页面上的"清空"含义不同）。
    expect(getByRole('button', { name: '清空搜索' })).toBeInTheDocument();
  });

  it('点击清空把值清掉，并把焦点交回输入框', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { getByRole, queryByRole } = renderWithProviders(<Harness onChange={onChange} />);
    const input = getByRole('searchbox', { name: '搜索专家' });

    await user.type(input, '知识库');
    await user.click(getByRole('button', { name: '清空搜索' }));

    expect(onChange).toHaveBeenLastCalledWith('');
    expect(input).toHaveValue('');
    expect(queryByRole('button')).toBeNull();

    /*
     * 这条是本用例的重点：清空按钮自己会随值变空而卸载，如果不显式把焦点
     * 交回输入框，焦点就掉回 body——键盘用户得从页头 Tab 一路回来才能接着改
     * 关键词。而"清空是为了继续找"，焦点留在框里才顺手。
     */
    expect(input).toHaveFocus();
  });
});
