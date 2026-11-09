/**
 * 评估阶段（智能体创建第三步）：左对话 / 右评估结果，两栏都是真的。
 *
 * 左栏是真会话（`stage = 'evaluation'`，与预览同规则物化）。**从这里进来不会一进来就开跑**：
 * 一轮评估要花几分钟和不少 token，空会话时摆一个「开始评估」按钮，由用户决定
 * 什么时候开始（点下去发的是 `agent-eval` 技能的 slash 命令，见 `evalKickoff.ts`）。
 * 首页「评估智能体」是例外：用户在那里已经按过发送，交接载荷带 `autoSend + newSession`，
 * 到页走的是**和「重新评估」同一个动作** —— 停掉旧一场、重开一场（重建沙箱）再立刻开跑。
 *
 * 「重新评估」= 用生成阶段的最新产物重建评估沙箱 + 新开一场会话 + 立刻开跑，
 * 语义与预览的「重新开始预览」对齐，只是它连开跑一起做了 —— 用户点它就是
 * 为了再跑一轮。重建由服务端做（建会话时带 `resetSandbox`）：该阶段沙箱整个删掉，
 * 上一轮的报告也在里面；右栏同时立刻清空，新会话开好后重拉一次。
 *
 * 右栏经 `useEvalResults` 读 `/evaluations/*` 端点渲染最新一轮报告；run 结束的边沿
 * 由 hook 自己看着 `chat.running` 重拉。
 *
 * 「让助手修复」把未通过的用例交给左侧那场评估会话（见 `AgentCreatePage`），
 * 用户留在当前阶段看它怎么处理。
 */

import { useEffect, useRef } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import { usePresetCommands } from '../../../shared/commands/preset-commands';
import type { ComposerModel } from '../../../shared/components/Composer';
import { Icon } from '../../../shared/components/Icon';
import {
  BootState,
  ConversationPane,
  evaluationBootCopy,
  LinkPill,
} from '../components/ConversationPane';
import { SplitLayout } from '../components/SplitLayout';
import type { SplitWidth } from '../components/SplitLayout';
import { WorkHead } from '../components/WorkHead';
import type { CreationChat } from '../useCreationChat';
import { useEvalResults } from '../useEvalResults';
import { evalKickoffPrompt } from './evalKickoff';
import { EvaluatePanel } from './EvaluatePanel';

/**
 * 首页「评估智能体」带来的「重开一场再开跑」请求（见 AgentCreatePage 的 route replay）。
 *
 * 为什么不在页面 mount 时直接 `restart`：要先打开最近一场评估会话才知道旧的一轮
 * 是不是还在跑（在跑就先停掉），而「重开」还要顺带清右栏的旧报告 —— 这两件事都只有
 * 评估阶段自己看得见。
 */
export interface EvalAutoStart {
  /** 只执行一次：key 变化才算新请求 */
  key: number;
  text: string;
  paths: string[];
}

export function EvaluateStage({
  agentId,
  agentDir,
  chat,
  split,
  onCaseRetry,
  model,
  sendBlockedReason,
  autoStart,
  onAutoStarted,
}: {
  agentId: string;
  /** 智能体产物根（Agent.dir）；评估沙箱是它下面的 evaluation/ */
  agentDir: string | null;
  chat: CreationChat;
  split: SplitWidth;
  onCaseRetry?: (task: string) => void;
  model?: ComposerModel;
  /** 没有可用模型等外部条件挡住发送的原因 */
  sendBlockedReason?: string | null;
  /** 首页「评估智能体」的自动重开请求；没有就是 null */
  autoStart?: EvalAutoStart | null;
  /**
   * 请求已经执行：页面据此把它清掉。
   *
   * 不清的话，切去别的阶段再切回来（阶段组件重新挂载、ref 归零）会把同一轮评估
   * 再重开一次。
   */
  onAutoStarted?: () => void;
}) {
  const { t } = useI18n();
  /** `/` 词表走前端预设（与首页 / 生成同源）：这里最常用的是 `/goldeval:agent-eval` */
  const commands = usePresetCommands();
  const results = useEvalResults(agentId, chat.running, chat.session?.id ?? '');

  /**
   * 首页带来的一轮评估：**不复用旧会话**，等旧的一轮停稳后重开一场（重建沙箱）再开跑。
   *
   * 顺序不能省：
   *   1. 一进来就清右栏 —— 旧报告马上会被服务端随沙箱删掉；
   *   2. 等最近一场会话打开（`phase === 'ready'`）才知道它是不是还在跑；
   *   3. 在跑就先 `stop`，等 run 到终态（`running` 变 false）再重开 ——
   *      同阶段还有活跃 run 时服务端建会话会回 409，抢跑只会退回旧会话。
   */
  const autoStartedRef = useRef(0);
  const autoResetRef = useRef(0);
  const autoStoppedRef = useRef(0);
  useEffect(() => {
    if (autoStart === null || autoStart === undefined) return;
    if (autoStartedRef.current === autoStart.key) return;

    if (autoResetRef.current !== autoStart.key) {
      autoResetRef.current = autoStart.key;
      results.reset();
    }

    if (chat.link.phase !== 'ready') return;
    if (chat.running) {
      // 停止只发一次：effect 会跟着 running / 渲染反复进来
      if (autoStoppedRef.current !== autoStart.key) {
        autoStoppedRef.current = autoStart.key;
        chat.stop();
      }
      return;
    }

    autoStartedRef.current = autoStart.key;
    chat.restart(autoStart.text, autoStart.paths);
    onAutoStarted?.();
  }, [autoStart, chat, results.reset, chat.link.phase, chat.running, onAutoStarted]);

  /*
   * 重开的前提与预览一致：会话就绪、通道已连、没有正在跑的一轮，
   * 且没有「没有可用模型」这类外部阻塞。另加一条：没有可用模型时新会话也跑不起来。
   */
  const canRestart =
    (sendBlockedReason ?? null) === null &&
    chat.link.conn === 'ready' &&
    chat.link.phase === 'ready' &&
    !chat.running;

  return (
    <SplitLayout
      split={split}
      left={
        <ConversationPane
          chat={chat}
          title={t('create.evaluation.sessionTitle')}
          status={
            <span className="ac-head-actions">
              <button
                type="button"
                className="ac-restart"
                disabled={!canRestart}
                onClick={() => {
                  // 先清右栏：旧报告马上会被服务端随沙箱一起删掉，不该继续摆在眼前
                  results.reset();
                  chat.restart(evalKickoffPrompt());
                }}
                title={t('create.evaluation.restartTitle')}
              >
                <Icon name="refresh" size={12} />
                {t('create.evaluation.restart')}
              </button>
              <LinkPill link={chat.link} />
            </span>
          }
          empty={
            <EvaluateStart chat={chat} sendBlockedReason={sendBlockedReason} />
          }
          placeholder={t('create.evaluation.placeholder')}
          model={model}
          commands={commands}
          sendBlockedReason={sendBlockedReason}
        />
      }
      right={
        <>
          <WorkHead
            title={t('create.evaluation.title')}
            desc={t('create.evaluation.desc')}
            dir={agentDir === null ? t('create.production.dirLoading') : `${agentDir}/evaluation`}
            skill="agent-eval"
          />
          <EvaluatePanel
            agentId={agentId}
            report={results.report}
            cases={results.cases}
            loading={results.loading}
            error={results.error}
            running={chat.running}
            onCaseRetry={onCaseRetry ?? (() => {})}
          />
        </>
      }
    />
  );
}

/**
 * 空会话时左栏摆什么。
 *
 * 准备期间仍是原来的连接 / 准备态；**就绪后不是直接开跑，而是给一个「开始评估」**——
 * 一轮评估要花几分钟、烧不少 token，用户应该自己按下开始。同一张卡也解释了
 * 这一轮会做什么，免得点下去不知道在等什么。
 */
function EvaluateStart({
  chat,
  sendBlockedReason,
}: {
  chat: CreationChat;
  sendBlockedReason?: string | null;
}) {
  const { t } = useI18n();
  const ready = chat.link.conn === 'ready' && chat.link.phase === 'ready';
  if (!ready) return <BootState link={chat.link} copy={evaluationBootCopy(t)} />;

  const blocked = sendBlockedReason ?? null;
  const canStart = blocked === null && !chat.running;

  return (
    <div className="ac-boot">
      <Icon name="gauge" size={22} />
      <p className="ac-boot-title">{t('create.evaluation.startTitle')}</p>
      <p className="ac-boot-desc">{t('create.evaluation.startDesc')}</p>
      <button
        type="button"
        className="ac-btn ac-btn--primary"
        disabled={!canStart}
        onClick={() => chat.send({ text: evalKickoffPrompt(), attachments: [] })}
      >
        {t('create.evaluation.start')}
      </button>
      {blocked !== null && <p className="ac-boot-desc">{blocked}</p>}
    </div>
  );
}
