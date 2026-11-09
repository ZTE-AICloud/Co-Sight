/**
 * 技能工坊（`/workshop`）：技能线的唯一工作台。
 *
 * 这一页**没有目标条**：创建与优化都是同一场对话，区别只在首条消息怎么拼
 * （`compose-prompt.ts`）。从哪个入口进来只影响首条与会话名。
 *
 * 版式与数据来源见 `docs/capability-routing.md` §3：
 *   - 顶栏：回技能库 / 通道状态 / 历史 / 新会话；
 *   - 主体：`Conversation`（与设计页同一个组件，折叠、审批卡、续页都在里面）；
 *   - 抽屉：按 cwd 拉的历史会话。
 *
 * 入口：
 *   首页「创建技能」      → `/workshop`（`location.state` 带首轮正文，自动发出）
 *   首页「技能优化」    → `/workshop?target=…&name=…` + 首轮正文（自动发出）
 *   技能库卡「优化」      → `/workshop?target=…&name=…`（等用户自己写）
 *   技能库卡「历史」      → 在技能库里开抽屉（按 `优化 <name>` 筛），点会话后带 `?session=` 进来
 *   智能体技能的「优化」  → 设计页（`state.replay`），不落这里
 *
 * **新会话不在本页起**：顶栏那颗「新会话」回首页（预选「创建技能」）。新会话要先有
 * 意图（创建，还是优化哪个技能），那是首页四张能力卡的事；工坊只承接已经发起的那场。
 *
 * 会话生命周期：**第一次发送时才建会话**（首页已经点过发送的那种算第一次）。
 * 进展与守卫见 `useWorkshopSession.ts`。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { msg, useI18n } from '../../i18n/useI18n';
import { sessionsApi } from '../../shared/api/sessions';
import type { Session } from '../../shared/api/sessions';
import { skillsApi } from '../../shared/api/skills';
import type { SkillsResponse, Skill } from '../../shared/api/skills';
import type { ComposerFill } from '../../shared/components/Composer';
import { attachmentOfPath } from '../../shared/components/Composer';
import { Conversation } from '../../shared/components/Conversation/Conversation';
import { useFilePicker } from '../../shared/components/FilePicker';
import { FilePreviewPanel } from '../../shared/components/FilePreview/FilePreviewPanel';
import {
  FilePreviewProvider,
  useFilePreviewState,
} from '../../shared/components/FilePreview/FilePreviewProvider';
import { Icon } from '../../shared/components/Icon';
import type { LiveState } from '../../shared/live/live-client';
import { useWorkspaces } from '../../shared/api/useWorkspaces';
import { HistoryDrawer } from './components/HistoryDrawer';
import { SkillFilesPanel } from './components/SkillFilesPanel';
import { useWorkshopSession } from './useWorkshopSession';
import type { WorkshopPhase, WorkshopSeed } from './useWorkshopSession';
import './skill-workshop.css';

/** 首页 `navigate('/workshop', { state })` 的形状（只这两项会被工坊消费） */
interface WorkshopLocationState {
  firstPrompt?: string;
  attachments?: string[];
}

const SKILLS_TAB = '/agents?tab=skills';

export function WorkshopPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const workspace = useWorkspaces();

  /* ---------- 技能库：拿到 cwd + 解析 ?target= ---------- */

  const [skills, setSkills] = useState<SkillsResponse | null>(null);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [skillsError, setSkillsError] = useState<string | null>(null);
  /** 「重试」换一代，让下面的取数 effect 再跑一次 */
  const [skillsNonce, setSkillsNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setSkillsLoading(true);
    setSkillsError(null);
    skillsApi
      .list(workspace.workspace?.id)
      .then((result) => {
        if (!cancelled) setSkills(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setSkillsError(describeError(cause));
      })
      .finally(() => {
        if (!cancelled) setSkillsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [skillsNonce, workspace.workspace?.id]);

  const cwd = skills?.cwd ?? null;

  const targetPath = searchParams.get('target');
  const targetName = searchParams.get('name') ?? '';
  /** 优化目标：只认库技能；智能体技能不进工坊（它们的优化落设计页） */
  const target = useMemo<Skill | null>(() => {
    if (targetPath === null || skills === null) return null;
    return (
      skills.items.find((item) => item.path === targetPath && item.source === 'library') ?? null
    );
  }, [skills, targetPath]);

  const mode = targetPath === null ? 'create' : 'optimize';
  /** 地址里的 `?session=` */
  const preferredSessionId = searchParams.get('session');

  /* ---------- 页面级提示（技能不存在、会话无效等） ---------- */

  const [pageNotice, setPageNotice] = useState<string | null>(null);
  /** 顶栏「历史」抽屉。技能库的「工坊历史」入口已经在库那一页开抽屉，不再跳进来挑会话 */
  const [historyOpen, setHistoryOpen] = useState(false);

  /* ---------- 首页带过来的首轮内容 ---------- */

  /**
   * **有 state = 首页已经按过发送**（技能卡片上的「优化」不带 state，那是让用户自己写）。
   * 正文允许为空：优化场「只选了技能、没写要求」本身就是一次完整的发送，命令与技能
   * 路径由页面拼，不能到了工坊再把这句话退回去让用户补一句。空正文能不能真的发出去
   * 由 `useWorkshopSession` 按入口判定（创建场空正文不算一次发送）。
   */
  const seed = useMemo<WorkshopSeed | null>(() => {
    const state = location.state as WorkshopLocationState | null;
    if (state === null) return null;
    return { firstPrompt: state.firstPrompt ?? '', attachments: state.attachments ?? [] };
    // 每次导航换一个 key；state 是导航载荷，不随渲染变
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.key]);

  const updateParams = useCallback(
    (mutate: (next: URLSearchParams) => void, replace = true) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          mutate(next);
          return next;
        },
        { replace },
      );
    },
    [setSearchParams],
  );

  const chat = useWorkshopSession({
    cwd,
    seed,
    preferredSessionId,
    mode,
    target,
    workspaceId: workspace.workspace?.id,
    startSettled: !workspace.loading,
    startBlockedReason:
      workspace.workspace === null && !workspace.loading
        ? workspace.error !== null
          ? t('workshop.blocked.workspaceError')
          : t('workshop.blocked.workspaceNone')
        : null,
    onSessionOpened: (sessionId) => {
      updateParams((next) => next.set('session', sessionId));
    },
    onSessionInvalid: () => {
      updateParams((next) => next.delete('session'));
    },
  });

  /* ---------- 裸进页面：找出还在跑的会话 ---------- */

  /**
   * 没有 `?session=`、也不是首页带首轮进来时，本页不会自动打开任何会话。
   * 但关掉页面**不会**中断服务端的 run（WS 断开只退订）；真正缺的是把它找回来的入口。
   * 所以这里按 cwd 捞一次 `in_progress`，有就摆一条「继续这场」。
   *
   * 只在创建场找：优化场的目标会话由技能卡的「历史」按名字筛，混进来反而会指错那场。
   * 查询失败静默 —— 这只是提示，不挡发送（发送侧有自己的错误条）。
   */
  const [runningSessions, setRunningSessions] = useState<Session[]>([]);
  const [runningDismissed, setRunningDismissed] = useState(false);

  useEffect(() => {
    if (cwd === null || preferredSessionId !== null || seed !== null || targetPath !== null) {
      setRunningSessions([]);
      return;
    }
    let cancelled = false;
    sessionsApi
      .list({ cwd, stage: 'development', status: 'in_progress', pageSize: 5 })
      .then((result) => {
        if (!cancelled) setRunningSessions(result.items);
      })
      .catch(() => {
        if (!cancelled) setRunningSessions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [cwd, preferredSessionId, seed, targetPath]);

  const firstRunning = runningSessions[0] ?? null;
  const firstRunningName =
    firstRunning === null
      ? ''
      : firstRunning.name === ''
        ? t('workshop.history.untitled')
        : firstRunning.name;

  const notify = useCallback((text: string) => setPageNotice(text), []);
  const notice = pageNotice ?? chat.notice;
  const dismissNotice = useCallback(() => {
    setPageNotice(null);
    chat.dismissNotice();
  }, [chat]);

  /**
   * 切会话的闸只剩「正在准备会话」这一段：建会话 + 发首轮还在路上时切走，
   * 这一轮会发到切过去的会话上。
   *
   * 跑着一轮**不挡**：那一轮在服务端照常跑完，回来时 `openSession` 会重拉消息与 run；
   * 旧会话的帧已由 `useLiveSession` 按 `sessionId` 滤掉，混不进当前这一场。
   */
  const switchingBlocked = chat.phase === 'preparing';

  /*
   * `?target=` 指向的技能已经不在库里：退回创建场语义，不把失效的绝对路径拼进 prompt。
   * 等 `skills` 落定才判 —— 加载中时 target 本来就还是 null。
   */
  useEffect(() => {
    if (targetPath === null || skills === null || target !== null) return;
    notify(t('workshop.notice.targetMissing'));
    updateParams((next) => {
      next.delete('target');
      next.delete('name');
    });
  }, [notify, skills, t, target, targetPath, updateParams]);

  /* ---------- 右侧技能库文件：一轮对话结束后重拉 ---------- */

  /** 技能库没有订阅：`running` 由 true 落到 false 才算一轮结束，给文件树一个重拉信号 */
  const [filesRefresh, setFilesRefresh] = useState(0);
  const wasRunningRef = useRef(false);
  useEffect(() => {
    if (wasRunningRef.current && !chat.running) {
      setFilesRefresh((current) => current + 1);
    }
    wasRunningRef.current = chat.running;
  }, [chat.running]);

  /* ---------- 发送侧：外部阻塞原因 ---------- */

  const workspaceBlocked =
    workspace.workspace === null
      ? workspace.loading
        ? t('workshop.blocked.workspaceLoading')
        : workspace.error !== null
          ? t('workshop.blocked.workspaceError')
          : t('workshop.blocked.workspaceNone')
      : null;

  const skillsBlocked =
    cwd === null
      ? skillsLoading
        ? t('workshop.blocked.skillsLoading')
        : t('workshop.blocked.skillsError')
      : null;

  // 连不上 / 正在准备 / 准备失败都挡住发送：通道断了发不出去，准备中建不了会话
  const phaseBlocked =
    chat.conn !== 'ready'
      ? t('workshop.link.connecting')
      : chat.phase === 'preparing'
        ? t('workshop.link.preparing')
        : chat.phase === 'failed'
          ? t('workshop.link.failed')
          : null;

  const sendBlockedReason =
    phaseBlocked ?? workspaceBlocked ?? skillsBlocked ?? chat.modelBlockedReason;

  /* ---------- 空态示例 → 填进发送框 ---------- */

  const [fill, setFill] = useState<ComposerFill | null>(null);
  const fillSeq = useRef(0);
  const pickSample = useCallback((text: string) => {
    fillSeq.current += 1;
    setFill({ key: fillSeq.current, text });
  }, []);

  /* ---------- 附件选择器 ---------- */

  const picker = useFilePicker();
  const pickFile = useCallback(async () => {
    const path = await picker.pickFile();
    return path === null ? null : attachmentOfPath(path);
  }, [picker.pickFile]);

  /* ---------- 文件预览（对话里的产物路径可点开） ---------- */

  const filePreview = useFilePreviewState(cwd);

  /* ---------- 动作 ---------- */

  /** 顶栏「历史」：只看本目录的全部会话；按技能筛选的入口在技能库的抽屉里 */
  const openHistory = useCallback(() => setHistoryOpen(true), []);
  const closeHistory = useCallback(() => setHistoryOpen(false), []);

  /**
   * 「新会话」= 回首页重新发起，不在这里就地清空。
   *
   * 新会话要先答「创建还是优化哪个技能」，那是首页四张能力卡在做的事；工坊只承接
   * 已经发起的那一场。预选「创建技能」：从技能线回去的下一步通常是再做一个技能，
   * 想优化的话在首页换一颗 chip 就行。
   */
  const newSession = useCallback(() => {
    if (switchingBlocked) {
      notify(t('workshop.notice.preparing'));
      return;
    }
    navigate('/', { state: { capability: 'skill.create' } });
  }, [navigate, notify, switchingBlocked, t]);

  const backToSkills = useCallback(() => navigate(SKILLS_TAB), [navigate]);

  const restore = useCallback(
    async (sessionId: string) => {
      if (switchingBlocked) {
        notify(t('workshop.notice.preparing'));
        return;
      }
      const ok = await chat.open(sessionId);
      if (!ok) return;
      setHistoryOpen(false);
      updateParams((next) => {
        next.set('session', sessionId);
      });
    },
    [chat, notify, switchingBlocked, t, updateParams],
  );

  const handleCurrentDeleted = useCallback(() => {
    chat.reset();
    updateParams((next) => next.delete('session'));
    notify(t('workshop.notice.deleted'));
  }, [chat, notify, t, updateParams]);

  const empty = (
    <WorkshopEmpty mode={mode} targetName={target?.name ?? targetName} onPick={pickSample} />
  );

  return (
    <FilePreviewProvider value={filePreview}>
      <div className="sw-page">
        <header className="sw-top">
          <div className="sw-top-lead">
            <button type="button" className="sw-icon-btn" title={t('workshop.back')} onClick={backToSkills}>
              <Icon name="arrowLeft" size={16} />
            </button>
            <div className="sw-title">
              <h1>{t('workshop.title')}</h1>
              <p>{t('workshop.subtitle')}</p>
            </div>
          </div>

          <div className="sw-top-actions">
            <LinkPill phase={chat.phase} conn={chat.conn} connDetail={chat.connDetail} onRetry={chat.retry} />
            <button
              type="button"
              className="sw-btn"
              disabled={cwd === null}
              onClick={openHistory}
            >
              <Icon name="clock" size={13} />
              {t('workshop.history.short')}
            </button>
            <button
              type="button"
              className="sw-btn"
              title={switchingBlocked ? t('workshop.notice.preparing') : t('workshop.newSessionHint')}
              onClick={newSession}
            >
              <Icon name="plus" size={13} />
              {t('workshop.newSession')}
            </button>
          </div>
        </header>

        {firstRunning !== null && !runningDismissed && chat.session === null && (
          <div className="sw-notice" role="status">
            <Icon name="clock" size={14} />
            <span>
              {t('workshop.running.body', { name: firstRunningName })}
              {runningSessions.length > 1 &&
                ` ${t('workshop.running.more', { count: runningSessions.length - 1 })}`}
            </span>
            <button
              type="button"
              className="sw-btn"
              onClick={() => void restore(firstRunning.id)}
            >
              {t('workshop.running.continue')}
            </button>
            <button
              type="button"
              className="sw-notice-close"
              title={t('workshop.running.close')}
              onClick={() => setRunningDismissed(true)}
            >
              <Icon name="close" size={14} />
            </button>
          </div>
        )}

        {notice !== null && (
          <div className="sw-notice" role="status">
            <Icon name="alert" size={14} />
            <span>{notice}</span>
            <button type="button" className="sw-notice-close" title={t('common.close')} onClick={dismissNotice}>
              <Icon name="close" size={14} />
            </button>
          </div>
        )}

        {skillsError !== null && cwd === null && (
          <div className="sw-error" role="alert">
            <Icon name="alert" size={14} />
            <span>
              {t('workshop.blocked.skillsError')} —— {skillsError}
            </span>
            <button type="button" className="sw-btn" onClick={() => setSkillsNonce((value) => value + 1)}>
              {t('workshop.retry')}
            </button>
          </div>
        )}

        {chat.phase === 'failed' && chat.error !== null && (
          <div className="sw-error" role="alert">
            <Icon name="alert" size={14} />
            <span>{chat.error}</span>
            <button type="button" className="sw-btn" onClick={chat.retry}>
              {t('workshop.retry')}
            </button>
          </div>
        )}

        <div className="sw-body">
          <Conversation
            className="sw-conversation"
            messages={chat.messages}
            running={chat.running}
            onSend={chat.send}
            onStop={chat.stop}
            hasOlder={chat.hasOlder}
            loadingOlder={chat.loadingOlder}
            onLoadOlder={chat.loadOlder}
            onApproval={chat.respondApproval}
            onAnswers={chat.respondAnswers}
            title={null}
            empty={empty}
            composerProps={{
              placeholder:
                mode === 'optimize'
                  ? t('workshop.placeholder.optimize', { name: target?.name ?? targetName })
                  : t('workshop.placeholder.create'),
              status: chat.running ? t('workshop.generating') : undefined,
              model: chat.model,
              sendBlockedReason,
              pickFile,
              fill,
              replay: chat.replay,
            }}
          />

          <SkillFilesPanel
            root={skills?.root ?? null}
            loading={skillsLoading}
            error={skillsError}
            refreshSignal={filesRefresh}
          />
        </div>

        {historyOpen && cwd !== null && (
          <HistoryDrawer
            cwd={cwd}
            currentSessionId={chat.session?.id ?? null}
            filter={null}
            busy={switchingBlocked}
            onClose={closeHistory}
            onOpen={(session) => void restore(session.id)}
            onCurrentDeleted={handleCurrentDeleted}
          />
        )}

        {/* 文件选择器自己带 dialog，关闭时不渲染 */}
        {picker.element}
      </div>

      <FilePreviewPanel />
    </FilePreviewProvider>
  );
}

/* ---------- 空态 ---------- */

function WorkshopEmpty({
  mode,
  targetName,
  onPick,
}: {
  mode: 'create' | 'optimize';
  targetName: string;
  onPick: (text: string) => void;
}) {
  const { t } = useI18n();
  const samples =
    mode === 'optimize'
      ? [
          { label: t('workshop.empty.optimizeSample1Label'), text: t('workshop.empty.optimizeSample1') },
          { label: t('workshop.empty.optimizeSample2Label'), text: t('workshop.empty.optimizeSample2') },
          { label: t('workshop.empty.optimizeSample3Label'), text: t('workshop.empty.optimizeSample3') },
        ]
      : [
          { label: t('workshop.empty.createSample1Label'), text: t('workshop.empty.createSample1') },
          { label: t('workshop.empty.createSample2Label'), text: t('workshop.empty.createSample2') },
          { label: t('workshop.empty.createSample3Label'), text: t('workshop.empty.createSample3') },
        ];

  return (
    <div className="sw-empty">
      <span className="sw-empty-icon">
        <Icon name={mode === 'create' ? 'wand' : 'sparkle'} size={22} />
      </span>
      <h2>
        {mode === 'create'
          ? t('workshop.empty.createTitle')
          : t('workshop.empty.optimizeTitle', { name: targetName })}
      </h2>
      <p>
        {mode === 'create'
          ? t('workshop.empty.createDesc')
          : t('workshop.empty.optimizeDesc', { name: targetName })}
      </p>
      <div className="sw-empty-samples">
        {samples.map((sample) => (
          <button key={sample.label} type="button" onClick={() => onPick(sample.text)}>
            <strong>{sample.label}</strong>
            <span>{sample.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ---------- 通道状态 ---------- */

/**
 * 与设计页的 `LinkPill` 同语义：连不上却写「在线」会让用户以为丢消息是自己的问题。
 *
 * 文案分四档：连接中 / 准备会话 / 已连接 / 连不上（给一个重连入口）。
 */
function LinkPill({
  phase,
  conn,
  connDetail,
  onRetry,
}: {
  phase: WorkshopPhase;
  conn: LiveState;
  connDetail: string | undefined;
  onRetry: () => void;
}) {
  const { t } = useI18n();

  if (phase === 'failed') {
    return (
      <span className="sw-link sw-link--bad" title={connDetail}>
        <Icon name="alert" size={12} />
        {t('workshop.link.failed')}
        <button type="button" className="sw-link-retry" onClick={onRetry}>
          {t('workshop.link.retry')}
        </button>
      </span>
    );
  }

  if (conn !== 'ready' || phase === 'connecting' || phase === 'preparing') {
    return (
      <span className="sw-link sw-link--wait">
        <span className="sw-link-dot" />
        {conn !== 'ready' ? t('workshop.link.connecting') : t('workshop.link.preparing')}
      </span>
    );
  }

  return (
    <span className="sw-link sw-link--ok">
      <span className="sw-link-dot" />
      {t('workshop.link.ready')}
    </span>
  );
}

/* ---------- 错误描述 ---------- */

function describeError(cause: unknown): string {
  if (cause instanceof Error) return cause.message;
  return msg('common.unknownError');
}
