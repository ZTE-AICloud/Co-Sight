/**
 * 模块接入信息卡（模型设置面板底部）。
 *
 * 存在的理由：模块面接口（`/api/framework/v1/models`）是**唯一**能把明文密钥交给
 * 本机其他进程的口子，而"怎么接"这件事此前只写在服务端代码和文档里。模块作者在
 * 界面上看不到它、也就不会去翻文档，结果就是继续往 `.env` 里手抄一份密钥——
 * 既容易过期，又把密钥散到了第二个地方。
 *
 * 三件事说得非常明确，因为它们都会被误解：
 * 1. 令牌在**哪个文件**（路径要具体到 `$COSIGHT_HOME` 下，而不是"某个配置里"）；
 * 2. 令牌**不能**放进环境变量（`claude-adapter` 那类适配器会把 `process.env`
 *    整体透传给子进程，等于交给 LLM 工具链）——原话是"让模块进程自己读文件"；
 * 3. 模块面**可读也可写**（D33 之后补上了增删改），但**只读的消费方不该顺手要写权限**
 *    ——令牌泄漏的代价因此从"配置被读走"变成"配置被改掉"，这句话得在界面上说出来，
 *    否则模块作者只会照着接口清单一路调下去。
 *
 * 数据来源都是现成的：接口基址取 `window.location.origin`，令牌路径取
 * `GET /api/health` 的 `cosightHome`。**不新增接口**——这块信息不值得让服务端
 * 再暴露一个"我是谁"的端点。
 */

import { useState } from 'react';

import { useHealth } from '../../api/system';
import { copyText } from '../../lib/copyText';
import { useI18n } from '../../i18n/useI18n';
import { Button } from '../../components/ui/Button';
import styles from '../config/config.module.css';

/** 模块面路径。与 `framework/server/src/app.ts` 的注册前缀、`MODULE_FACE_BASE_PATH` 对应。 */
const MODULE_FACE_PATH = '/api/framework/v1/models';

/** 令牌文件名。与 `framework/server/src/config/paths.ts` 的 `MODULE_TOKEN_FILE_NAME` 对应。 */
const TOKEN_FILE_NAME = '.module-token';

/**
 * 接口基址取当前页面的 origin，**开发态与生产态都成立**：
 * 生产态前端由服务端同源托管（origin 就是后端）；开发态前端在 4310，但 Vite 把
 * `/api` 代理到 4300，且代理不改 `Host`（`changeOrigin: false`），
 * 于是后端看到的仍是 `localhost` —— 正好过得了模块面的回环校验。
 */
function useModuleFaceBase(): string {
  const origin = typeof window === 'undefined' ? '' : window.location.origin;
  return `${origin}${MODULE_FACE_PATH}`;
}

/** 一段可复制的等宽文本 + 一个复制按钮。复制失败时改成"请手动选中"。 */
function Copyable({ text, label }: { text: string; label: string }) {
  const { t } = useI18n();
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  return (
    <div className={styles.copyRow}>
      <code className={styles.code} title={text}>
        {text}
      </code>
      <Button
        size="sm"
        aria-label={t('settings.model.moduleAccess.copyAriaLabel', { label })}
        onClick={() => {
          void copyText(text).then((ok) => {
            setState(ok ? 'copied' : 'failed');
          });
        }}
      >
        {state === 'failed'
          ? t('settings.model.moduleAccess.copyFailed')
          : state === 'copied'
            ? t('settings.model.moduleAccess.copied')
            : t('settings.model.moduleAccess.copy')}
      </Button>
    </div>
  );
}

/**
 * 展开后的内容。
 *
 * 单独一个组件是为了让 `useHealth()` 只在展开时才挂载——**折叠状态不发请求**。
 * 这块信息绝大多数用户一辈子不会展开，而设置弹窗每打开一次就多一次 `/api/health`
 * 是没必要的（虽然它通常命中缓存，但"打开列表"这件事本身不该依赖另一个查询的缓存状态）。
 */
function ModuleAccessBody() {
  const { t } = useI18n();
  const health = useHealth();
  const base = useModuleFaceBase();

  /*
   * `cosightHome` 拿不到时**不编一个默认值**（如 `~/.cosight-harness`）：用户把
   * `COSIGHT_HOME` 配到别处时，一个看着合理的默认路径比"暂时读不到"危险得多——
   * 他会照着它去找一个不存在的文件。
   */
  const cosightHome = health.data?.cosightHome;
  const tokenPath =
    cosightHome === undefined ? null : `${cosightHome}/${TOKEN_FILE_NAME}`;

  const curl = [
    `# 令牌从文件读，不要写进 .env（模块进程的环境会被透传给子进程）`,
    `TOKEN=$(cat ${tokenPath ?? '$COSIGHT_HOME/.module-token'})`,
    `curl -H "Authorization: Bearer $TOKEN" ${base}/active`,
  ].join('\n');

  return (
    <>
      <p className={styles.extraHint}>{t('settings.model.moduleAccess.intro')}</p>

      <dl className={styles.extraList}>
        <dt className={styles.extraTerm}>{t('settings.model.moduleAccess.baseUrl')}</dt>
        <dd className={styles.extraValue}>
          <Copyable text={base} label={t('settings.model.moduleAccess.baseUrl')} />
        </dd>

        <dt className={styles.extraTerm}>{t('settings.model.moduleAccess.tokenFile')}</dt>
        <dd className={styles.extraValue}>
          {tokenPath === null ? (
            t('settings.model.moduleAccess.tokenFileUnknown')
          ) : (
            <Copyable text={tokenPath} label={t('settings.model.moduleAccess.tokenFile')} />
          )}
        </dd>
      </dl>

      <ul className={styles.notes}>
        <li>{t('settings.model.moduleAccess.scope')}</li>
        <li>{t('settings.model.moduleAccess.notEnv')}</li>
        <li>{t('settings.model.moduleAccess.localOnly')}</li>
      </ul>

      <p className={styles.extraHint}>{t('settings.model.moduleAccess.curlHint')}</p>
      <pre className={styles.pre}>{curl}</pre>
    </>
  );
}

export function ModuleAccessCard() {
  const { t } = useI18n();
  /*
   * 自己跟踪展开状态，而不是让 `<details>` 全权负责：原生 `<details>` 的**内容
   * 始终在 DOM 里**（只是被隐藏），里面的 `useHealth()` 照样会发请求。要"折叠时
   * 不请求"就必须知道展开与否，而 `onToggle` 给出的正是这个信号——不需要自己接管
   * 展开动画或键盘行为，那些仍由浏览器负责。
   */
  const [open, setOpen] = useState(false);

  return (
    <details
      className={styles.disclosure}
      open={open}
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
    >
      <summary className={styles.disclosureSummary}>
        {t('settings.model.moduleAccess.title')}
      </summary>
      {open ? <ModuleAccessBody /> : null}
    </details>
  );
}
