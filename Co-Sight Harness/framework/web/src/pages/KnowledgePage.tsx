/**
 * 知识库页（路由 `/knowledge`，直接访问时的内嵌视图）。
 *
 * 页面内容**不是**框架自己的界面，而是用户在「设置 → 知识库路由设置」里配的
 * 那个地址：这里把它嵌进主面板，用户留在工作台内就能看。
 *
 * 注意侧栏「知识库」**不再**进这条路由：它在新的浏览器标签页里直接打开配置的
 * 地址（见 `components/shell/KnowledgeNavItem`）。本页仍保留给直接输入地址、
 * 旧书签以及导航表一致性测试——去掉它会让 `NAV_ITEMS` 里的 `/knowledge` 变成死链。
 *
 * 三种状态与其它宿主页一致：
 * - 读取中 → 加载态；
 * - 读取失败 → 错误 + 重试（不能当成"没配置"）；
 * - 没有可用路由 → 空态 + 直接去设置里新增（同样是"点一下就到"，不绕路）。
 *
 * 框架**不探测**地址是否可达：拿用户填的地址去服务端请求就是一条 SSRF 路径。
 * 打不开时 iframe 里是对方站点自己的错误页，这也是它的真实状态。
 */

import { useActiveRagKnowledge } from '../api/ragKnowledge';
import { useApiErrorMessage } from '../api/useApiErrorMessage';
import { Button } from '../components/ui/Button';
import { StatusPanel } from '../components/ui/StatusPanel';
import { useI18n } from '../i18n/useI18n';
import { useUiStore } from '../stores/ui';
import styles from '../components/module/embedFrame.module.css';

export function KnowledgePage() {
  const { t } = useI18n();
  const describeError = useApiErrorMessage();
  const active = useActiveRagKnowledge();
  const openSettings = useUiStore((state) => state.openSettings);

  if (active.isPending) {
    return <StatusPanel icon="empty" title={t('knowledgeRoute.loading')} role="status" />;
  }

  if (active.isError) {
    return (
      <StatusPanel
        icon="alert"
        role="alert"
        title={t('knowledgeRoute.loadFailedTitle')}
        hint={describeError(active.error)}
        action={
          <Button
            icon="retry"
            onClick={() => {
              void active.refetch();
            }}
          >
            {t('error.retry')}
          </Button>
        }
      />
    );
  }

  const base = active.data ?? null;
  if (base === null) {
    return (
      <StatusPanel
        icon="empty"
        title={t('knowledgeRoute.missingTitle')}
        hint={t('knowledgeRoute.missingHint')}
        action={
          <Button
            onClick={() => {
              openSettings('ragKnowledge', { create: true });
            }}
          >
            {t('knowledgeRoute.openSettings')}
          </Button>
        }
      />
    );
  }

  return (
    <div className={styles.host}>
      <iframe
        className={styles.frame}
        src={base.routeUrl}
        title={t('knowledgeRoute.frameTitle', { name: base.name })}
        /*
         * 与 `ModuleHost` 同一套最小权限：知识库界面是独立前端，要能跑脚本、保住
         * 自己的源（localStorage / cookie）、提交表单、开新窗口、下载文件；整页跳转
         * 只放行用户主动点击的那一种。这里不给 `allow-top-navigation`。
         */
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads allow-top-navigation-by-user-activation"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
}
