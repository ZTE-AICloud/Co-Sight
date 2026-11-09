import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { msg, useI18n } from '../../i18n/useI18n';
import type { MessageKey, MessageParams } from '../../i18n/types';
import { backendDownHint, agentsApi, isBackendDown } from '../../shared/api/agents';
import type { Agent, AgentDetail } from '../../shared/api/agents';
import type { KnowledgeWorkflow } from '../../shared/api/knowledge';
import { useKnowledgeWorkflow } from '../../shared/api/useKnowledgeWorkflow';
import { composeKnowledgeRebuildPrompt } from '../../shared/commands/harness-prompt';
import { ApiError } from '../../shared/api/client';
import { modelBlockReason, sessionModelBlockReason, useModels } from '../../shared/api/useModels';
import { AgentAvatar } from '../../shared/components/AgentAvatar';
import type { ComposerModel } from '../../shared/components/Composer';
import { FilePreviewPanel } from '../../shared/components/FilePreview/FilePreviewPanel';
import {
  FilePreviewProvider,
  useFilePreviewState,
} from '../../shared/components/FilePreview/FilePreviewProvider';
import { Icon } from '../../shared/components/Icon';
import { frameworkExpertsUrl, leaveToFramework } from '../../shared/framework';
import { useSplitWidth } from './components/SplitLayout';
import { stageTabs } from './stage-meta';
import { EvaluateStage } from './stages/EvaluateStage';
import type { EvalAutoStart } from './stages/EvaluateStage';
import { PreviewStage } from './stages/PreviewStage';
import { ProductionStage } from './stages/ProductionStage';
import { useCreationChat } from './useCreationChat';
import type { CreationSeed } from './useCreationChat';
import { useProductionGate } from './useProductionGate';
import type { ProductionGate } from './useProductionGate';
import type { StageId } from './types';
import './agent-create.css';

/**
 * 智能体设计页（`/agents/:agentId/design`）。
 *
 * 外壳只做四件事：顶栏身份、三阶段步骤条、一场实时连接（`useCreationChat`）、
 * 根据当前阶段渲染对应的 `stages/*Stage.tsx`。**不在这里写任何阶段的布局与文案** ——
 * 生成有分栏，预览只有居中对话，评估是分栏 + 演示结果，这些差异归各自的 Stage。
 *
 * 顶栏只有身份与返回，**没有动作按钮**（原因见下方 header 处的注释）。
 *
 * ── 从地址直接落到某个阶段 ────────────────────────────────────────────────
 * `?stage=preview` / `?stage=evaluation` 让这一页**进来就停在那个阶段**，
 * 卡底「评估」就是这么落过来的（`AgentListPage.openEvaluate`）—— 那个页面本来
 * 就是「围着这个专家的 run 转」，换个入口不必再手点一次步骤条。参数只在挂载时读，
 * 之后阶段每次变化都会用 `replace` 写回地址（`?stage=` 与步骤条始终一致，
 * 刷新 / 分享不会看到「地址说评估、页面在生成」）。缺省 / 不认识的值一律落回「生成」。
 *
 * **这一页没有「新建」入口**：路径里的 `:agentId` 就是它的身份，顶栏的名称 / 描述 / 图标
 * 来自 `agentsApi.detail()`。查不到这个 id（多半是刚被删掉）就整页换成「找不到这个智能体」，
 * 不摆一套假的三阶段外壳。
 *
 * ── 三个阶段的真实度 ──────────────────────────────────────────────────────
 * - 生成：对话、文件树都是真的（`stage = 'development'`）。
 * - 预览：对话是真的，跑在预览沙箱里（`stage = 'preview'`，每次 run 前从开发产物重拷）。
 * - 评估：对话是真的，跑在评估沙箱里（`stage = 'evaluation'`，与预览同规则物化）。
 *   右栏的评估报告仍是一版演示面板（`EvaluatePanel`），接真实产物是下一步的事。
 */

export function AgentCreatePage() {
  const { t } = useI18n();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  /** 路由保证非空（没带的地址在 App.tsx 就被重定向走了），`?? ''` 只为类型收窄 */
  const { agentId = '' } = useParams<{ agentId: string }>();

  /**
   * 首页交接过来的一次性载荷（原话 + 初始化会话 id）。没有就是空对象 ——
   * 从列表页点进来、手输地址都走这条路，行为与以前一致。
   */
  const seed = readDesignSeed(location.state);
  /** 创建响应里的 `updatedAt`；只从首页创建进来时有值，用于等后端把元数据刷成 AI 版 */
  const metaBaseline = readMetaBaseline(location.state);

  /** 顶栏身份。null 且无错 = 首屏还没回来 */
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [agentError, setAgentError] = useState<string | null>(null);

  /** 内置智能体只读：不设计、不评估，也不给它找会话 / 查产物 */
  const builtin = agent?.source === 'builtin';

  /**
   * 初始阶段。**地址参数优先**（`?stage=evaluation`，卡底「评估」带过来的）；
   * 没带 / 不认识就是「生成」。只用首次渲染时的那份地址 —— 之后的方向是
   * `stageId` → 地址（见下面那个 effect），不再反向同步，避免两处互为来源。
   */
  const [stageId, setStageId] = useState<StageId>(() =>
    readStageParam(searchParams.get('stage')),
  );

  /**
   * 阶段是这一页的「当前视图」，地址里也留一份：刷新、分享、从历史恢复时都落在同一阶段。
   *
   * 用 `replace` 而不是 `push`：步骤条上的切换不是一次新的导航，不该在浏览器
   * 后退里堆三步。`development` 在地址里就是**没有这个参数**（缺省值不写进地址）。
   *
   * 除 `stage` 之外的参数原样保留 —— 例如模块的 `?embed=1`：它决定要不要挂侧边栏，
   * 被 `App` 每次渲染都读一遍，不能因为这里重建查询串就丢了。
   *
   * `state` 也原样带过去：首页交接的首轮载荷（原话 / 附件）挂在 `location.state` 上，
   * 带参数的 `navigate` 缺省会把 state 置空 —— 那样切一次阶段，首轮就只剩库里那份快照了。
   */
  useEffect(() => {
    const desired = stageId === 'development' ? null : stageId;
    if (searchParams.get('stage') === desired) return;
    const next = new URLSearchParams(searchParams);
    if (desired === null) next.delete('stage');
    else next.set('stage', desired);
    setSearchParams(next, { replace: true, state: location.state });
  }, [location.state, searchParams, setSearchParams, stageId]);

  /**
   * 生成产物状态（契约 4.10）。**预览 / 评估的准入只看它**：
   * 进入阶段前现拉一次，`ready` 为 false 时该阶段整块换成告警占位（见 `StageLocked`）。
   *
   * 挂载时也拉一次：步骤条要提前标出哪一阶段还不能进（缓存只用于展示，
   * 真正的判定在 `selectStage` 里现拉）。
   */
  // 内置智能体不参与生产流程（服务端 409）：空 id 让 Hook 直接按「不查」处理
  const production = useProductionGate(builtin ? '' : agentId);
  /** 正在判定能不能进入某个阶段：期间步骤条不响应点击，避免并发请求 */
  const [entering, setEntering] = useState<StageId | null>(null);

  /**
   * 产物是否已生成完成。**预览 / 评估的会话只有它为真时才建**：
   * 没生成完就开会话，页面上会摆着一场什么都干不了的对话，用户会以为能用了。
   * 判据只来自服务端快照（`useProductionGate`），不在前端推断。
   */
  const productionReady = production.snapshot?.ready === true;
  const productionReason =
    production.snapshot === null
      ? (production.error ?? null)
      : production.snapshot.reasons.join('；');

  /**
   * 产物状态还没问到（首次请求还在路上）。直接带着 `?stage=preview|evaluation` 进来时，
   * 这一小段时间里不能摆 `StageLocked` —— 它把「读不到状态」当原因，等于替服务端
   * 下了「不能进」的结论。等首次请求落地，这里会换成该阶段的对话或 `StageLocked`。
   */
  const gatePending = production.snapshot === null && production.error === null;

  /**
   * 当前阶段的对话记录与收发。**整页一条连接**，切阶段换的是它打开的那场会话。
   * 三个阶段都走真会话 —— 这个判断只在 `useCreationChat` 里；
   * 预览 / 评估还要过产物状态这道门（见 `CreationGate`）。
   */
  /**
   * 生产会话里用户新选 / 取消的知识检索工作流。
   *
   * `undefined` = 本页没改过（用智能体自己的配置 `Agent.knowledgeWorkflowId`）；
   * `null` = 已取消（落库成功）；对象 = 已选中（落库成功）。
   *
   * 改动**先落库再改这里**：取消要跨刷新生效，只改内存会在下次打开时被配置复活。
   */
  const [knowledge, setKnowledge] = useState<KnowledgeWorkflow | null | undefined>(undefined);
  /** 保存中：锁住 chip，避免连点产生交错请求 */
  const [knowledgeSaving, setKnowledgeSaving] = useState(false);
  /** 保存失败的人话；显示在 chip 右侧，下一次改动静默清掉 */
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);

  /**
   * 当前生效的知识检索 id：本页改过就用页面值，否则用智能体自己的配置。
   * 空串 = 没有（智能体详情还没回来时也是空串，加载完会自然切到配置值）。
   */
  const effectiveKnowledgeId =
    knowledge === undefined ? (agent?.knowledgeWorkflowId ?? '') : (knowledge?.id ?? '');

  const chat = useCreationChat(
    // 内置智能体不设计：空 id 让 Hook 不找会话、不建会话（服务端也只放行 runtime）
    builtin ? '' : agentId,
    stageId,
    seed,
    {
      ready: productionReady,
      reason: productionReason,
    },
    /*
     * 创建时落库的首轮快照（原话 + 附件），路由 state 丢了（刷新 / 从列表再次进入）
     * 时的兜底。详情还没回来时传 `undefined`（不是空快照）：Hook 会等它落定再开会话，
     * 否则这份快照就赶不上首轮补发了。取失败传空快照，页面本来就有错误提示。
     *
     * `stored` 每次渲染都是新对象，但 Hook 只解构成原始值进依赖，不会反复 boot。
     */
    agent === null && agentError === null
      ? undefined
      : { prompt: agent?.initialInput ?? '', attachments: agent?.initialAttachments ?? [] },
    /*
     * 预览 / 评估首次建会话要显式传 modelId：用智能体所属工作区的默认模型。
     * 详情还没回来时为 undefined，前端解析会退回框架当前工作区。
     */
    agent?.workspaceId ?? undefined, // 内置行 workspaceId=null：归一成 undefined，走框架当前工作区解析
    // 知识检索：智能体配置 + 本页改动（空串 = 没有）
    effectiveKnowledgeId === '' ? null : effectiveKnowledgeId,
  );

  /**
   * 配置里只有 id，拉列表补名称 —— 匹配不上或拉失败就退回显示 id。
   * 本页刚选过（`knowledge` 是对象）时不需要查。
   */
  const autoKnowledge = useKnowledgeWorkflow(
    knowledge === undefined && effectiveKnowledgeId !== '' ? effectiveKnowledgeId : null,
  );

  /** chip 显示用：本页选择优先；否则用配置值，名称能查到就显示名称，查不到显示 id。 */
  const knowledgeValue: KnowledgeWorkflow | null =
    knowledge !== undefined
      ? knowledge
      : effectiveKnowledgeId === ''
        ? null
        : (autoKnowledge ?? {
            id: effectiveKnowledgeId,
            name: effectiveKnowledgeId,
            description: '',
          });

  /**
   * 改 / 取消知识检索：**先写库、再改页面状态**。
   *
   * 取消传空串（服务端契约：空串 = 取消，不传 = 不改）。写库成功后才更新 chip，
   * 失败保持原值并把原因摆在 chip 旁边 —— 不能出现「界面已取消、库里还留着」的假象。
   */
  const changeKnowledge = useCallback(
    async (next: KnowledgeWorkflow | null): Promise<void> => {
      setKnowledgeSaving(true);
      setKnowledgeError(null);
      try {
        const updated = await agentsApi.update(agentId, { knowledgeWorkflowId: next?.id ?? '' });
        // update 只返回 Agent，不带详情里的派生字段（knowledgeInjected / skills），合并保留
        setAgent((prev) => (prev === null ? null : { ...prev, ...updated }));
        setKnowledge(next);
      } catch (err) {
        setKnowledgeError(
          t('knowledge.saveFailed', {
            error: err instanceof Error ? err.message : String(err),
          }),
        );
      } finally {
        setKnowledgeSaving(false);
      }
    },
    [agentId, t],
  );

  /**
   * 配置已取消、但产物里还留着知识检索技能 —— 取消只改「下次构建用什么」，
   * 不会动已经生成好的产物。这里给一个明确的重建入口，由用户承担耗时。
   */
  const knowledgeStale =
    !builtin && agent?.knowledgeInjected === true && effectiveKnowledgeId === '';

  /** 发一条重建请求（只用 harness-create 现有接口），让 agent-genesis 重新生成一版产物。 */
  const rebuildWithoutKnowledge = useCallback(() => {
    if (chat.running) return;
    void chat.send({ text: composeKnowledgeRebuildPrompt(), attachments: [] });
  }, [chat.running, chat.send]);

  /**
   * 路由 state 带来的「优化 / 评估」请求，三种送达方式：
   *   - 首页「优化智能体」带 `autoSend`：到页即发（`kickoffInto`，会话 ready 后发一次）；
   *   - 首页「评估智能体」带 `autoSend + newSession`：交给评估阶段**重开一场再开跑**
   *     （要先停掉还在跑的旧一轮、清掉右栏旧报告，所以不在这里直接发）；
   *   - 技能库的「优化」不带：只放进发送框（`capability-routing.md` §5.2），
   *     一轮优化跑几分钟、烧 token，发不发由用户按发送键。
   *
   * 路由 state 只活这一次导航，但重渲染会反复读到它 —— 用 ref 挡第二次。
   * `replayInto` 走 `ComposerReplay` 管道，Composer 还没挂载时也能先存着。
   *
   * 自动发的那条**先把 history state 清掉**：刷新 / 重新挂载时不能把同一轮再发一次
   * （普通 replay 只是重填发送框，重复一次无害）。
   */
  const routeReplay = readDesignReplay(location.state);
  const appliedRouteReplay = useRef(false);
  /**
   * 评估阶段的「重开一场再开跑」请求（首页「评估智能体」）。
   *
   * 请求要等评估阶段就绪、旧一轮停稳之后才执行，那两件事只有 `EvaluateStage` 看得见；
   * 所以这里只把它记成 state 传下去，不在页面 effect 里直接 `restart`。
   */
  const [autoStart, setAutoStart] = useState<EvalAutoStart | null>(null);
  const autoStartSeq = useRef(0);
  useEffect(() => {
    if (routeReplay === null || appliedRouteReplay.current) return;
    appliedRouteReplay.current = true;
    if (routeReplay.autoSend) {
      if (routeReplay.newSession) {
        autoStartSeq.current += 1;
        setAutoStart({
          key: autoStartSeq.current,
          text: routeReplay.text,
          paths: routeReplay.paths,
        });
      } else {
        chat.kickoffInto(routeReplay.text, routeReplay.paths);
      }
      navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
      return;
    }
    chat.replayInto(routeReplay.text, routeReplay.paths);
  }, [chat, routeReplay, navigate, location.pathname, location.search]);

  /**
   * 分栏宽度放在页面级：生成和评估共用同一个宽度，切阶段不该复位。
   * 传 `stageId` 只是让 ResizeObserver 在换 `.ac-main` 节点时重新观察。
   */
  const split = useSplitWidth(stageId);

  /**
   * 模型清单与首页同一个来源（`useModels`）。
   *
   * **选中值就是会话自己的 `modelId`**，不另存一份页面状态：切换时调
   * `sessions/:sessionId/update`，成功后再以服务端返回的 `Session` 为准 ——
   * 选择器跟着会话走，请求失败时也不会留下一个假的选中项。
   * 会话的 `modelId` 为空时选择器显示「选择模型」：候选只有模型列表，不提供
   * 「跟随本机配置」这一项。加载中 / 拉失败 / 空三种状态由 Composer 在那个下拉上
   * 表达，页面不用自己画提示。
   *
   * **三个阶段都传这个对象**：对话在哪一阶段，就在哪一阶段能换模型。
   * 预览阶段以前刻意不放，结果同一个输入框在切阶段时忽有忽无；
   * 模型本就是会话级字段，哪场会话都能改，没有理由藏起来。
   */
  const { models, loading: modelsLoading, error: modelsError } = useModels();

  /**
   * 会话与通道没准备好时也**不许发送**：这时消息没有落点，点发送只会弹一句
   * 「还没选中会话 / 未连接」，正文再被原样弹回来 —— 而页面明明还在写着
   * 「准备会话…」。原因按连接态与准备阶段分开说，措辞与右上角状态 pill 同源
   * （`create.pane.*`），不另造一套。
   *
   * 只锁发送键与 Enter，不锁编辑区（`sendBlockedReason` 的语义）：准备期间
   * 用户仍可以先把需求打完。
   */
  const linkBlockedReason =
    chat.link.conn !== 'ready'
      ? chat.link.conn === 'closed'
        ? t('create.pane.reconnecting')
        : t('create.pane.connecting')
      : chat.link.phase === 'failed'
        ? t('create.pane.linkFailed')
        : chat.link.phase === 'ready'
          ? null
          : t('create.pane.preparing');

  /**
   * 没有可用模型同样不许发起会话：消息发出去也只会以模型错误收尾。
   * 加载中 / 拉失败 / 空都挡（判据见 `modelBlockReason`），发送框上会显示原因。
   * 会话绑定的模型在框架侧被删了也挡（判据见 `sessionModelBlockReason`）：
   * 这在服务端会是 400，但让用户在这里就看到原因、当场重选，比发出去再弹 toast 好。
   * 连接 / 准备的原因优先：它比模型更早决定「这一轮根本发不出去」。
   */
  const sendBlockedReason =
    linkBlockedReason ??
    modelBlockReason(
      { models, loading: modelsLoading, error: modelsError },
      t('create.page.startSession'),
    ) ??
    sessionModelBlockReason(
      { models, loading: modelsLoading, error: modelsError },
      chat.session?.modelId,
    );

  useEffect(() => {
    // 换了 agentId（列表页点另一张卡片）要重新取，且**旧请求的响应必须丢掉** ——
    // 否则切得比 mock 那 250ms 延迟快时，会先看到前一个智能体的名字闪一下
    let cancelled = false;
    setAgent(null);
    setAgentError(null);

    void agentsApi.detail(agentId).then(
      (detail) => {
        if (!cancelled) setAgent(detail);
      },
      (err: unknown) => {
        if (!cancelled) setAgentError(describeAgentError(err, agentId));
      },
    );

    return () => {
      cancelled = true;
    };
  }, [agentId]);

  /**
   * 等后端把创建时的兜底元数据刷成 AI 版（`server/.../agent-metadata.ts`）：
   * 从首页创建进来时带着创建响应的 `updatedAt`，每 2 秒读一次详情，变了就换掉顶栏身份并停止；
   * 约 60 秒没变就放弃（生成失败 / 进程重启都会保持兜底值）。
   *
   * 「变了」不区分是谁改的：用户在另一个标签页手改也会走到这里，显示用户自己的值，语义正确。
   * 没有基线（从列表点进来、刷新、直接输地址）时一次请求都不发。
   */
  useEffect(() => {
    if (metaBaseline === null) return;
    let cancelled = false;
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      if (tries > 30) {
        clearInterval(timer);
        return;
      }
      void agentsApi.detail(agentId).then(
        (detail) => {
          if (cancelled || detail.updatedAt === metaBaseline) return;
          clearInterval(timer);
          setAgent(detail);
        },
        () => {}, // 读失败不打扰：下一拍再试
      );
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [agentId, metaBaseline]);

  const { refresh: refreshProduction, check: checkProduction } = production;

  /**
   * 生成阶段一轮跑完，产物状态可能刚变（第一次生成成功、或失败了）：
   * 重拉一次，步骤条上的「还不能进」标记才不会停留在旧值上。
   * 判据是 `running` 由真转假 —— 只在 development 阶段有意义。
   */
  const wasRunningRef = useRef(chat.running);
  useEffect(() => {
    if (stageId === 'development' && wasRunningRef.current && !chat.running) {
      refreshProduction();
      // 一轮跑完产物可能变了：详情里的 `knowledgeInjected` 要跟着刷新，
      // 否则「移除并重建」跑完还一直提示产物里有知识检索
      void agentsApi.detail(agentId).then(setAgent, () => {});
    }
    wasRunningRef.current = chat.running;
  }, [agentId, chat.running, stageId, refreshProduction]);

  /**
   * 生成中时，停在告警占位上的用户会自动等到产物完成：轮询状态，ready 后
   * 直接换成那一阶段的对话（渲染条件看 `productionReady`）。
   * 只轮询 `building` —— 其余状态不会自己变，问了也是白问。
   */
  const watching = stageId !== 'development' && !productionReady && production.snapshot?.status === 'building';
  useEffect(() => {
    if (!watching) return;
    const timer = setInterval(refreshProduction, 4000);
    return () => clearInterval(timer);
  }, [watching, refreshProduction]);

  /**
   * 切阶段。**预览 / 评估必须先问服务端产物生成完了没有**（契约 4.10）：
   * 现拉一次，然后把阶段切过去 —— 不 ready 时该阶段渲染成整块告警占位
   * （`StageLocked`），而不是留在生成阶段上弹一条小提示。
   *
   * 先判定再切、而不是切过去再判定：切过去时 `production.snapshot` 必须已经是新的，
   * 否则会用旧快照把 `useCreationChat` 放行，白白建一场会话。
   * 判定期间 `entering` 挡住并发点击 —— 每次判定都是一次真实请求。
   */
  async function selectStage(next: StageId) {
    if (next === stageId || entering !== null) return;

    // 生成阶段没有准入条件：它本来就是产出产物的地方
    if (next === 'development') {
      setStageId(next);
      return;
    }

    setEntering(next);
    try {
      await checkProduction();
      // 不管 ready 与否都切过去：不就绪时由 StageLocked 占满主体区说明原因
      setStageId(next);
    } finally {
      setEntering(null);
    }
  }

  const tabs = stageTabs(t);
  const stageIndex = tabs.findIndex((item) => item.id === stageId);

  /**
   * 步骤条上「已完成」（绿勾）的唯一来源：**生成阶段的产物已经就绪**（契约 4.10 的 `ready`）。
   *
   * 预览 / 评估没有可验证的完成信号（不存在「预览通过」这种持久状态），所以不画绿勾。
   * 用户可以从卡片直接跳「评估」—— 那时前面的阶段只是**位置**在前，不代表做过；
   * 它们用 `past`（序号 + 正常字色）表示「已经翻过这一页」，不冒充「已完成」。
   */
  const doneStageIds = new Set<StageId>(
    production.snapshot?.ready === true ? ['development'] : [],
  );
  /** 查不到这个智能体：整页只留顶栏，body 换成「找不到」，不摆三阶段外壳 */
  const missing = agentError !== null;

  /**
   * 选中值读 `chat.session.modelId`。会话还没准备好（`session === null`）时借
   * Composer 的 loading 态把下拉锁住 —— 别让人往一个还不存在的会话上写模型。
   */
  const model: ComposerModel = {
    value: chat.session?.modelId ?? '',
    options: models.map((item) => ({ value: item.id, label: item.label })),
    onChange: (value) => {
      void chat.updateModel(value);
    },
    loading: modelsLoading || chat.session === null,
    error: modelsError,
  };

  /**
   * 评估面板点「修复」：把这条未通过的用例交给左侧那场真实评估会话处理。
   *
   * 右栏目前还是演示数据，但**动作不能是假的** —— 以前这里是往演示内核里补一条
   * 假消息，现在评估已经接了真会话，就应当真的发出去。发送键的忙碌 / 阻塞态由
   * `chat.send` 与 Composer 自己管，这里不再判。
   */
  function handleCaseRetry(task: string) {
    chat.send({ text: t('create.page.caseRetryPrompt', { task }), attachments: [] });
  }

  /**
   * 对话里文件引用的解析基址：会话 cwd = `<智能体产物根>/<stage>`。
   *
   * 详情还没回来（`agent === null`）时给 null：相对路径打不开，但已发附件那种
   * 绝对路径仍然能开 —— 不该因为详情慢半拍就把入口全锁上。
   */
  const filePreview = useFilePreviewState(
    agent === null ? null : `${agent.dir.replace(/\/+$/u, '')}/${stageId}`,
  );

  /**
   * 顶栏「返回专家列表」，以及内置 / 找不到时那两个兜底按钮。
   *
   * **专家列表属于框架**（宿主路由 `/experts`，本模块的 `/agents` 只是被嵌进去的那一页）：
   * 只在 iframe 里 `navigate('/agents')` 是不够的 —— 宿主地址栏还停在 `/agent-dev` 之类的
   * 路由上，侧栏高亮的也不是「专家」，看起来就是"回到了我们自己的页面"。
   * 所以这里和卡片「使用」一样**整页离开模块**，地址口径与跳转写法见 `shared/framework.ts`。
   *
   * 被嵌着时框架的沙箱只放行**用户激活**的顶层跳转（2026-10-21 起，
   * `allow-top-navigation-by-user-activation`），所以点击就是原页跳；宿主还是旧版本、
   * 顶层跳转被挡下时由 `leaveToFramework` 兜底成开新标签 —— 与「使用」同一行为。
   */
  function backToExperts() {
    leaveToFramework(frameworkExpertsUrl());
  }

  return (
    <FilePreviewProvider value={filePreview}>
    <div className={`ac${filePreview.tabs.length > 0 ? ' ac--dock-open' : ''}`}>
      <header className="ac-top">
        <div className="ac-top-left">
          <button
            type="button"
            className="ac-back"
            aria-label={t('create.page.backToList')}
            onClick={backToExperts}
          >
            <Icon name="arrowLeft" size={16} />
          </button>

          <AgentIdentity agentId={agentId} agent={agent} error={agentError} />
        </div>

        {/*
          顶栏右侧**不放动作按钮**。
          曾经有过「放弃 / 发布智能体」，两个都不成立：
          - 发布：没有这个动作。智能体创建后后端就把工作区建好了，被使用时校验可用状态，
            始终取最新值 —— 没有「把产出固化成正式资产」这一步。
          - 放弃：唯一的破坏性效果是建了一半的工作区，而后端自己管它，前端没有可丢弃的产出。
          离开这一页就是点左上角的返回（整页回框架的专家页 `/experts`，见 `backToExperts`）。
        */}
      </header>

      {missing ? (
        <MissingAgent
          agentId={agentId}
          message={agentError}
          onBack={backToExperts}
        />
      ) : builtin ? (
        <BuiltinAgent onBack={backToExperts} />
      ) : (
        <>
          <nav className="ac-stepper" aria-label={t('create.page.stepperLabel')}>
            {tabs.map((item, index) => {
              const done = doneStageIds.has(item.id);
              /*
               * `done` 只留给它真有完成证据的阶段（见 `doneStageIds`）；
               * 位置在前的其余阶段是 `past` —— 别用绿勾替用户宣布「这一阶段做过了」。
               */
              const state =
                index === stageIndex ? 'active' : done ? 'done' : index < stageIndex ? 'past' : 'todo';
              /*
               * 预览 / 评估在产物没生成完时**仍然可点** —— 点了会现拉一次状态，
               * 然后由该阶段整块说明为什么进不去（`StageLocked`）。
               * 这里只把「上次读到的状态」标出来，不代替判定。
               */
              const gated = item.id !== 'development';
              // 还没读到过状态时不标：否则首屏会闪一下「全都锁着」
              const locked = gated && production.snapshot !== null && !production.snapshot.ready;
              const checking = entering === item.id;
              return (
                <Fragment key={item.id}>
                  {index > 0 && (
                    <span
                      className={`ac-stepper-line${
                        doneStageIds.has(tabs[index - 1].id) ? ' ac-stepper-line--done' : ''
                      }`}
                    />
                  )}
                  <button
                    type="button"
                    className={`ac-step ac-step--${state}${locked ? ' ac-step--locked' : ''}`}
                    aria-current={state === 'active'}
                    aria-busy={checking}
                    disabled={entering !== null}
                    title={locked ? t('create.page.stepLocked') : undefined}
                    onClick={() => void selectStage(item.id)}
                  >
                    <span className="ac-step-dot">
                      {state === 'done' ? <Icon name="check" size={12} /> : index + 1}
                    </span>
                    <span className="ac-step-label">{item.label}</span>
                    {locked && (
                      <span className="ac-step-gate" aria-hidden="true">
                        <Icon name="alert" size={11} />
                      </span>
                    )}
                  </button>
                </Fragment>
              );
            })}
          </nav>

          {stageId === 'development' && (
            <ProductionStage
              agentId={agentId}
              agent={agent}
              chat={chat}
              split={split}
              model={model}
              sendBlockedReason={sendBlockedReason}
              // 内置智能体不设计，不挂知识检索
              knowledge={builtin ? null : knowledgeValue}
              knowledgeSaving={knowledgeSaving}
              knowledgeError={builtin ? null : knowledgeError}
              knowledgeStale={knowledgeStale}
              onKnowledgeChange={changeKnowledge}
              onRebuildWithoutKnowledge={rebuildWithoutKnowledge}
            />
          )}
          {/*
            预览 / 评估**只在产物生成完成后才渲染对话**；否则整块换成告警占位。
            两个阶段共用同一套判定，差别只在文案里的阶段名。
          */}
          {stageId === 'preview' &&
            (productionReady ? (
              <PreviewStage
                agentId={agentId}
                chat={chat}
                model={model}
                sendBlockedReason={sendBlockedReason}
              />
            ) : gatePending ? (
              <StageChecking stage={stageId} />
            ) : (
              <StageLocked
                stage={stageId}
                production={production}
                replayPending={chat.replay !== null}
                onBack={() => setStageId('development')}
              />
            ))}
          {stageId === 'evaluation' &&
            (productionReady ? (
              <EvaluateStage
                agentId={agentId}
                agentDir={agent?.dir ?? null}
                chat={chat}
                split={split}
                model={model}
                sendBlockedReason={sendBlockedReason}
                onCaseRetry={handleCaseRetry}
                autoStart={autoStart}
                onAutoStarted={() => setAutoStart(null)}
              />
            ) : gatePending ? (
              <StageChecking stage={stageId} />
            ) : (
              <StageLocked
                stage={stageId}
                production={production}
                replayPending={chat.replay !== null}
                onBack={() => setStageId('development')}
              />
            ))}
        </>
      )}
    </div>

      {/* 面板自己在没有打开文件时返回 null；放在 .ac 外面，fixed 定位不参与页面 flex 布局 */}
      <FilePreviewPanel />
    </FilePreviewProvider>
  );
}

/**
 * 直接落在预览 / 评估阶段、产物状态还在路上时的占位。
 *
 * 与 `StageLocked` 长得像，但说的是**中性**的一句「正在确认」：这时服务端还没回答，
 * 既不能说进得去、也不能说进不去。`useProductionGate` 的首次请求落地后这一块就会消失。
 */
function StageChecking({ stage }: { stage: StageId }) {
  const { t } = useI18n();
  return (
    <div className="ac-main ac-main--single">
      <div className="ac-locked" aria-busy="true">
        <span className="ac-locked-icon ac-locked-icon--busy">
          <Icon name="refresh" size={24} />
        </span>
        <h2 className="ac-locked-title">
          {t('create.page.checkingStage', { stage: stageName(stage, t) })}
        </h2>
        <p className="ac-locked-hint">{t('create.page.checkingStageHint')}</p>
      </div>
    </div>
  );
}

/**
 * 产物没生成完时，预览 / 评估阶段的**整块占位**（不是一条提示条）。
 *
 * 用户点进来是为了用这个阶段；进不去时就把整个主体区交给它说明原因，
 * 而不是切回生成阶段、在顶上挂一行小字 —— 那样既没回答「我为什么进不来」，
 * 也没给「什么时候能进」的预期。
 *
 * 同时它保证「不显示会话」这条规则不依赖入口：只要状态不是 ready，
 * 这两个阶段就没有任何对话区，也就不会有「预览会话 / 评估会话」这几个字。
 */
function StageLocked({
  stage,
  production,
  replayPending = false,
  onBack,
}: {
  stage: StageId;
  production: ProductionGate;
  /**
   * 这一阶段已经留着一句从别处带来的要求（首页评估落点的 replay），
   * 只是现在还进不来 —— 发送框不在屏幕上，得告诉用户「话没丢」。
   */
  replayPending?: boolean;
  onBack: () => void;
}) {
  const { t } = useI18n();
  const label = stageName(stage, t);
  const snapshot = production.snapshot;
  const building = snapshot?.status === 'building';
  const reason =
    snapshot === null
      ? (production.error ?? t('create.gate.noProduction'))
      : snapshot.reasons.join(t('common.clauseSeparator'));

  return (
    <div className="ac-main ac-main--single">
      <div className="ac-locked" role="alert">
        <span className="ac-locked-icon">
          <Icon name="alert" size={26} />
        </span>
        <h2 className="ac-locked-title">{t('create.page.lockedTitle', { stage: label })}</h2>
        <p className="ac-locked-desc">{t('create.page.lockedDesc', { reason: trimPeriod(reason) })}</p>

        {/* 话已经带过来了，只是这一阶段还进不去 —— 先说清楚，别让用户以为白写了 */}
        {replayPending && (
          <p className="ac-locked-hint">{t('create.page.lockedDraftKept', { stage: label })}</p>
        )}

        {snapshot === null ? (
          <p className="ac-locked-hint">{t('create.page.lockedReadFailed')}</p>
        ) : building ? (
          <p className="ac-locked-hint">
            {t('create.page.lockedReady', { stage: label })}
            {snapshot.product === null
              ? ''
              : t('create.page.lockedProduct', {
                  name: snapshot.product.name,
                  version: snapshot.product.version,
                })}
          </p>
        ) : snapshot.status === 'not_started' ? (
          <p className="ac-locked-hint">{t('create.page.lockedNotStarted')}</p>
        ) : (
          <p className="ac-locked-hint">{t('create.page.lockedBlocked')}</p>
        )}

        <div className="ac-locked-actions">
          <button
            type="button"
            className="ac-btn ac-btn--primary"
            disabled={production.loading}
            onClick={production.refresh}
          >
            {production.loading ? t('create.page.checking') : t('create.page.recheck')}
          </button>
          <button type="button" className="ac-btn" onClick={onBack}>
            {t('create.page.backToBuild')}
          </button>
        </div>
      </div>
    </div>
  );
}

/** 阶段显示名；未知 id 原样返回（`STAGE_TABS` 是唯一来源，见 stage-meta.ts） */
function stageName(
  id: StageId,
  t: (key: MessageKey, params?: MessageParams) => string,
): string {
  return stageTabs(t).find((item) => item.id === id)?.label ?? id;
}

/** 拼句前去掉服务端原因自带的句末标点，避免出现「。。」 */
function trimPeriod(text: string): string {
  return text.replace(/[。！？.!?]+$/u, '');
}

/**
 * 顶栏左侧的身份块，三态：加载中（骨架）→ 拿到（图标 / 名称 / 描述）→ 报错。
 *
 * 描述留空时显示「未填写描述」而不是空白 —— 这一块左侧对齐，少一行会让顶栏高度塌一下。
 */
function AgentIdentity({
  agentId,
  agent,
  error,
}: {
  agentId: string;
  agent: Agent | null;
  error: string | null;
}) {
  const { t } = useI18n();
  if (agent !== null) {
    return (
      <div className="ac-agent">
        <AgentAvatar icon={agent.icon} name={agent.name} size={34} />
        <span className="ac-agent-meta">
          <span className="ac-agent-name">{agent.name}</span>
          <span className="ac-agent-desc">
            {agent.description === '' ? <em>{t('create.page.noDescription')}</em> : agent.description}
          </span>
        </span>
      </div>
    );
  }

  if (error !== null) {
    return (
      <div className="ac-agent">
        <span className="ac-agent-avatar ac-agent-avatar--bad">
          <Icon name="alert" size={17} />
        </span>
        <span className="ac-agent-meta">
          <span className="ac-agent-name">{t('create.page.unknownAgent')}</span>
          {/* 原因交给下面的 MissingAgent 说，这里只留 id，免得同一句话出现两遍 */}
          <span className="ac-agent-desc">
            <code>{agentId}</code>
          </span>
        </span>
      </div>
    );
  }

  return (
    <div className="ac-agent" aria-busy="true" aria-label={t('create.page.readingAgent')}>
      <span className="ac-agent-avatar ac-skeleton" />
      <span className="ac-agent-meta">
        <span className="ac-skeleton ac-skeleton--name" />
        <span className="ac-skeleton ac-skeleton--desc" />
      </span>
    </div>
  );
}

/** 查不到这个智能体时的整页 body：一句原因 + 一个出口，不摆假的阶段进度条 */
function MissingAgent({
  agentId,
  message,
  onBack,
}: {
  agentId: string;
  message: string | null;
  onBack: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="ac-missing" role="alert">
      <Icon name="alert" size={22} />
      <p className="ac-missing-title">
        {t('create.page.notFound', { id: agentId })}
      </p>
      <p className="ac-missing-desc">{message ?? t('create.page.loadFailed')}</p>
      <button type="button" className="ac-btn ac-btn--primary" onClick={onBack}>
        {t('create.page.backToExperts')}
      </button>
    </div>
  );
}

/** 内置智能体：不摆三阶段外壳（手输地址 / 旧书签也进不来） */
function BuiltinAgent({ onBack }: { onBack: () => void }) {
  const { t } = useI18n();
  return (
    <div className="ac-missing ac-missing--readonly">
      <Icon name="shield" size={22} />
      <p className="ac-missing-title">{t('create.page.builtinTitle')}</p>
      <button type="button" className="ac-btn ac-btn--primary" onClick={onBack}>
        {t('create.page.builtinBack')}
      </button>
    </div>
  );
}

/**
 * 把取详情的失败翻译成能动手的话。
 *
 * 与列表页的 `describeLoadError` 同源但**不共用**：列表页那版是「整屏加载失败」，
 * 这里多一条 404（id 查不到）—— 那在列表页不可能发生，在这里却是最常见的一种
 * （卡片点进来时，那个专家刚在另一个标签页被删掉）。
 */
function describeAgentError(err: unknown, agentId: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) {
      return msg('create.page.agentNotFound', { agentId });
    }
    // 「整个后端没起」的判据是「响应根本不是 JSON」（判据只有一处，见 isBackendDown）。
    // 后端自己报的 4xx / 5xx 有 JSON，不走这条 —— 它的原话比我们的猜测有用。
    if (isBackendDown(err)) {
      return msg('create.page.detailDown', { hint: backendDownHint(), agentId });
    }
    return msg('create.page.detailStatus', { message: err.message, status: err.status });
  }
  return err instanceof Error ? err.message : msg('create.page.loadFailed');
}

/**
 * 地址里的 `?stage=`。**只认步骤条上真有的三个阶段**（顺序见 `stage-meta.ts`）：
 * `runtime` 是后端阶段，但不是创建流程的一步，这一页也没有对应面板；拼错的值同理。
 * 认不出来就落回「生成」—— 那是有内容、也进得去的一屏，比停在一个渲染不出东西的
 * 阶段上好。地址参数是**入口**，不是判据：能不能进这一阶段仍由产物状态门禁说了算。
 */
const STAGE_PARAMS: readonly StageId[] = ['development', 'preview', 'evaluation'];

function readStageParam(value: string | null): StageId {
  return STAGE_PARAMS.find((id) => id === value) ?? 'development';
}

/**
 * 读首页放在 `navigate(..., { state })` 里的交接载荷。
 *
 * `location.state` 的类型是 `any`，而且路由 history 里可能留着旧版本的形状 ——
 * 只认这两个字符串字段，其余一律当没有。空载荷不是错误：列表页点进来、手输地址、
 * 新标签页打开都会走到这里，此时页面照常工作，只是不替用户发首轮。
 */
/**
 * 「优化」带来的 replay 载荷（技能库 / 首页「优化智能体」）。
 *
 * 与首轮 seed 分开读：replay 是「放进发送框」，seed 是「建会话后补发」。
 * `autoSend` 是首页的语义 —— 用户在那里已经按过发送，到设计页直接发；
 * 不带时只放进发送框（技能库「优化」）。
 * `newSession` 只对评估有意义：不复用最近一场，重开一场（重建沙箱）再立刻开跑，
 * 与阶段里的「重新评估」同一个动作。
 * 正文与附件**至少有一项**才算有效载荷（首页只挂文件、不写正文是合法的）。
 * 形状不对时返回 null —— 宁可什么都不填，也不往发送框塞半截路径。
 */
function readDesignReplay(
  state: unknown,
): { text: string; paths: string[]; autoSend: boolean; newSession: boolean } | null {
  if (typeof state !== 'object' || state === null) return null;
  const replay = (state as Record<string, unknown>).replay;
  if (typeof replay !== 'object' || replay === null) return null;
  const value = replay as Record<string, unknown>;
  const text = typeof value.text === 'string' ? value.text.trim() : '';
  const paths = Array.isArray(value.paths)
    ? value.paths.filter((item): item is string => typeof item === 'string' && item !== '')
    : [];
  if (text === '' && paths.length === 0) return null;
  // 只认显式的 true：旧 history 条目里没有这些字段，一律按「不自动发、复用会话」处理
  return {
    text,
    paths,
    autoSend: value.autoSend === true,
    newSession: value.newSession === true,
  };
}

/**
 * 首页创建时带来的元数据基线（创建响应里的 `Agent.updatedAt`）。
 *
 * 后端在创建成功后异步生成名称 / 描述 / 标签，落库会刷新 `updatedAt`；
 * 设计页据此判断「AI 版回来了没有」。形状不对就当没有 —— 不轮询，页面照旧。
 */
function readMetaBaseline(state: unknown): string | null {
  if (typeof state !== 'object' || state === null) return null;
  const value = (state as Record<string, unknown>).metaBaseline;
  return typeof value === 'string' && value !== '' ? value : null;
}

function readDesignSeed(state: unknown): CreationSeed {
  if (typeof state !== 'object' || state === null) return {};
  const value = state as Record<string, unknown>;
  const firstPrompt = typeof value.firstPrompt === 'string' ? value.firstPrompt.trim() : '';
  const initSessionId = typeof value.initSessionId === 'string' ? value.initSessionId : '';
  // 附件是绝对路径；形状不对的项直接丢掉，不把脏数据带到发送那一步
  const attachments = Array.isArray(value.attachments)
    ? value.attachments.filter((item): item is string => typeof item === 'string' && item !== '')
    : [];
  return {
    ...(firstPrompt === '' ? {} : { firstPrompt }),
    ...(initSessionId === '' ? {} : { preferredSessionId: initSessionId }),
    ...(attachments.length === 0 ? {} : { attachments }),
  };
}
