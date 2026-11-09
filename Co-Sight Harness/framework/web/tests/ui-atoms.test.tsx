/**
 * UI 原子组件测试（Button / IconButton / Tag / Avatar / Skeleton / StatusPanel / Icon）。
 *
 * 这些组件不依赖路由与查询，但仍然统一走 renderWithProviders：helpers/render.tsx
 * 的文档里它就写着"用来测原子组件与局部交互"，Provider 将来多一层（主题、语言）
 * 时不用回来改这一堆文件。
 *
 * 同一个用例里要对比两种 prop 时，用**两次 render** 而不是 rerender：renderWithProviders
 * 把 ui 包在 Provider 里交给 RTL，而 rerender 只替换最外层那个元素（Provider 会被
 * 换掉），React 于是整棵树重挂载——想测的"同一个实例换了 prop"其实变成了重挂载，
 * 组件内部 state 也一并重置。两棵树同时存在时按 name 或 container 各自查询即可。
 *
 * 断言优先落在无障碍树（role / 可访问名 / aria 属性）与真实交互结果上，而不是
 * 结构与实现细节：这些组件对用户（含读屏与键盘用户）呈现成什么，才是它们存在的意义。
 */

import { fireEvent, render, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Avatar } from '../src/components/ui/Avatar';
import { Button, IconButton } from '../src/components/ui/Button';
import buttonStyles from '../src/components/ui/Button.module.css';
import { Icon } from '../src/components/ui/Icon';
import { Skeleton } from '../src/components/ui/Skeleton';
import skeletonStyles from '../src/components/ui/Skeleton.module.css';
import { StatusPanel } from '../src/components/ui/StatusPanel';
import { Tag } from '../src/components/ui/Tag';
import tagStyles from '../src/components/ui/Tag.module.css';
import { renderWithProviders } from './helpers/render';

/**
 * 取 CSS Modules 里的类名。
 *
 * 类名是构建期生成的（vite 这边配的是 `cs-[hash]_[local]`），写死字符串等于把
 * 构建配置抄进测试；而直接写 `styles.primary` 得到的是 `string | undefined`
 * （noUncheckedIndexedAccess 对索引签名一视同仁）。这个函数把"类名一定存在"
 * 这层意思显式写出来，拼错类名时直接抛错，比断言一个 undefined 更好读。
 */
function styleClass(styles: Readonly<Record<string, string | undefined>>, name: string): string {
  const className = styles[name];
  if (className === undefined) {
    throw new Error(`CSS Modules 里没有 .${name}`);
  }
  return className;
}

/**
 * 查一个元素，查不到立刻抛错。
 *
 * 图标一律 aria-hidden，`getByRole` 这类按可访问性查询的手段完全看不见它们，
 * 只能走选择器；而选择器查空会静默返回 null，断言就变成了对一个 null 的断言。
 */
function mustQuery(root: ParentNode, selector: string): Element {
  const node = root.querySelector(selector);
  if (node === null) {
    throw new Error(`未找到 ${selector}`);
  }
  return node;
}

/** 只为了让 rerender 改的是 props 而不是重挂载，见文件头关于 rerender 的说明。 */
function AvatarWithSrc({ src }: { src: string }): ReactElement {
  return <Avatar name="张明远" src={src} />;
}

describe('Button', () => {
  it('默认 type="button"，放进表单里也不会变成提交按钮', () => {
    const { getByRole } = renderWithProviders(<Button>保存草稿</Button>);

    /*
     * HTML 里 <button> 不写 type 时默认是 "submit"，只是没有 form 时无从体现。
     * 工作台里按钮远多于表单，某天有人加一个包住整块内容的 <form>，"保存草稿"
     * 就会顺手把表单提交掉——而且只在真正的浏览器里才复现。
     */
    expect(getByRole('button', { name: '保存草稿' })).toHaveAttribute('type', 'button');
  });

  it('显式传 type="submit" 时原样输出', () => {
    const { getByRole } = renderWithProviders(<Button type="submit">提交</Button>);

    // 默认值必须是"可以被覆盖"的默认值，否则真需要提交时只能绕开这个组件。
    expect(getByRole('button', { name: '提交' })).toHaveAttribute('type', 'submit');
  });

  it('点击时调用 onClick', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { getByRole } = renderWithProviders(<Button onClick={onClick}>新建</Button>);

    await user.click(getByRole('button', { name: '新建' }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('disabled 时点击不派发 onClick', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { getByRole } = renderWithProviders(
      <Button onClick={onClick} disabled>
        新建
      </Button>,
    );
    const button = getByRole('button', { name: '新建' });

    expect(button).toBeDisabled();
    /*
     * 这里必须用 user-event：它会像浏览器一样跳过 disabled 元素上的 click。
     * 换 fireEvent.click 直接派发事件反而会调到 onClick，得到一条与真实浏览器
     * 相反的"绿"。
     */
    await user.click(button);

    expect(onClick).not.toHaveBeenCalled();
  });

  it('variant 与 size 落到类名上，默认 secondary + md', () => {
    const byDefault = renderWithProviders(<Button>确定</Button>);
    const customized = renderWithProviders(
      <Button variant="primary" size="sm">
        确定
      </Button>,
    );

    // 这两条钉住默认值：若有人把 primary 提成默认，卡片底部那一排按钮会整体变蓝。
    expect(within(byDefault.container).getByRole('button')).toHaveClass(
      styleClass(buttonStyles, 'secondary'),
    );
    expect(within(byDefault.container).getByRole('button')).toHaveClass(
      styleClass(buttonStyles, 'md'),
    );

    const button = within(customized.container).getByRole('button');
    expect(button).toHaveClass(styleClass(buttonStyles, 'primary'));
    expect(button).toHaveClass(styleClass(buttonStyles, 'sm'));
    expect(button).not.toHaveClass(styleClass(buttonStyles, 'secondary'));
  });

  it('图标是装饰性的，不参与可访问名', () => {
    const { getByRole } = renderWithProviders(<Button icon="search">搜索</Button>);
    const button = getByRole('button', { name: '搜索' });

    // 名字必须正好是"搜索"：Button 给 Icon 不传 title，图标对读屏软件隐藏，
    // 否则按钮会被念成"搜索 搜索"。
    expect(button).toHaveAttribute('type', 'button');
    expect(mustQuery(button, 'svg')).toHaveAttribute('aria-hidden', 'true');
  });
});

describe('IconButton', () => {
  it('label 既是可访问名也是悬停提示，图标本身对读屏软件隐藏', () => {
    const { getByRole } = renderWithProviders(<IconButton label="关闭设置" icon="close" />);
    const button = getByRole('button', { name: '关闭设置' });

    // 只有图标的按钮对读屏软件无字可读，label 现在是它唯一的名字来源；
    // 同时把它挂到 title 上，鼠标用户悬停也能看到同一句话，两处不会漂。
    expect(button).toHaveAttribute('title', '关闭设置');
    expect(mustQuery(button, 'svg')).toHaveAttribute('aria-hidden', 'true');

    /*
     * type 同样是 button：搜索框里的清空按钮就是这个组件，若它变成 submit，
     * 点一下"清空"会连带把外面的搜索表单提交出去。
     */
    expect(button).toHaveAttribute('type', 'button');
  });

  it('iconSize 传给图标，默认是 16px', () => {
    const sized = renderWithProviders(<IconButton label="重试" icon="retry" iconSize={20} />);
    const byDefault = renderWithProviders(<IconButton label="重试" icon="retry" />);

    // 图标默认跟随 16px 网格；放大是为了让"加载失败重试"这类单独出现的图标
    // 不至于在 24px 的按钮里显得空。
    expect(mustQuery(within(sized.container).getByRole('button'), 'svg')).toHaveAttribute(
      'width',
      '20',
    );
    expect(mustQuery(within(byDefault.container).getByRole('button'), 'svg')).toHaveAttribute(
      'width',
      '16',
    );
  });

  it('默认 ghost + sm + 正方形', () => {
    const { getByRole } = renderWithProviders(<IconButton label="重试" icon="retry" />);

    // ghost 对应"文字即按钮"的位置；iconOnly 去掉左右内边距让它保持正方——
    // 少了这个类，侧栏与搜索框里的图标按钮会变成一颗椭圆。
    const button = getByRole('button', { name: '重试' });
    expect(button).toHaveClass(styleClass(buttonStyles, 'ghost'));
    expect(button).toHaveClass(styleClass(buttonStyles, 'sm'));
    expect(button).toHaveClass(styleClass(buttonStyles, 'iconOnly'));
  });
});

describe('Tag', () => {
  it('渲染文本，title 作为截断后的补充信息', () => {
    const { getByText } = renderWithProviders(
      <Tag title="企业知识库构建专家">企业知识库构…</Tag>,
    );

    // 标签有 max-width、超出就省略号，悬停提示是读全名的唯一途径。
    expect(getByText('企业知识库构…')).toHaveAttribute('title', '企业知识库构建专家');
  });

  it('tone 落到类名上，默认 neutral', () => {
    const byDefault = renderWithProviders(<Tag>普通标签</Tag>);
    const brand = renderWithProviders(<Tag tone="brand">预置</Tag>);

    expect(within(byDefault.container).getByText('普通标签')).toHaveClass(
      styleClass(tagStyles, 'neutral'),
    );

    // brand 是"预置"标记：底用浅蓝、字用深灰（10px 下品牌蓝对比度不够）。
    // tone 断掉的话"预置"和普通标签长得一模一样，用户会以为那条可以随便改。
    expect(within(brand.container).getByText('预置')).toHaveClass(styleClass(tagStyles, 'brand'));
    expect(within(brand.container).getByText('预置')).not.toHaveClass(
      styleClass(tagStyles, 'neutral'),
    );
  });
});

describe('Avatar', () => {
  it('没有图片时显示名字首字', () => {
    const { getByText } = renderWithProviders(<Avatar name="张明远" />);

    // 中文名取第一个字（不是拼音首字母）：稿里头像位只有 24px，一个字更清楚。
    expect(getByText('张')).toBeInTheDocument();
  });

  it('英文名首字母转大写', () => {
    const { getByText } = renderWithProviders(<Avatar name="alice" />);

    // 小写字母在浅色圆底上的视觉重量明显弱于大写，而首字母是"没认出图"时
    // 用户唯一的线索。
    expect(getByText('A')).toBeInTheDocument();
  });

  it('空名字回落到 "?"，不会渲染成一片空白', () => {
    const { getByText, container } = renderWithProviders(<Avatar name="" />);

    // 专家的头像与姓名都来自后端，字段缺失时这里是最后一道兜底：
    // 空白圆看起来像渲染坏了，问号至少说明"这里本来有个头像"。
    expect(getByText('?')).toBeInTheDocument();
    expect(mustQuery(container, 'span')).toHaveAttribute('style');
  });

  it('始终对读屏软件隐藏', () => {
    const { container } = renderWithProviders(<Avatar name="张明远" src="/avatars/zhang.png" />);

    // 头像出现的两个位置（专家卡片、侧栏用户行）旁边都有同一个人名的可见文本，
    // 读屏软件再念一次头像只是重复；内部 <img alt=""> 也是同一层意思。
    expect(mustQuery(container, 'span')).toHaveAttribute('aria-hidden', 'true');
    expect(mustQuery(container, 'img')).toHaveAttribute('alt', '');
  });

  it('同名底色稳定，不同名字（本用例这两个）不同色', () => {
    const { container } = renderWithProviders(
      <>
        <Avatar name="张明远" />
        <Avatar name="张明远" />
        <Avatar name="李静" />
        <Avatar name="李静" />
      </>,
    );
    const colors = [...container.children].map((node) => node.getAttribute('style'));

    // 先确认内联样式里真的有颜色：否则下面几条只是在比较 null == null。
    expect(colors[0]).toMatch(/^background: /);
    // 同名两次渲染必须一模一样。色相是哈希而不是随机，随机会让同一位专家
    // 每次刷新换个颜色，用户会以为列表加载错了或者认错了人。
    expect(colors[0]).toBe(colors[1]);
    // 不同名字必须能区分，否则头像退化成一个纯装饰的圆。
    // 注意这里只保证"哈希到不同色相"，不是"名字不同就一定不同色"：色相按 360
    // 取模，名字一多必然撞色（实测 name="" 与 name="alice" 恰好同色）。
    expect(colors[2]).toBe(colors[3]);
    expect(colors[0]).not.toBe(colors[2]);
  });

  it('src 为空字符串或 null 时按"没有图"处理', () => {
    // 后端把缺失的 avatarUrl 序列化成 ""（而不总是 null）是常见情况。
    // 不判空就会渲染出 <img src="">，浏览器会拿当前页面地址再请求一次。
    const empty = renderWithProviders(<Avatar name="张明远" src="" />);
    const missing = renderWithProviders(<Avatar name="张明远" src={null} />);

    for (const { container } of [empty, missing]) {
      expect(container.querySelector('img')).toBeNull();
      expect(mustQuery(container, 'span')).toHaveTextContent('张');
    }
  });

  it('图片加载失败回落到首字', () => {
    const { container } = renderWithProviders(<Avatar name="张明远" src="/avatars/broken.png" />);

    fireEvent.error(mustQuery(container, 'img'));

    // 断言可见结果而不是 failedSrc 这个 state：这里关心的是"用户看到了什么"，
    // 失败地址怎么记是实现细节。
    const avatar = mustQuery(container, 'span');
    expect(avatar.querySelector('img')).toBeNull();
    expect(avatar).toHaveTextContent('张');
  });

  it('失败状态按地址记：同地址不再重试，换地址重新加载', () => {
    // 这里用不带 Provider 的 render：要让 rerender 改的是 props 而不是重挂载，
    // 否则 Avatar 的 state 会跟着重置，测出来的就不是"同一个实例换了地址"。
    const { container, rerender } = render(<AvatarWithSrc src="/avatars/a.png" />);

    fireEvent.error(mustQuery(container, 'img'));
    expect(container.querySelector('img')).toBeNull();

    // 同一个地址再渲染一次：不该"忘了刚失败过"又发出一次注定失败的请求。
    rerender(<AvatarWithSrc src="/avatars/a.png" />);
    expect(container.querySelector('img')).toBeNull();

    // 换成另一个地址必须重新尝试。失败状态若记成布尔，列表重排后这一行会一直
    // 停在首字上，直到整棵子树重挂载为止。
    rerender(<AvatarWithSrc src="/avatars/b.png" />);
    expect(mustQuery(container, 'img')).toHaveAttribute('src', '/avatars/b.png');
  });
});

describe('Skeleton', () => {
  it('对读屏软件隐藏', () => {
    const { container } = renderWithProviders(<Skeleton />);

    // 骨架屏是纯视觉占位，念出来只是一串"空白块"。真正的加载语义由外层容器的
    // aria-busy 承担，两者不该同时出现在无障碍树里。
    expect(mustQuery(container, 'span')).toHaveAttribute('aria-hidden', 'true');
  });

  it('尺寸落到内联样式：数字按 px、字符串按原样', () => {
    const pixel = renderWithProviders(<Skeleton width={200} height={12} />);
    const relative = renderWithProviders(<Skeleton width="60%" height="100%" />);

    // 数字自动补 px（卡片高度、行高这类固定值直接写数字）。
    expect(mustQuery(pixel.container, 'span')).toHaveStyle({ width: '200px', height: '12px' });
    // 字符串原样交给 CSS，于是 '100%' 这种跟着父级走的宽度可以直接传。
    expect(mustQuery(relative.container, 'span')).toHaveStyle({ width: '60%', height: '100%' });
  });

  it('circle 切成圆形', () => {
    const { container } = renderWithProviders(<Skeleton circle />);

    // 头像占位必须和真头像一样是正圆，否则数据到达时整块会"换形状"。
    expect(mustQuery(container, 'span')).toHaveClass(styleClass(skeletonStyles, 'circle'));
  });
});

describe('StatusPanel', () => {
  it('标题、提示与操作按钮都渲染', () => {
    const { getByText, getByRole } = renderWithProviders(
      <StatusPanel
        title="这个模块还没接入"
        hint="先到专家页看看"
        action={<Button>重试</Button>}
      />,
    );

    expect(getByText('这个模块还没接入')).toBeInTheDocument();
    expect(getByText('先到专家页看看')).toBeInTheDocument();
    expect(getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('没有 hint 与 action 时不留下空占位', () => {
    const { container } = renderWithProviders(<StatusPanel title="空空如也" />);

    // 面板是 flex column + gap 居中；多一个空的 <p>/<div> 会把标题和图标顶歪，
    // 而"只有标题"和"标题 + 提示"两种空态在页面上是并存的。
    expect(container.querySelectorAll('p')).toHaveLength(1);
    expect(container.querySelectorAll('svg')).toHaveLength(1);
  });

  it('role 只在显式传入时出现', () => {
    const quiet = renderWithProviders(<StatusPanel title="空空如也" />);
    const loud = renderWithProviders(<StatusPanel title="加载失败" role="alert" />);

    /*
     * 默认没有 role：空态是"替换掉了一块内容区"，不是"突然出现一条通知"。
     * 每次都播报会让读屏用户以为出了错——这也是这里用 role 而不是 aria-live
     * 的原因。
     */
    expect(mustQuery(quiet.container, 'div')).not.toHaveAttribute('role');

    // 出错时传 alert，读屏软件会立刻播报打断当前朗读；这条路径断了，
    // "加载失败"对读屏用户就是一次静默的空白。
    expect(mustQuery(loud.container, 'div')).toHaveAttribute('role', 'alert');
  });

  it('icon 可换，默认是 empty', () => {
    const byDefault = renderWithProviders(<StatusPanel title="出错了" />);
    const withAlert = renderWithProviders(<StatusPanel title="出错了" icon="alert" />);

    // 「加载失败」配感叹号、「空空如也」配日历：图标错了状态就传达错了，
    // 而这两种面板的文案经常是同一句"暂无数据"。
    expect(mustQuery(withAlert.container, 'svg').innerHTML).not.toBe(
      mustQuery(byDefault.container, 'svg').innerHTML,
    );
  });
});

describe('Icon', () => {
  it('按 name 渲染 svg，默认 16px 且对读屏软件隐藏', () => {
    const { container } = renderWithProviders(<Icon name="search" />);
    const svg = mustQuery(container, 'svg');

    expect(svg).toHaveAttribute('viewBox', '0 0 16 16');
    expect(svg).toHaveAttribute('width', '16');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    // 没有名字的裸 <svg> 在部分读屏软件里会被念成 "graphic"，所以既要隐藏、
    // 也不该带 role。
    expect(svg).not.toHaveAttribute('role');
  });

  it('给了 title 就是 img 语义，名字来自 title', () => {
    const { getByRole } = renderWithProviders(<Icon name="search" title="搜索" size={24} />);
    const icon = getByRole('img', { name: '搜索' });

    // 单独表意的图标（旁边没有文字）必须能读出名字。
    expect(icon).toHaveAttribute('width', '24');
    // 有 title 时不能再 aria-hidden，否则等于把刚给的名字又藏起来。
    expect(icon).not.toHaveAttribute('aria-hidden');
  });
});
