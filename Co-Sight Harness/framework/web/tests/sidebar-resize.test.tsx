/**
 * 侧栏拖拽（需求 UX-2）行为测试。
 *
 * 测的是"宽度怎么变"这件纯逻辑，以及它的边界：
 * - 只在展开态有手柄（折叠态是定宽窄条）；
 * - 拖动严格跟随指针位移；
 * - 两端都夹住（拖出窗口外不能得到 5000 或者负数）；
 * - 松手之后再移动鼠标不能继续改宽度（不这样做的话，用户只是把鼠标移开侧栏，
 *   宽度就会跟着跑）；
 * - 键盘等价操作（拖拽对只用键盘的人等于不存在）。
 *
 * **jsdom 的现实**：它既没有 `PointerEvent`（25.0.1 的 living/events 里没有这个实现），
 * 也没有 `setPointerCapture`。所以下面用 `MouseEvent` 冒充指针事件——React 的
 * `onPointerDown` 只关心事件名和 `clientX` / `button`，这三样 MouseEvent 都有；
 * 而 `setPointerCapture` 那一行在 jsdom 里会短路（可选调用），真实浏览器里它才是
 * "拖到面板上方也不脱手"的保证。
 */

import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import {
  SIDEBAR_COLLAPSED_WIDTH,
  SIDEBAR_DEFAULT_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_MIN_WIDTH,
  SIDEBAR_RESIZE_STEP,
} from '../src/lib/sidebarWidth';
import { useUiStore } from '../src/stores/ui';
import { renderWithProviders } from './helpers/render';
import { Sidebar } from '../src/components/shell/Sidebar';

/** 手柄的无障碍名（`app.resizeSidebar`）。 */
const HANDLE = '调整侧栏宽度';

function handle(): HTMLElement {
  return screen.getByRole('separator', { name: HANDLE });
}

/** `<aside>` 在无障碍树上是 complementary。 */
function sidebar(): HTMLElement {
  return screen.getByRole('complementary');
}

/** 侧栏当前宽度（内联样式里的那个值，和真实浏览器读到的一致）。 */
function width(): number {
  return Number.parseInt(sidebar().style.width, 10);
}

type PointerType = 'pointerdown' | 'pointermove' | 'pointerup' | 'pointercancel';

/** 派发一个指针事件（用 MouseEvent 顶替，见文件头）。 */
function pointer(type: PointerType, clientX: number, button = 0): void {
  fireEvent(
    handle(),
    new MouseEvent(type, { bubbles: true, cancelable: true, clientX, button }),
  );
}

describe('侧栏拖拽：手柄的存在与形态', () => {
  it('展开态有一条可拖拽分割线，宽度作为它的当前值暴露给读屏软件', () => {
    renderWithProviders(<Sidebar />);

    expect(handle()).toBeInTheDocument();
    expect(handle()).toHaveAttribute('aria-orientation', 'vertical');
    // 分隔条同时是一个"滑块"：读屏软件要能念出当前宽度与取值范围。
    expect(handle()).toHaveAttribute('aria-valuenow', String(SIDEBAR_DEFAULT_WIDTH));
    expect(handle()).toHaveAttribute('aria-valuemin', String(SIDEBAR_MIN_WIDTH));
    expect(handle()).toHaveAttribute('aria-valuemax', String(SIDEBAR_MAX_WIDTH));
    // 裸数字没有单位：读屏软件只念 "280" 时，用户不知道自己在调什么量。
    expect(handle()).toHaveAttribute('aria-valuetext', `${SIDEBAR_DEFAULT_WIDTH} 像素`);
    // 指向被调整的那块面板，否则只知道"在调一个数值"、不知道调的是谁。
    expect(handle()).toHaveAttribute('aria-controls', sidebar().id);
    expect(sidebar().id).not.toBe('');
    // 可聚焦：不然键盘用户根本拿不到它。
    expect(handle()).toHaveAttribute('tabindex', '0');
  });

  it('折叠态没有手柄——窄条是定宽的，拖它没有意义', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);

    await user.click(screen.getByRole('button', { name: '切换侧栏' }));

    expect(screen.queryByRole('separator', { name: HANDLE })).toBeNull();
  });

  it('折叠再展开之后，宽度还是用户拖出来的那个值', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);

    pointer('pointerdown', 300);
    pointer('pointermove', 360);
    pointer('pointerup', 360);
    const dragged = SIDEBAR_DEFAULT_WIDTH + 60;
    expect(useUiStore.getState().sidebarWidth).toBe(dragged);

    await user.click(screen.getByRole('button', { name: '切换侧栏' }));
    expect(width()).toBe(SIDEBAR_COLLAPSED_WIDTH);

    await user.click(screen.getByRole('button', { name: '切换侧栏' }));
    // 折叠是"临时收起"，不该顺手把用户调过的宽度丢掉。
    expect(width()).toBe(dragged);
  });
});

describe('侧栏拖拽：指针', () => {
  it('宽度跟随指针位移', () => {
    renderWithProviders(<Sidebar />);
    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH);

    pointer('pointerdown', 300);
    pointer('pointermove', 340);
    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH + 40);

    // 往回收也要跟得上（起点是按下那一刻，不是上一次移动的位置）。
    pointer('pointermove', 320);
    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH + 20);

    pointer('pointerup', 320);
    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH + 20);
  });

  it('两端都夹住：拖到窗口外也不会得到 5000 或者负数', () => {
    renderWithProviders(<Sidebar />);

    pointer('pointerdown', 300);
    pointer('pointermove', 5000);
    expect(width()).toBe(SIDEBAR_MAX_WIDTH);

    pointer('pointermove', -5000);
    expect(width()).toBe(SIDEBAR_MIN_WIDTH);

    pointer('pointerup', -5000);
  });

  it('没按下就移动不会改宽度，松手后再移动也不会', () => {
    renderWithProviders(<Sidebar />);

    // 只是把鼠标划过侧栏右缘。
    pointer('pointermove', 400);
    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH);

    pointer('pointerdown', 300);
    pointer('pointermove', 400);
    pointer('pointerup', 400);
    const afterDrag = useUiStore.getState().sidebarWidth;

    // 松手之后指针还在移动（用户要把鼠标挪开），这时宽度必须已经定住。
    pointer('pointermove', 500);
    expect(useUiStore.getState().sidebarWidth).toBe(afterDrag);
    expect(width()).toBe(afterDrag);
  });

  it('右键拖拽不做任何事', () => {
    renderWithProviders(<Sidebar />);

    pointer('pointerdown', 300, 2);
    pointer('pointermove', 400);

    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH);
  });
});

describe('侧栏拖拽：收尾', () => {
  /*
   * 这一组盯的是"拖拽结束之后，拖拽状态有没有真的被还回去"。它比"宽度算得对不对"
   * 更容易漏：宽度算错是一眼能看见的，而一个卡住的 `dragging` 只会在下一次
   * **不按键**划过手柄时露馅。
   *
   * jsdom 里所有指针相关的方法都不存在，所以真实浏览器里那条"释放捕获会抛
   * NotFoundError"的路径本来永远走不到——下面第一个用例手动把它造出来（在实例上
   * 装一个必抛的 `releasePointerCapture`），让这条最容易出事的分支真被执行一次。
   */

  it('pointercancel 之后收尾必须完成，哪怕释放指针捕获抛了错', () => {
    renderWithProviders(<Sidebar />);

    pointer('pointerdown', 300);
    Object.defineProperty(handle(), 'releasePointerCapture', {
      configurable: true,
      // 真实浏览器在指针已被收走时就是这个行为（Chrome 实测抛 NotFoundError）。
      value: () => {
        throw new Error('NotFoundError');
      },
    });

    pointer('pointercancel', 300);
    const afterCancel = useUiStore.getState().sidebarWidth;

    // 幽灵拖拽的检查：不按任何键，只是让鼠标划过手柄带。
    pointer('pointermove', 500);
    expect(useUiStore.getState().sidebarWidth).toBe(afterCancel);
  });

  it('拖到一半切折叠（手柄被卸载）不会把"正在拖拽"留在侧栏上', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);

    pointer('pointerdown', 300);
    expect(sidebar().className).toContain('resizing');

    // 第二根手指去点折叠：侧栏切成窄条，手柄随之消失。`.resizing` 必须跟着还回去，
    // 否则展开之后宽度过渡还是关着的——折叠、展开、拖拽全都变成瞬移，且不可自愈。
    await user.click(screen.getByRole('button', { name: '切换侧栏' }));

    expect(sidebar().className).not.toContain('resizing');
  });
});

describe('侧栏拖拽：键盘', () => {
  it('方向键按 16px 步进，Home / End 直达两端', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);

    handle().focus();
    await user.keyboard('{ArrowRight}');
    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH + SIDEBAR_RESIZE_STEP);

    await user.keyboard('{ArrowLeft}{ArrowLeft}');
    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH - SIDEBAR_RESIZE_STEP);

    await user.keyboard('{Home}');
    expect(width()).toBe(SIDEBAR_MIN_WIDTH);

    await user.keyboard('{End}');
    expect(width()).toBe(SIDEBAR_MAX_WIDTH);

    // 念出来的值要跟着走：只更新 aria-valuenow 而 valuetext 留在旧值上，
    // 读屏用户听到的就是一个不动的数字。
    expect(handle()).toHaveAttribute('aria-valuetext', `${SIDEBAR_MAX_WIDTH} 像素`);
  });

  it('键盘把宽度顶到两端之后就不再变', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);

    handle().focus();
    await user.keyboard('{End}{ArrowRight}{ArrowRight}');
    expect(width()).toBe(SIDEBAR_MAX_WIDTH);

    await user.keyboard('{Home}{ArrowLeft}');
    expect(width()).toBe(SIDEBAR_MIN_WIDTH);
  });

  it('不认识的键不吞掉', async () => {
    const user = userEvent.setup();
    renderWithProviders(<Sidebar />);

    handle().focus();
    await user.keyboard('{Tab}');

    // Tab 仍然能把焦点移走（手柄把它 preventDefault 掉的话，键盘用户会被困在这里）。
    expect(handle()).not.toHaveFocus();
    expect(width()).toBe(SIDEBAR_DEFAULT_WIDTH);
  });
});
