/**
 * Segmented（单选分段控件）测试。
 *
 * 单独一个文件，是因为这里几乎没有"一个 prop 一条断言"式的用例：语义（radiogroup
 * 还是 tablist）、roving tabindex、方向键、环绕，都是整组的行为，一条用例里要同时
 * 看选中态与焦点落在哪。放在原子组件那个文件里会把两种节奏揉在一起。
 */

import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Segmented, type SegmentedOption } from '../src/components/ui/Segmented';
import { renderWithProviders } from './helpers/render';

type Filter = 'all' | 'hot' | 'new' | 'preset';

const OPTIONS: readonly SegmentedOption<Filter>[] = [
  { value: 'all', label: '全部' },
  { value: 'hot', label: '最热' },
  { value: 'new', label: '最新' },
  { value: 'preset', label: '预置' },
];

/**
 * 受控壳。
 *
 * Segmented 自己不存状态（value 与 onChange 都在外面），不套这一层就有两件事测不了：
 * 选中态是否跟着 onChange 转移、方向键移动后焦点是否也跟着走。回调照常往上报，
 * 方便断言"报的是什么值"。
 */
function Harness({ onChange }: { onChange: (value: Filter) => void }) {
  const [value, setValue] = useState<Filter>('all');
  return (
    <Segmented
      ariaLabel="专家筛选"
      options={OPTIONS}
      value={value}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
    />
  );
}

describe('Segmented', () => {
  it('整组是 radiogroup，选项是 radio 且只有选中项 aria-checked', () => {
    const { getByRole, getAllByRole } = renderWithProviders(<Harness onChange={vi.fn()} />);

    /*
     * 语义是"筛选项"而不是页签：四个选项的结果都渲染在下方同一个网格里，
     * 用 tablist 会让读屏软件去寻找一个并不存在的 tabpanel。
     */
    const group = getByRole('radiogroup', { name: '专家筛选' });
    expect(group).toBeInTheDocument();
    expect(getAllByRole('radio')).toHaveLength(OPTIONS.length);

    // 选中态由 aria-checked 表达，而不是靠样式或某个 data 属性：读屏软件听的是这个。
    expect(getByRole('radio', { name: '全部' })).toHaveAttribute('aria-checked', 'true');
    expect(getByRole('radio', { name: '最热' })).toHaveAttribute('aria-checked', 'false');
  });

  it('整组只有一个 Tab 停靠点，且停在选中项上', async () => {
    const user = userEvent.setup();
    const { getAllByRole, getByRole } = renderWithProviders(<Harness onChange={vi.fn()} />);

    /*
     * roving tabindex：未选中项 tabIndex=-1。整组对 Tab 序列只占一个位置，
     * 进去以后用方向键在组内走；否则四个选项会把 Tab 序列撑长三倍，用户
     * 想跳到搜索框得多按三次。
     */
    const stops = getAllByRole('radio').filter((radio) => radio.getAttribute('tabindex') === '0');
    expect(stops).toHaveLength(1);

    await user.tab();

    // 停靠点必须落在选中项上：落在第一项的话，用户每次进组都得再按方向键
    // 找当前筛选条件。
    expect(getByRole('radio', { name: '全部' })).toHaveFocus();
  });

  it('value 不匹配任何选项时仍保留 Tab 停靠点，回退到首项', async () => {
    const user = userEvent.setup();
    /*
     * "值不在选项里"不是假想状态：调用方从 `?filter=` 查询串取初值时就可能拿到一个
     * 后端已经不认的值。若此时每一项都是 tabIndex=-1，整组在 Tab 序列里彻底消失
     * ——radio 不像 input 那样会自己成为停靠点，键盘用户根本进不来。
     */
    const { getAllByRole, getByRole } = renderWithProviders(
      <Segmented
        ariaLabel="专家筛选"
        options={OPTIONS}
        value={'已废弃的筛选值' as Filter}
        onChange={vi.fn()}
      />,
    );

    const stops = getAllByRole('radio').filter((radio) => radio.getAttribute('tabindex') === '0');
    expect(stops).toHaveLength(1);

    await user.tab();
    expect(getByRole('radio', { name: '全部' })).toHaveFocus();

    // 回退的是 Tab 停靠点，不是把首项假装选上：四个选项都该是未选中。
    expect(getByRole('radio', { name: '全部' })).toHaveAttribute('aria-checked', 'false');
  });

  it('点击选项把值交回调用方，选中态随之转移', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { getByRole } = renderWithProviders(<Harness onChange={onChange} />);

    await user.click(getByRole('radio', { name: '最新' }));

    expect(onChange).toHaveBeenCalledWith('new');
    expect(getByRole('radio', { name: '最新' })).toHaveAttribute('aria-checked', 'true');
    expect(getByRole('radio', { name: '全部' })).toHaveAttribute('aria-checked', 'false');
  });

  it('点击已选中项也会回调一次', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { getByRole } = renderWithProviders(<Harness onChange={onChange} />);

    await user.click(getByRole('radio', { name: '全部' }));

    /*
     * 组件不判断"值没变就不回调"。写状态的调用方不会因此多渲染一次（React 对
     * 相同的 state 直接跳过），但把 onChange 当副作用用的调用方（比如重置分页、
     * 上报埋点）会多跑一次——这条断言把这个约定钉住，别指望组件替你挡。
     */
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith('all');
    expect(getByRole('radio', { name: '全部' })).toHaveAttribute('aria-checked', 'true');
  });

  it('方向键同时移动选中与焦点，上下与左右等价', async () => {
    const user = userEvent.setup();
    const { getByRole } = renderWithProviders(<Harness onChange={vi.fn()} />);

    await user.tab();
    await user.keyboard('{ArrowRight}');

    // 一次按键完成"移动焦点 + 改变选中"：WAI-ARIA 单选组不要求再按空格确认，
    // 这与 tablist 的行为不同，把 tab 的习惯带过来会以为控件没反应。
    expect(getByRole('radio', { name: '最热' })).toHaveFocus();
    expect(getByRole('radio', { name: '最热' })).toHaveAttribute('aria-checked', 'true');

    await user.keyboard('{ArrowLeft}');
    expect(getByRole('radio', { name: '全部' })).toHaveFocus();
    expect(getByRole('radio', { name: '全部' })).toHaveAttribute('aria-checked', 'true');

    // 上下键与左右键等价：控件横竖两种排布共用一套键，用户不必先看清它是横的还是竖的。
    await user.keyboard('{ArrowDown}');
    expect(getByRole('radio', { name: '最热' })).toHaveFocus();

    await user.keyboard('{ArrowUp}');
    expect(getByRole('radio', { name: '全部' })).toHaveFocus();
  });

  it('首尾环绕', async () => {
    const user = userEvent.setup();
    const { getByRole } = renderWithProviders(<Harness onChange={vi.fn()} />);

    await user.tab();

    // 从第一项往左跳到末项、从末项往右跳回第一项。不环绕的话，用户按到末尾时
    // 键还在响应但什么都没发生，看起来像控件坏了。
    await user.keyboard('{ArrowLeft}');
    expect(getByRole('radio', { name: '预置' })).toHaveFocus();
    expect(getByRole('radio', { name: '预置' })).toHaveAttribute('aria-checked', 'true');

    await user.keyboard('{ArrowRight}');
    expect(getByRole('radio', { name: '全部' })).toHaveFocus();
  });

  it('Home / End 跳到首尾', async () => {
    const user = userEvent.setup();
    const { getByRole } = renderWithProviders(<Harness onChange={vi.fn()} />);

    await user.tab();

    await user.keyboard('{End}');
    expect(getByRole('radio', { name: '预置' })).toHaveFocus();

    await user.keyboard('{Home}');
    expect(getByRole('radio', { name: '全部' })).toHaveFocus();
  });

  it('方向键阻止默认行为，切换筛选时不会顺带滚动页面', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Harness onChange={vi.fn()} />);

    const prevented: boolean[] = [];
    const record = (event: KeyboardEvent): void => {
      if (event.key === 'ArrowDown') {
        prevented.push(event.defaultPrevented);
      }
    };
    /*
     * 监听挂在 document 上（React 的委托监听在更下面的根容器，比这里先跑），
     * 于是读到的是组件处理之后的结果。这一点在 jsdom 里只能这么测：页面滚动
     * 本身没有布局可言，只能断言"默认行为被拦下了"。
     */
    document.addEventListener('keydown', record);
    try {
      await user.tab();
      await user.keyboard('{ArrowDown}');
    } finally {
      document.removeEventListener('keydown', record);
    }

    expect(prevented).toEqual([true]);
  });
});
