/**
 * i18n 层单测：翻译核心（纯函数）+ React 绑定（useI18n）。
 *
 * 这一层最贵的失败不是"翻译得不好"，而是**结构性的漏翻与静默降级**：
 * 词表少一个键、`{name}` 少一个占位符，都不会是编译错误，只会让界面上
 * 冒出一个键名或少一段信息。所以第一个 describe 花最大力气比对两份词表，
 * 其余的用例守的是"取不到时到底退化成什么"——一条错误的降级比崩溃更难发现。
 */

import { act, renderHook } from '@testing-library/react';
import { DEFAULT_LOCALE, SUPPORTED_LOCALES } from 'harness-shared';
import { beforeEach, describe, expect, it } from 'vitest';

import { enUS } from '../src/i18n/messages/en-US';
import { zhCN } from '../src/i18n/messages/zh-CN';
import {
  detectInitialLocale,
  htmlLangOf,
  isSupportedLocale,
  translate,
  translateApiErrorKey,
} from '../src/i18n/translate';
import type { MessageKey } from '../src/i18n/types';
import { useI18n } from '../src/i18n/useI18n';
import { useUiStore } from '../src/stores/ui';

/**
 * 递归展开成 `[点分路径, 词条]`。
 *
 * 直接比 `Object.keys` 只能看到 `app` / `nav` 这一层，而漏翻总是发生在叶子
 * （`app.wordmark` 这类）。展开成叶子路径才能让"少一条翻译"变成一个精确的 diff。
 */
function leafEntries(dictionary: object, prefix = ''): [key: string, text: string][] {
  return Object.entries(dictionary).flatMap(([segment, value]) =>
    typeof value === 'string'
      ? [[prefix + segment, value] as [key: string, text: string]]
      : leafEntries(value as object, `${prefix}${segment}.`),
  );
}

/** 取出模板里的占位符名，排序后便于比较。 */
function placeholders(template: string): string[] {
  return [...template.matchAll(/\{(\w+)\}/g)].map((match) => match[1] ?? '').toSorted();
}

describe('词表一致性', () => {
  /*
   * 这条是整个文件里最有价值的一条。
   *
   * `en-US.ts` 标注了 `: Messages`，所以它的**结构**由编译期保证；
   * 但 `Messages` 的叶子类型是 `string`，编译期管不到"这条到底翻了没有"——
   * 漏掉一条时界面上表现为那个位置显示成键名或中文，只有跑起来才看得见。
   * 词表本身又不在覆盖率统计里（见 vite.config.ts 的 coverage.exclude），
   * 于是这里是它唯一的守卫。
   */
  it('中英词表的叶子键集合完全一致', () => {
    const zhKeys = leafEntries(zhCN).map(([key]) => key);
    const enKeys = leafEntries(enUS).map(([key]) => key);

    // 先确认展开函数本身没坏：两侧都是空数组时 toStrictEqual 也会通过，
    // 那会变成一条永远绿的假测试。
    expect(zhKeys.length).toBeGreaterThan(20);

    expect(enKeys.toSorted()).toStrictEqual(zhKeys.toSorted());
  });

  it('每条词条都有非空文案', () => {
    // 空串不会报错、也不会显示键名，只会让界面上凭空少一句说明，
    // 是最难在评审里被发现的一种"翻了但等于没翻"。
    for (const dictionary of [zhCN, enUS]) {
      const blank = leafEntries(dictionary).filter(([, text]) => text.trim() === '');
      expect(blank).toStrictEqual([]);
    }
  });

  it('同一词条在中英两侧的占位符集合一致', () => {
    // 英文侧写出 `{total} experts` 而中文侧是固定文案（或反过来）时，
    // 插值不会报错，只是那个语言的数字凭空消失。
    const zhByKey = new Map(leafEntries(zhCN));
    const mismatched = leafEntries(enUS)
      .filter(([key, text]) => {
        const zh = zhByKey.get(key) ?? '';
        return placeholders(text).join(',') !== placeholders(zh).join(',');
      })
      .map(([key]) => key);

    expect(mismatched).toStrictEqual([]);
  });
});

describe('translate：取值、插值、兜底', () => {
  it('按语言取到同一条词条的两种文案', () => {
    expect(translate('zh-CN', 'nav.experts')).toBe('专家·技能');
    expect(translate('en-US', 'nav.experts')).toBe('Experts · Skills');
  });

  it('替换 {name} 占位符，数字参数被字符串化', () => {
    expect(translate('zh-CN', 'workspace.openNamed', { name: '周报助手' })).toBe(
      '周报助手（打开工作区设置）',
    );
    expect(translate('en-US', 'files.truncatedEntries', { count: 3 })).toBe(
      'Too many entries — showing the first 3',
    );
    // 0 是合法数值。若插值用真值判断（`value || ''`）而不是 `undefined` 判断，
    // 这里会渲染成空串——下限恰好是 0 的那种文案会凭空少一个数字。
    expect(translate('en-US', 'files.truncatedEntries', { count: 0 })).toBe(
      'Too many entries — showing the first 0',
    );
  });

  it('缺参数时原样保留占位符，而不是渲染 undefined', () => {
    // 界面出现 `{count}` 一眼能看出是漏传参数；出现 `undefined` 会被当成数据有问题。
    // 这是源码里刻意选的行为，用例把它钉住，防止有人"顺手"改成空串。
    expect(translate('en-US', 'files.truncatedEntries')).toBe(
      'Too many entries — showing the first {count}',
    );
    expect(translate('en-US', 'files.truncatedEntries', {})).toBe(
      'Too many entries — showing the first {count}',
    );
    expect(translate('en-US', 'workspace.createdNotActivated', { other: 'x' })).toBe(
      'The workspace was created, but switching to it failed: {reason}',
    );
  });

  it('多余的参数不影响结果', () => {
    expect(translate('en-US', 'files.truncatedEntries', { count: 2, unused: 'zzz' })).toBe(
      'Too many entries — showing the first 2',
    );
  });

  it('词表里没有的键返回键名本身（不抛错、不返回 undefined）', () => {
    // 正常路径走不到这里（MessageKey 编译期保证存在），但服务端 messageKey
    // 是运行期字符串；这条兜底保证任何情况下界面拿到的是 string 而不是崩页面。
    const unknownKey = 'does.not.exist' as MessageKey;

    expect(translate('zh-CN', unknownKey)).toBe('does.not.exist');
    expect(translate('en-US', unknownKey)).toBe('does.not.exist');
  });
});

describe('translateApiErrorKey：服务端 messageKey 的降级', () => {
  it('命中词表里的完整键时返回句子', () => {
    expect(translateApiErrorKey('zh-CN', 'error.not_found.workspace')).toBe('未找到工作区');
    expect(translateApiErrorKey('en-US', 'error.not_found.workspace')).toBe('Workspace not found');
  });

  it('前缀是字符串叶子时逐段降级到该前缀', () => {
    // `error.rate_limited` 本身是一条完整的文案，带上服务端多给的段时
    // 应当退到这句人话，而不是 null。
    expect(translateApiErrorKey('zh-CN', 'error.rate_limited.whatever')).toBe(
      '请求过于频繁，请稍后再试',
    );
  });

  it('前缀是分组节点时退到该分组的 default 子键', () => {
    /*
     * `error.not_found` 是对象节点（route/workspace/expert/... 的集合），渲染不出来，
     * 所以只在字符串叶子里找是不够的：那样"服务端新增了一种资源、词表还没跟上"
     * 会返回 null，调用方退到 `error.internal`，把一个 404 说成"服务内部错误"。
     *
     * 兜底走的是分组自己声明的 `default`——与 `error.not_implemented.default`
     * 同一套约定。这条断言钉的就是"这个 default 真的会被读到"。
     */
    expect(translateApiErrorKey('zh-CN', 'error.not_found.something_new')).toBe('未找到');
    expect(translateApiErrorKey('en-US', 'error.not_found.something_new')).toBe('Not found');
    expect(translateApiErrorKey('zh-CN', 'error.conflict.something_new')).toBe(
      '操作与现有数据冲突，请检查后重试',
    );

    // 分组已备好 default、但请求的是分组里确实存在的子键时，仍然优先具体的那句。
    expect(translateApiErrorKey('zh-CN', 'error.not_found.expert')).toBe('未找到专家');
    expect(translateApiErrorKey('zh-CN', 'error.not_implemented.model_probe')).toBe(
      '模型连通性探测尚未实现',
    );
    // 这一条在接上分组兜底之前永远走不到：`not_implemented` 下没有这个子键。
    expect(translateApiErrorKey('zh-CN', 'error.not_implemented.something_new')).toBe(
      '该功能尚未实现',
    );
  });

  it('两条降级路都无果时返回 null', () => {
    // 词表里没有任何前缀能命中（连 `error` 这个根都不是字符串），
    // 此时才交给调用方决定兜底文案，而不是把键名糊到界面上。
    expect(translateApiErrorKey('zh-CN', 'totally.unknown.key')).toBeNull();
    expect(translateApiErrorKey('en-US', '')).toBeNull();
  });

  it('对非错误域的键同样做插值（函数本身不认识"错误"这个概念）', () => {
    expect(translateApiErrorKey('zh-CN', 'files.truncatedEntries', { count: 5 })).toBe(
      '文件太多，只列出前 5 项',
    );
  });
});

describe('语言元信息', () => {
  it('isSupportedLocale 只接受受支持的语言', () => {
    expect(isSupportedLocale('zh-CN')).toBe(true);
    expect(isSupportedLocale('en-US')).toBe(true);

    // 语言标签的近亲（BCP-47 的更细粒度写法）不算受支持：本层要求精确匹配，
    // 前缀匹配只发生在 detectInitialLocale 里。
    expect(isSupportedLocale('zh')).toBe(false);
    expect(isSupportedLocale('zh-Hans-CN')).toBe(false);
    expect(isSupportedLocale(null)).toBe(false);
    expect(isSupportedLocale(42)).toBe(false);
    expect(isSupportedLocale(undefined)).toBe(false);
  });

  it('htmlLangOf 给出 <html lang> 用的 BCP-47 标签', () => {
    // 英文刻意是 `en` 而不是 `en-US`：`lang` 影响读屏的语音合成与 CJK 字体回退，
    // 全大写地区码没有额外好处。这条锚住映射表不被"统一成 locale 值"。
    expect(htmlLangOf('zh-CN')).toBe('zh-CN');
    expect(htmlLangOf('en-US')).toBe('en');
  });

  it('每种受支持语言都有 html lang，且默认语言是中文', () => {
    for (const locale of SUPPORTED_LOCALES) {
      expect(htmlLangOf(locale)).toBeTruthy();
    }
    expect(DEFAULT_LOCALE).toBe('zh-CN');
    expect([...SUPPORTED_LOCALES]).toStrictEqual(['zh-CN', 'en-US']);
  });
});

describe('detectInitialLocale：首帧语言', () => {
  it('存档里有受支持的值时以存档为准', () => {
    // 用户选过英文，即使浏览器语言是中文也不能在下次启动时被翻回去。
    expect(detectInitialLocale('en-US', ['zh-CN'])).toBe('en-US');
    expect(detectInitialLocale('zh-CN', ['en-US'])).toBe('zh-CN');
  });

  it('存档里的值受支持列表之外时忽略它，继续看浏览器语言', () => {
    // 手改过 localStorage、或降级掉一门语言时走这里：不能把非法值抛给调用方。
    expect(detectInitialLocale('fr-FR', ['fr-FR', 'en-GB'])).toBe('en-US');
    expect(detectInitialLocale('', [])).toBe(DEFAULT_LOCALE);
  });

  it('按前缀匹配浏览器语言，不区分大小写', () => {
    // `zh-Hans-CN` 这类更细的标签要落到 zh-CN；本平台只有两种语言，
    // 完整 BCP-47 协商不会得出第三种结果。
    expect(detectInitialLocale(null, ['zh-Hans-CN'])).toBe('zh-CN');
    expect(detectInitialLocale(null, ['EN-us'])).toBe('en-US');
    expect(detectInitialLocale(null, ['zh'])).toBe('zh-CN');
  });

  it('取第一个能识别的浏览器语言，都识别不出时用默认值', () => {
    expect(detectInitialLocale(null, ['de-DE', 'zh-CN', 'en-US'])).toBe('zh-CN');
    expect(detectInitialLocale(null, ['fr-FR', 'en-GB'])).toBe('en-US');
    expect(detectInitialLocale(null, [])).toBe(DEFAULT_LOCALE);
    expect(detectInitialLocale(null, ['de-DE'])).toBe(DEFAULT_LOCALE);
  });

  it('不自己读 localStorage——存档值由调用方注入', () => {
    // 签名里那个 `stored` 参数就是持久化的唯一入口。若哪天有人在函数内部
    // 直接读 localStorage，就会绕过调用点（stores/ui.ts 传的是 null，
    // 真正的 rehydrate 由 zustand persist 完成），这一条会红。
    localStorage.setItem('cosight.ui', JSON.stringify({ state: { locale: 'en-US' }, version: 1 }));

    expect(detectInitialLocale(null, ['zh-CN'])).toBe('zh-CN');
  });
});

describe('useI18n', () => {
  beforeEach(() => {
    // 全局 afterEach 会把 store 复位，但用例内部仍需要一个确定的起点：
    // store 走 persist，语言可能来自文件加载时 detectLocale() 的探测结果。
    useUiStore.setState({ locale: 'zh-CN' });
  });

  it('t 用 store 里的当前语言，tApi 走同一套降级', () => {
    const { result } = renderHook(() => useI18n());

    expect(result.current.locale).toBe('zh-CN');
    expect(result.current.t('nav.experts')).toBe('专家·技能');
    // 具体子键没收录 → 退到分组兜底；完整键 → 那一条。
    expect(result.current.tApi('error.not_found.something_new')).toBe(zhCN.error.not_found.default);
    expect(result.current.tApi('error.not_found.workspace')).toBe('未找到工作区');
  });

  it('切换语言后 t / tApi 立即反映新语言', () => {
    const { result } = renderHook(() => useI18n());

    act(() => {
      result.current.setLocale('en-US');
    });

    expect(result.current.locale).toBe('en-US');
    // 没有 Provider 需要重挂：语言是全局单例状态，订阅它的组件就地重渲染。
    expect(result.current.t('nav.experts')).toBe('Experts · Skills');
    expect(result.current.tApi('error.not_found.workspace')).toBe('Workspace not found');
  });

  it('语言不变时 t 的引用保持不变', () => {
    // t 会被大量组件放进 useMemo 的依赖数组（如拼 aria-label）。若每次渲染
    // 换一个新函数，那些 memo 会全部失效——这条用例就是 t 上 useCallback 的护栏。
    const { result, rerender } = renderHook(() => useI18n());
    const first = result.current.t;

    rerender();

    expect(result.current.t).toBe(first);
  });

  it('语言选择落进 localStorage（这是唯一的写入路径）', () => {
    const { result } = renderHook(() => useI18n());

    act(() => {
      result.current.setLocale('en-US');
    });

    // zustand persist 的同步 storage：写入发生在 setState 当次，不需要等 effect。
    expect(localStorage.getItem('cosight.ui')).toContain('"en-US"');
  });
});
