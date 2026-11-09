import { useMemo } from 'react';
import { useLocation } from 'react-router';
import { pickModuleForCapability, type ModuleCapability } from 'harness-shared';

import { useI18n } from '../../i18n/useI18n';
import { useActiveModel } from '../../api/models';
import { useModules } from '../../api/system';
import { useActiveWorkspace } from '../../api/workspaces';
import { useNewChatStore } from '../../stores/newChat';
import { useObservabilityReloadStore } from '../../stores/observabilityReload';
import { Button } from '../ui/Button';
import { StatusPanel } from '../ui/StatusPanel';
import styles from './embedFrame.module.css';

export interface ModuleHostProps {
  capability: ModuleCapability;
  /**
   * 当前模型 / 工作区变化时重新挂载 iframe，等价于让模块整体刷新一次。
   *
   * 只有需要"结果跟着全局上下文走"的页面才开（专家列表 / Agent 开发 / 评估）。
   * 模块拿不到宿主的切换事件——这里刻意没有 postMessage 桥（见下方第 2 条）——
   * 而它自己的入口加载时就会按当前上下文重新请求，所以重建 iframe 是最小且不会
   * 说谎的做法。专家列表其实只随工作区变，模型变时也会重建一次：代价是模块多拉
   * 一遍列表，换来的是"切换上下文后绝不显示旧数据"。关着时不订阅这两个查询，
   * 避免给会话 / 观测等页面多发请求。
   */
  reloadOnContextChange?: boolean;
}

/**
 * 把某个能力对应的模块前端嵌进主面板（C2：iframe + 清单寻址）。
 *
 * 几件**刻意不做**的事：
 *
 * 1. **宿主不代模块做桥接会话。** D25 的设计是模块从**自己的源**调
 *    `/api/bridge/token` 再 `/api/bridge/exchange`——令牌里记录的是"哪个源换的"，
 *    换个源就换不出来。若由宿主代为换发再把会话交给模块，这条约束就没了。
 * 2. **不做 postMessage 协议。** 语言已经通过 URL 参数传下去了，够用。
 *    现在没有模块可对接，先写一套没人消费的消息协议，等真有模块时多半是错的。
 * 3. **不允许同源模块。** `validateModuleManifest` 会拒绝与宿主同源的 entry
 *    （D24），所以这里拿到的 entry 一定是跨源的，sandbox 才有意义。
 */
export function ModuleHost({ capability, reloadOnContextChange = false }: ModuleHostProps) {
  const { t, locale } = useI18n();
  const { search } = useLocation();
  const query = useModules();
  /*
   * 两个查询只在开启刷新时才订阅。关掉时 `enabled: false` 不会发请求，
   * 但如果别处已经查过，仍然读得到同一份缓存。
   */
  const activeModel = useActiveModel({ enabled: reloadOnContextChange });
  const activeWorkspace = useActiveWorkspace({ enabled: reloadOnContextChange });
  /*
   * 对话页专用：点「新建对话」时 nonce 递增，key 变化 → iframe 重建 → 模块回到空态。
   * 其它能力不订阅这个信号（它们没有”新建”动作）。
   */
  const newChatNonce = useNewChatStore((state) => state.nonce);
  /*
   * 观测模块专用：点「观测」导航项时（已在该页面）nonce 递增，触发 iframe 重建，
   * 模块重新加载并回到会话列表页（默认路由）。
   */
  const observabilityReloadNonce = useObservabilityReloadStore((state) => state.nonce);

  const manifest = useMemo(
    () => (query.data === undefined ? null : pickModuleForCapability(query.data.modules, capability)),
    [query.data, capability],
  );
  /*
   * 同一份前端可以挂多个页面：清单用 `mounts[].entryPath` 说明"这个能力在模块里是哪一页"。
   * 不声明时落到 `entry` 本身（cosight-viewer 这类靠 `?capability=` 自选的模块就走这条）。
   */
  const entryPath = useMemo(
    () => manifest?.mounts.find((mount) => mount.capability === capability)?.entryPath ?? null,
    [manifest, capability],
  );

  /*
   * 上下文版本：任一变化就换 key → iframe 重建 → 模块重新请求一遍。
   *
   * 工作区自己的 `defaultModelId` 也进 key：它决定该工作区最终用哪个模型，
   * 改它和切换全局模型对模块是同一件事。
   */
  const contextKey = [
    activeWorkspace.data?.id ?? 'no-workspace',
    activeWorkspace.data?.defaultModelId ?? 'no-workspace-model',
    activeModel.data?.id ?? 'no-model',
  ].join('|');
  /*
   * 首次进入页面时等上下文就绪再挂 iframe：否则会先按"无模型/无工作区"加载一次，
   * 数据回来后 key 一变又整页重建，用户看到的是两次加载。
   * 查询失败不算"没就绪"——模块自己会按当前上下文请求，宿主不替它拦。
   */
  const contextPending =
    reloadOnContextChange && (activeModel.isPending || activeWorkspace.isPending);

  const src = useMemo(() => {
    if (manifest === null) {
      return null;
    }
    /*
     * 基址可以是模块自己的某个页面（`entryPath`，如 smart-factory 的 `/agents`）。
     * 没声明时落到 entry 本身，行为与从前完全一致。entryPath 由契约限定为同源绝对
     * 路径（不允许 `//host`），解析后不会跑出 `allowedOrigins`。
     *
     * entry 自己的查询串要带过去：那通常是开发服务器的环境开关（`?theme=dark`），
     * 换页面不该把它悄悄丢掉。entryPath 里同名的参数优先（页面自己的意图更具体）。
     */
    const url = entryPath === null ? new URL(manifest.entry) : new URL(entryPath, manifest.entry);
    if (entryPath !== null) {
      for (const [key, value] of new URL(manifest.entry).searchParams) {
        if (!url.searchParams.has(key)) {
          url.searchParams.set(key, value);
        }
      }
    }
    /*
     * 只用 new URL(...).searchParams 拼接，不做字符串相加：
     * entry 本身可能已经带了查询串（很多 dev server 需要 ?foo=bar），
     * 手写 `entry + '?' + x` 会拼出两个问号。
     */
    url.searchParams.set('locale', locale);
    /*
     * 当前能力 —— 同一模块可以挂多个能力（cosight-viewer 既挂「新建对话」又挂「观测」），
     * 模块据此知道自己该渲染哪个页面；声明了 `entryPath` 的模块（smart-factory）用不上它，
     * 但传下去仍然没有害处，将来模块想自选页面也不必改清单。
     *
     * 放在转发宿主查询串**之前**：宿主 URL 上显式给了 `capability` 时以后者为准。
     */
    url.searchParams.set('capability', capability);
    for (const [key, value] of new URLSearchParams(search)) {
      url.searchParams.set(key, value);
    }
    return url.toString();
  }, [manifest, entryPath, locale, search, capability]);

  if (query.isPending || contextPending) {
    return <StatusPanel icon="empty" title={t('module.loading')} role="status" />;
  }

  if (query.isError) {
    return (
      <StatusPanel
        icon="alert"
        role="alert"
        title={t('module.error.title')}
        hint={t('module.error.hint')}
        action={
          <Button
            icon="retry"
            onClick={() => {
              void query.refetch();
            }}
          >
            {t('error.retry')}
          </Button>
        }
      />
    );
  }

  if (manifest === null || src === null) {
    return (
      <StatusPanel
        icon="empty"
        title={t('module.missing.title')}
        hint={t('module.missing.hint')}
      />
    );
  }

  const name = manifest.name[locale];

  return (
    <div className={styles.host}>
      <iframe
        /*
         * key 变化时 React 会销毁旧节点、建新的，浏览器因此重新加载模块。
         * - 开 `reloadOnContextChange` 的能力：按模型/工作区上下文重建；
         * - 对话能力：按「新建对话」nonce 重建（用户已在首页时，导航不会触发重挂载）；
         * - 观测能力：按「观测」导航项 nonce 重建（用户已在观测页时，点击导航回到主页）；
         * - 其它能力：不设 key，行为与之前一致。
         */
        key={
          reloadOnContextChange
            ? contextKey
            : capability === 'conversation'
              ? `conversation-${String(newChatNonce)}`
              : capability === 'observability'
                ? `observability-${String(observabilityReloadNonce)}`
                : undefined
        }
        className={styles.frame}
        src={src}
        title={t('module.frameTitle', { name })}
        /*
         * 最小权限沙箱：
         * - allow-scripts：模块是前端应用，必须能跑；
         * - allow-same-origin：让模块保持**自己的源**（不是宿主的源）。少了它，
         *   模块会变成不透明源，连自己的 localStorage 和 cookie 都读写不了；
         * - allow-forms / allow-popups：模块内的表单提交与"在新窗口打开"；
         * - allow-top-navigation-by-user-activation：模块里**用户主动点**的动作可以整页
         *   回到宿主页面（如 smart-factory 设计页的「返回专家列表」、专家卡片的「使用」）。
         *   只放行"用户激活"这一种：脚本自己发起的顶层跳转照样被挡，工作台不会被模块
         *   悄悄带走。给了它，模块就不必再兜底开新标签。
         * - allow-downloads：模块需要能触发文件下载（如导出会话）。
         * 仍然**不给** allow-top-navigation（无用户激活的顶层跳转）。
         */
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads allow-top-navigation-by-user-activation"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
}
