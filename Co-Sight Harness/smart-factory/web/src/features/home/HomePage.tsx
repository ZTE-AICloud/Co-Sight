import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { msg, useI18n } from '../../i18n/useI18n';
import { agentsApi, backendDownHint, isBackendDown } from '../../shared/api/agents';
import type { Agent } from '../../shared/api/agents';
import { ApiError } from '../../shared/api/client';
import { skillsApi } from '../../shared/api/skills';
import type { Skill } from '../../shared/api/skills';
import { modelBlockReason, useModels } from '../../shared/api/useModels';
import { useWorkspaces } from '../../shared/api/useWorkspaces';
import { Composer, attachmentOfPath } from '../../shared/components/Composer';
import type { ComposerFill, ComposerSubmit } from '../../shared/components/Composer';
import { useFilePicker } from '../../shared/components/FilePicker';
import { Icon } from '../../shared/components/Icon';
import { KnowledgeSelect } from '../../shared/components/KnowledgeSelect';
import { TargetPicker } from '../../shared/components/TargetPicker';
import type { PickerOption } from '../../shared/components/TargetPicker';
import type { KnowledgeWorkflow } from '../../shared/api/knowledge';
import { composeHarnessPrompt, withKnowledgeFlag } from '../../shared/commands/harness-prompt';
// 评估命令与评估阶段的「开始评估」同源：只拼一处，别让首页另写一份
import { evalKickoffPrompt } from '../agent-create/stages/evalKickoff';
// 优化场的命令只拼一处：首页也好、工坊也好，发出的必须是同一句 skill_optimize
import { composeOptimizeMessage, skillMdPath } from '../skill-workshop/compose-prompt';
import { CAPABILITIES, capabilityDef, stripCapabilityLabel } from './capabilities';
import type { CapabilityKey } from './capabilities';
import { createAgentFromPrompt } from './create-agent';
import { Mascot } from './icons';

/**
 * 首页（`/`）：入口对话区（左侧菜单栏由 App 外壳提供，不在本页范围内）。
 *
 * 页面形态：
 *
 *   大标题 → 副标题 → 输入卡片（正文开头是**能力 chip**）→ 一行提示 → 五张能力卡
 *
 * **能力是页面状态，不是正文里的命令**：chip 显示能力的名字（「创建智能体」……），
 * 点它五选一；正文只写需求。提交时按能力分流（见 `submit`）：
 *   - 创建智能体 → `POST /agents` 登记身份，跳 `/agents/:id/design`
 *   - 优化智能体 → 已有的设计页（拼 harness-create 命令，到页即发进最近一场开发会话）
 *   - 创建技能   → `/workshop`（工坊自己拼 skill-foundry 前缀）
 *   - 技能优化   → 库技能进 `/workshop?target=…`（工坊拼 skill_optimize 前缀）；智能体技能进它的设计页（replay）
 *   - 评估智能体 → `/agents/:id/design?stage=evaluation`（拼 `agent-eval` 命令，重开一场会话后立刻开跑）
 *
 * 需要目标的两类能力**先读正文、读不出来才弹选择器**（`resolveByName`）：
 * 用户写了「评估一下天气智能体」，就不该再弹一个列表让他重选一遍。
 *
 * ⚠️ **跳转目标是 `/agents/{id}/design`。** 写成 `/agent-create/{id}`、`/agent/{id}/create`
 * 这类前缀**不会报错**：它们落进 App.tsx 的 `*` 兜底被送回本页，表现出来是「点了发送、
 * 输入框清空、什么都没发生」，而其实智能体已经建出来了（静默失败，最难查的一种）。
 * 改路径时对齐 App.tsx 的路由表，别凭记忆写。
 *
 * ⚠️ `/workshop` 的路由由工坊那一阶段在 `App.tsx` 登记。未登记前「创建技能 / 优化库技能」
 * 会落进 `*` 兜底被送回本页 —— 与上面同一个坑。
 */

/**
 * `navigate('/', { state })` 带来的预选能力。
 *
 * 目前只有工坊顶栏的「新会话」会带（`skill.create`）：新会话要到首页发起，
 * 而用户是从技能线过来的，别让他回来还要再点一次 chip。
 */
interface HomeLocationState {
  capability?: CapabilityKey;
}

/** 目标解析的结果：直接命中，或需要用户从候选里挑（歧义 / 没认出来） */
type Resolution<T> =
  | { kind: 'direct'; item: T }
  | { kind: 'pick'; matches: T[]; ambiguous: boolean };

/** 选择器状态：`select` = 只定目标、留在首页；`submit` = 定完直接去落点 */
type PickerState =
  | {
      kind: 'agent';
      mode: 'select' | 'submit';
      text: string;
      attachments: string[];
      options: Agent[];
    }
  | {
      kind: 'skill';
      mode: 'select' | 'submit';
      text: string;
      attachments: string[];
      options: Skill[];
    };

export function HomePage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();

  /** 本轮能力：输入框里那颗 chip 就是它，切换走 chip 菜单或下面的五张卡 */
  const [capability, setCapability] = useState<CapabilityKey>('agent.create');
  const [capMenuOpen, setCapMenuOpen] = useState(false);
  const [draft, setDraft] = useState('');
  /** 能力菜单容器：打开时把焦点送进第一项，关闭时还给 chip */
  const capMenuRef = useRef<HTMLDivElement>(null);
  const wasCapMenuOpenRef = useRef(false);

  /**
   * 当前工作区：新智能体会建到它下面。没有生效工作区就不让创建 ——
   * 与专家页同一口径（那边也按当前工作区展示），否则建完回列表会「找不到」。
   *
   * 页面上不再显示它（首页不摆工作区 pill）：它只用来挡发送、以及筛目标候选。
   */
  const { workspace, loading: workspaceLoading, error: workspaceError } = useWorkspaces();
  const workspaceId = workspace?.id;

  /**
   * 当前选中的模型 id。
   *
   * 清单是异步来的，初值只能是空串；拉到清单后由下面那个 effect 兜默认值：
   * 优先框架的「当前生效模型」（`activeId`），没有生效模型才取第一个。
   * 用户改过之后 modelId 非空，effect 就不再覆盖 —— 这是
   * 「默认选中生效模型，但不抢用户的选择」。
   */
  const [modelId, setModelId] = useState('');
  const { models, activeId, loading: modelsLoading, error: modelsError } = useModels();

  useEffect(() => {
    if (modelId !== '' || models.length === 0) return;
    setModelId(activeId ?? models[0].id);
  }, [models, activeId, modelId]);

  const [hasContent, setHasContent] = useState(false);
  /** 提交请求在路上。它既是按钮的文案依据，也是「别点第二下」的闸 */
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** 已选中的目标（结构化状态；正文里那颗「专家：X / 技能：X」chip 只是它的展示） */
  const [agentTarget, setAgentTarget] = useState<Agent | null>(null);
  const [skillTarget, setSkillTarget] = useState<Skill | null>(null);

  /**
   * 目标清单：切到需要目标的能力时才拉。缓存跟着**当前工作区**走 ——
   * 工作区一变（框架里切了、或首次从「未就绪」读到生效工作区）就整批作废，
   * 见下面那个 reset effect。
   */
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const agentsRef = useRef<Agent[] | null>(null);
  const skillsRef = useRef<Skill[] | null>(null);
  /**
   * 只认最后一次请求的响应。工作区可能在请求在途时变掉：旧响应要是晚到，
   * 会把上一批候选写回缓存，下一次 ensure 就拿它当新工作区的清单返回。
   */
  const agentsSeq = useRef(0);
  const skillsSeq = useRef(0);
  const [agentLoading, setAgentLoading] = useState(false);
  const [skillLoading, setSkillLoading] = useState(false);
  /** 原始错误（展示时套「读取失败：…」） */
  const [agentError, setAgentError] = useState<string | null>(null);
  const [skillError, setSkillError] = useState<string | null>(null);

  const [picker, setPicker] = useState<PickerState | null>(null);

  /**
   * 「能力 chip 刚被补回来」的序号。
   *
   * 发送失败时 Composer 会把正文整段回写，目标 chip（专家：X / ＋选择…）也会跟着没了；
   * 下面那个补 chip 的观察器把能力 chip 補回来后推进这个序号，目标 chip 的 effect
   * 依赖它重跑一次，把目标入口一起恢复 —— 否则用户只看到能力、看不到目标。
   */
  const [chipEpoch, setChipEpoch] = useState(0);

  const ensureAgents = useCallback(async (): Promise<Agent[]> => {
    if (agentsRef.current !== null) return agentsRef.current;
    const seq = (agentsSeq.current += 1);
    setAgentLoading(true);
    try {
      const page = await agentsApi.list({
        pageSize: 200,
        /*
         * 本页拉这份清单**只用于「评估智能体」的候选**（见 capability 的 target）。
         * 内置智能体在设计页是只读的（服务端对 update / delete 也一律 409），
         * 选进来只会把用户带到「内置智能体不可编辑」那一条死路 —— 而首页写的要求
         * 也没有任何落点。所以候选只要用户建的。
         *
         * 不能靠列表接口的工作区筛选排除：内置行的 workspaceId 为 null，
         * 后端会把它混进每个工作区的列表（agents.repo.ts 的 OR 条件）。
         */
        source: 'user',
        ...(workspaceId === undefined ? {} : { workspaceId }),
      });
      // 过期响应（工作区在途时变了）：不写缓存、不落状态，交给新一代请求
      if (seq !== agentsSeq.current) return page.items;
      agentsRef.current = page.items;
      setAgents(page.items);
      setAgentError(null);
      return page.items;
    } finally {
      if (seq === agentsSeq.current) setAgentLoading(false);
    }
  }, [workspaceId]);

  const ensureSkills = useCallback(async (): Promise<Skill[]> => {
    if (skillsRef.current !== null) return skillsRef.current;
    const seq = (skillsSeq.current += 1);
    setSkillLoading(true);
    try {
      const result = await skillsApi.list(workspaceId);
      if (seq !== skillsSeq.current) return result.items;
      skillsRef.current = result.items;
      setSkills(result.items);
      setSkillError(null);
      return result.items;
    } finally {
      if (seq === skillsSeq.current) setSkillLoading(false);
    }
  }, [workspaceId]);

  /**
   * 工作区换了（框架里切了，或首次从「未就绪」读到生效工作区）：上一批目标清单、
   * 已选目标、读取错误都不再属于这一屏。不清的话「专家：X」会指向另一个工作区的
   * 智能体，选择器也会继续拿旧清单糊弄用户。
   *
   * **不需要框架发通知**：`useWorkspaces` 在窗口重新聚焦 / 页面重新可见时静默重查
   * `workspaces/list`，`activeId` 一变 `workspaceId` 就变，本 effect 跟着跑
   * （内嵌态切工作区的同步方式见 docs/open-questions.md）。
   *
   * 同时推进请求序号，让在途的旧工作区请求作废；loading 一并清掉 ——
   * 那些请求就算回来也不再被采纳，别让发送框一直等着它们。
   */
  useEffect(() => {
    agentsSeq.current += 1;
    skillsSeq.current += 1;
    agentsRef.current = null;
    skillsRef.current = null;
    setAgents(null);
    setSkills(null);
    setAgentLoading(false);
    setSkillLoading(false);
    setAgentError(null);
    setSkillError(null);
    setAgentTarget(null);
    setSkillTarget(null);
    setError(null);
  }, [workspaceId]);

  /**
   * 切到需要目标的能力就先拉清单：选择器打开时列表已经在了，
   * 而不是先弹一个「正在读取…」再等一轮。
   */
  useEffect(() => {
    if (capability === 'agent.evaluate' || capability === 'agent.optimize') {
      void ensureAgents().catch((err: unknown) => setAgentError(describeTargetError(err)));
    } else if (capability === 'skill.evolve') {
      void ensureSkills().catch((err: unknown) => setSkillError(describeTargetError(err)));
    }
  }, [capability, ensureAgents, ensureSkills]);

  /**
   * 没有可用模型（或没有生效工作区）就不许发起**会用到它们的能力**：
   * 创建智能体与创建技能都要当场建会话，缺模型根本跑不起来。
   *
   * 优化 / 评估不在这里挡：它们的落点页面自己会解析模型、给出原因 ——
   * 目标页比首页更清楚缺的是什么。
   */
  const actionLabel = t(capabilityDef(capability).labelKey);
  const workspaceBlocked =
    workspace === null
      ? workspaceLoading
        ? t('home.blockedWorkspaceLoading')
        : workspaceError !== null
          ? t('home.blockedWorkspaceError', { action: actionLabel })
          : t('home.blockedWorkspaceNone', { action: actionLabel })
      : null;
  const sendBlockedReason =
    capability === 'agent.create' || capability === 'skill.create'
      ? (workspaceBlocked ??
        modelBlockReason({ models, loading: modelsLoading, error: modelsError }, actionLabel))
      : null;

  /**
   * 「把这些内容放回发送框」的一次性请求（见 `ComposerFill`）。
   * 用一次性请求而不是直接 setDraft：能力 chip 是 Composer 的命令 token，
   * 改 value 只能写纯文字（token 的结构会丢）。
   */
  const [fill, setFill] = useState<ComposerFill | null>(null);
  const fillSeq = useRef(0);
  const inputWrapRef = useRef<HTMLDivElement>(null);

  /**
   * 本次提交要挂的知识检索工作流（null = 不挂）。
   *
   * 只有「创建智能体 / 优化智能体」两条能力用它（都走 harness-create）；
   * 切到评估或技能类时 chip 不显示，值保留但提交时忽略。
   */
  const [knowledge, setKnowledge] = useState<KnowledgeWorkflow | null>(null);
  /**
   * 用户在这页动过 chip 没有。
   *
   * 「优化智能体」要把它写进目标智能体的配置；但首页的初值就是 `null`（没选），
   * 与「用户点了 ×」长得一样 —— 不记这一笔，优化时就会把目标智能体原有的配置误清掉。
   * 创建不需要：选择已经随首条消息的参数落库（服务端解析）。
   */
  const [knowledgeTouched, setKnowledgeTouched] = useState(false);
  const changeKnowledge = useCallback((next: KnowledgeWorkflow | null) => {
    setKnowledge(next);
    setKnowledgeTouched(true);
  }, []);
  const supportsKnowledge = capability === 'agent.create' || capability === 'agent.optimize';

  /**
   * 正文的 ref 版。
   *
   * 目标 chip 那个 effect **不能依赖 draft**：它每敲一个字就变，effect 会重插 token
   * 并把光标拽到末尾（输入直接被打断）。所以 effect 只看能力 / 目标 / fill，
   * 需要正文时从 ref 里现取。目标清单（`agents` / `skills`）同理走各自的 ref ——
   * 清单是异步到的，把它放进依赖里，用户正打字时清单一到就会重插 chip、拽走光标。
   */
  const draftRef = useRef('');
  draftRef.current = draft;

  /** 往框里放「能力 chip + 正文」 */
  const fillWith = useCallback(
    (key: CapabilityKey, text: string) => {
      fillSeq.current += 1;
      setFill({
        key: fillSeq.current,
        text,
        command: { value: t(capabilityDef(key).labelKey) },
      });
    },
    [t],
  );

  /**
   * 进页面就摆一颗默认能力 chip。
   *
   * 默认是 `agent.create`；带 `state.capability` 进来时预选那一条（目前只有工坊
   * 「新会话」会带 `skill.create`）。认不出的值一律回落到默认，不把 chip 空着。
   *
   * 放在父组件 effect 里而不是初次渲染的 fill 初值：Composer 的 fill effect 在子组件
   * 里跑，父组件的 effect 一定在它之后 —— 首次挂载时编辑器已经就位，这次 fill 不会被跳过。
   */
  useEffect(() => {
    const requested = (location.state as HomeLocationState | null)?.capability;
    const initial: CapabilityKey =
      requested !== undefined && CAPABILITIES.some((cap) => cap.key === requested)
        ? requested
        : 'agent.create';
    setCapability(initial);
    fillWith(initial, '');
    // 只在挂载时放一次；之后由用户切能力 / 点卡片切换
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * 切换能力（chip 菜单与下面的能力卡共用）：剥掉旧 chip 的字面量，再用新 chip + 正文重填。
   *
   * 只换命令，不动这一轮的内容：正文原样保留，目标只在与新能力不匹配时才清掉。
   */
  function selectCapability(next: CapabilityKey) {
    const rest = stripCapabilityLabel(draft, t(capabilityDef(capability).labelKey));
    setCapability(next);
    setCapMenuOpen(false);
    setError(null);
    if (capabilityDef(next).target !== 'agent') setAgentTarget(null);
    if (capabilityDef(next).target !== 'skill') setSkillTarget(null);
    fillWith(next, rest);
  }

  /** 「添加文件」的选择器：首页与创建页共用一份，选择器自己只管回一个绝对路径 */
  const pickerFile = useFilePicker();
  const pickFile = useCallback(async () => {
    const path = await pickerFile.pickFile();
    return path === null ? null : attachmentOfPath(path);
  }, [pickerFile.pickFile]);

  /** 打字同样清掉上一轮的错误：用户已经在改了，旧结论就不作数 */
  function handleChange(value: string) {
    /*
     * 同值不算「在改」：发送失败时 Composer 会把这一轮原样回写（见它的 restorePayload），
     * 那不是用户的新输入 —— 顺手清错误会把刚弹出来的失败原因自己抹掉。
     */
    if (value === draft) return;
    setDraft(value);
    if (error !== null) setError(null);
  }

  /**
   * 发送框内容变化（正文或附件）。只记下来给吉祥物用，不在这里清错误：
   * 附件变化并不改变「为什么发不出去」，清了反而让用户看不到原因。
   */
  function handleContentChange(next: boolean) {
    setHasContent(next);
  }

  /*
   * 点 / 键盘激活正文里的能力 chip → 展开五选一菜单。
   * chip 是 Composer 建的 DOM token，不经过 React；这里用事件委托认它
   * （目标 chip / 「选择目标」chip 各自开自己的弹层，不在这里接管）。
   */
  useEffect(() => {
    const wrap = inputWrapRef.current;
    if (wrap === null) return;
    const capabilityChipOf = (event: Event): HTMLElement | null => {
      const chip = (event.target as HTMLElement | null)?.closest<HTMLElement>('.command-chip') ?? null;
      return chip !== null &&
        !chip.classList.contains('command-chip--target') &&
        !chip.classList.contains('command-chip--add')
        ? chip
        : null;
    };
    const onClick = (event: MouseEvent) => {
      if (capabilityChipOf(event) === null) return;
      event.preventDefault();
      setCapMenuOpen((open) => !open);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      if (capabilityChipOf(event) === null) return;
      event.preventDefault();
      setCapMenuOpen((open) => !open);
    };
    wrap.addEventListener('click', onClick);
    wrap.addEventListener('keydown', onKeyDown);
    return () => {
      wrap.removeEventListener('click', onClick);
      wrap.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  /*
   * 菜单打开时把焦点送进第一项；关闭时还回能力 chip。
   * 同时维护 chip 的 aria-expanded —— chip 是 DOM token，React 只在这里补状态。
   */
  useEffect(() => {
    const chip = inputWrapRef.current?.querySelector<HTMLElement>('[data-token-kind="command"]');
    chip?.setAttribute('aria-expanded', String(capMenuOpen));
    if (capMenuOpen) {
      capMenuRef.current?.querySelector<HTMLButtonElement>('.home__cap-item')?.focus();
    } else if (wasCapMenuOpenRef.current) {
      chip?.focus();
    }
    wasCapMenuOpenRef.current = capMenuOpen;
  }, [capMenuOpen, chipEpoch, capability]);

  /*
   * 能力 chip **不能被删掉**：它是这一轮能力的可见载体。CSS 只藏掉了 ×，
   * 键盘仍能把它删掉（贴着它按 Backspace / Delete、全选后删除、Ctrl+X），
   * 所以这里在 DOM 上兜底：不管谁把它拿掉了，都在正文最前面补回来。
   *
   * 「补回来」分两种情形：
   *   - 正文里只剩需求（用户直接删了 token）→ 在开头插 token；
   *   - 正文开头还留着 chip 的字面量（发送失败时 Composer 把正文原样回写，
   *     token 已经变成普通文字）→ 把那段字面量换回 token，别让标签出现两遍。
   *
   * 观察器只看「有没有 command token」，Composer 自己的 fill / 回写都会带 token
   * 或带着同样的字面量，走到这里时结果一致，不会来回打架。
   */
  useEffect(() => {
    const editor = inputWrapRef.current?.querySelector<HTMLElement>('.composer__editor');
    if (editor === null || editor === undefined) return;

    const label = t(capabilityDef(capability).labelKey);
    const ensureChip = () => {
      const existing = editor.querySelector<HTMLElement>('[data-token-kind="command"]');
      if (existing !== null) {
        /*
         * 语言切换：token 里存的是建它那一刻的 label（可见文字与 `data-token-text`
         * 各一份）。这里**不重建节点**，只把两处字面量换掉 —— 重建会把光标甩到
         * 末尾，也会把用户已经写好的正文拆开。
         *
         * 换完补一次 `input`，让 Composer 走同一条上报路径把父组件的 value 同步到
         * 新文案：否则 `stripCapabilityLabel` 还按新语言的 label 去剥旧文案，剥不掉，
         * 旧语言的能力名就混进 prompt 与取名里。
         */
        if (existing.getAttribute('data-token-text') !== label) {
          existing.setAttribute('data-token-text', label);
          existing.title = label;
          const name = existing.querySelector('.command-chip__name');
          if (name !== null) name.textContent = label;
          editor.dispatchEvent(new Event('input', { bubbles: true }));
        }
        return;
      }

      const chip = buildCapabilityChip(label);
      const first = editor.firstChild;

      /* 开头是残留下来的 chip 字面量？（Composer 回写正文时 token 会退化成纯文字） */
      if (first !== null && first.nodeType === Node.TEXT_NODE) {
        const leading = first.textContent ?? '';
        if (leading.trimStart().startsWith(label)) {
          first.textContent = leading.trimStart().slice(label.length).trimStart();
          editor.insertBefore(chip, first);
          // 后面还有需求才补空格；只剩 chip 时不留一个孤零零的空白
          if ((first.textContent ?? '') !== '') {
            editor.insertBefore(document.createTextNode(' '), first);
          }
          setChipEpoch((epoch) => epoch + 1);
          return;
        }
      }

      editor.insertBefore(chip, editor.firstChild);
      editor.insertBefore(document.createTextNode(' '), editor.firstChild);
      setChipEpoch((epoch) => epoch + 1);
    };

    /*
     * 键盘上贴着 chip 的那两下（光标在它后面按 Backspace / 在它前面按 Delete）
     * 直接吃掉，不让它先删再补：补回来的同时光标会被甩到正文末尾，
     * 用户在开头删空行会觉得「删了却跳到结尾」。
     *
     * **全选删除不拦**：拦了就连正文都清不掉；那种情况交给下面的观察器把 chip 放回去
     * （其余内容照常删掉）。
     */
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Backspace' && event.key !== 'Delete') return;
      if (event.defaultPrevented || event.isComposing) return;
      const selection = window.getSelection();
      if (selection === null || selection.rangeCount === 0) return;
      const range = selection.getRangeAt(0);
      if (!range.collapsed) return;
      const chip = editor.querySelector('[data-token-kind="command"]');
      if (chip === null) return;
      const side = caretAdjacent(range, editor, chip);
      if (
        (event.key === 'Backspace' && side === 'after') ||
        (event.key === 'Delete' && side === 'before')
      ) {
        event.preventDefault();
      }
    };
    editor.addEventListener('keydown', onKeyDown);

    const observer = new MutationObserver(ensureChip);
    observer.observe(editor, { childList: true, subtree: true, characterData: true });
    // 初次挂载 / 换能力后也确认一次（fill 可能因为 key 相同被 Composer 跳过）
    ensureChip();

    return () => {
      editor.removeEventListener('keydown', onKeyDown);
      observer.disconnect();
    };
  }, [capability, t]);

  /*
   * 目标也长在正文里：能力 chip 后面紧跟一颗「专家：X / 技能：X」的 token。
   *
   * 它带 `data-token-kind="target"`（不是 `command`），`readEditorText` 只认 `command`，
   * 所以目标不会混进发给会话的正文 —— 展示在框里，语义在状态里。
   * 没有目标时摆一颗虚线「＋选择…」，点它重开选择器；这颗**不能被删**，
   * 否则用户就只剩「删了没法加回来」——见下面 add 分支里的键位拦截与观察器。
   */
  useEffect(() => {
    const editor = inputWrapRef.current?.querySelector<HTMLElement>('.composer__editor');
    if (editor === null || editor === undefined) return;

    editor
      .querySelectorAll('[data-token-kind="target"], [data-token-kind="target-add"]')
      .forEach((node) => node.remove());

    const def = capabilityDef(capability);
    if (def.target === null) return;

    const isAgent = def.target === 'agent';
    const name = isAgent ? agentTarget?.name : skillTarget?.name;

    const openTargetPicker = () => {
      const text = stripCapabilityLabel(draftRef.current, t(def.labelKey));
      // 候选清单从 ref 现取（而不是 effect 闭包里的 state）：清单异步到达不该让这个
      // effect 重跑 —— 重跑会重插 chip 并把光标拽到末尾，打断正在打的字。
      setPicker(
        isAgent
          ? { kind: 'agent', mode: 'select', text, attachments: [], options: agentsRef.current ?? [] }
          : { kind: 'skill', mode: 'select', text, attachments: [], options: skillsRef.current ?? [] },
      );
    };

    /** 插在能力 chip 后面（能力 chip 不存在时放最前） */
    const insertAfterCapability = (node: Node) => {
      const capToken = editor.querySelector('[data-token-kind="command"]');
      if (capToken !== null) {
        const space = document.createTextNode(' ');
        editor.insertBefore(space, capToken.nextSibling);
        editor.insertBefore(node, space.nextSibling);
      } else {
        editor.insertBefore(node, editor.firstChild);
        editor.insertBefore(document.createTextNode(' '), editor.firstChild);
      }
    };

    if (name === undefined) {
      const add = document.createElement('span');
      add.className = 'command-chip command-chip--add';
      add.contentEditable = 'false';
      add.tabIndex = 0;
      add.setAttribute('role', 'button');
      add.setAttribute('aria-haspopup', 'dialog');
      add.setAttribute('data-token-id', `add-${Date.now().toString(36)}`);
      add.setAttribute('data-token-kind', 'target-add');
      add.textContent = t(isAgent ? 'home.target.pickAgent' : 'home.target.pickSkill');
      add.setAttribute('aria-label', add.textContent);
      add.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        openTargetPicker();
      });
      add.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        event.stopPropagation();
        openTargetPicker();
      });
      insertAfterCapability(add);

      /*
       * 光标放到「＋ 选择…」之后（正文最末尾）。
       *
       * fill 写回正文时把光标放在末尾，但那一刻这颗 chip 还没插进来 —— 光标就卡在了
       * 能力 chip 后面，用户一打字落在两颗 chip 中间，而不是当成需求。
       *
       * 定位用最后一个文本节点，不用 (editor, n)：DIV 级偏移在 Chrome 里落不准，
       * 正是它把上一版的光标钉在了能力 chip 后面。
       */
      const selection = window.getSelection();
      if (document.activeElement === editor && selection !== null && selection.isCollapsed) {
        if (editor.lastChild === null || editor.lastChild.nodeType !== Node.TEXT_NODE) {
          editor.appendChild(document.createTextNode(' '));
        }
        const last = editor.lastChild as Text;
        const caret = document.createRange();
        caret.setStart(last, last.textContent?.length ?? 0);
        caret.collapse(true);
        selection.removeAllRanges();
        selection.addRange(caret);
      }

      /*
       * 「＋ 选择目标」这颗也不能被删掉：它是这一轮唯一的选目标入口，删了就再也加不回来
       * （能力的 chip 另有兜底，这里只认自己这颗）。
       *
       * 与能力 chip 同一套办法：贴着它的 Backspace / Delete 直接吃掉；
       * 选中后删除、拖动等其余删法由观察器放回去。全选删除不拦（正文总得能清），
       * 交给观察器 —— 能力 chip 那边也会同时把自己补回来。
       */
      const onKeyDown = (event: KeyboardEvent) => {
        if (event.key !== 'Backspace' && event.key !== 'Delete') return;
        if (event.defaultPrevented || event.isComposing) return;
        const selection = window.getSelection();
        if (selection === null || selection.rangeCount === 0) return;
        const range = selection.getRangeAt(0);
        if (!range.collapsed) return;
        const side = caretAdjacent(range, editor, add);
        if (
          (event.key === 'Backspace' && side === 'after') ||
          (event.key === 'Delete' && side === 'before')
        ) {
          event.preventDefault();
        }
      };
      editor.addEventListener('keydown', onKeyDown);

      const observer = new MutationObserver(() => {
        if (editor.querySelector('[data-token-kind="target-add"]') !== null) return;
        insertAfterCapability(add);
      });
      observer.observe(editor, { childList: true });

      return () => {
        editor.removeEventListener('keydown', onKeyDown);
        observer.disconnect();
      };
    }

    const label = t(isAgent ? 'home.target.agent' : 'home.target.skill', { name });
    const token = document.createElement('span');
    token.className = 'command-chip command-chip--target';
    token.contentEditable = 'false';
    token.setAttribute('data-token-id', `tgt-${Date.now().toString(36)}`);
    token.setAttribute('data-token-kind', 'target');
    token.title = label;

    // 名字本身就是「重开选择器」的键盘落点；token 上仍保留鼠标点击（点空白处也能开）
    const text = document.createElement('button');
    text.type = 'button';
    text.className = 'command-chip__name command-chip__name--action';
    text.textContent = label;
    text.setAttribute('aria-label', label);
    text.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      openTargetPicker();
    });

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'command-chip__x';
    remove.setAttribute('aria-label', t('common.remove', { name: label }));
    remove.textContent = '×';
    remove.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (isAgent) setAgentTarget(null);
      else setSkillTarget(null);
    });

    token.append(text, remove);
    token.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      openTargetPicker();
    });

    insertAfterCapability(token);

    // 选完目标把光标放到末尾：接着写需求，而不是插在 token 前面
    editor.focus();
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  }, [capability, agentTarget, skillTarget, fill, t, chipEpoch]);

  /**
   * 提交这一轮：能力来自 chip，正文只承载需求。
   *
   * 返回 false 时 Composer 会把正文与附件原样还回输入框 ——
   * 「没选目标」也走这条，用户不会因为弹了一次选择器就丢了刚写的话。
   */
  async function submit(payload: ComposerSubmit): Promise<boolean> {
    if (submitting) return false;

    const def = capabilityDef(capability);
    const text = stripCapabilityLabel(payload.text, t(def.labelKey));
    const attachments = payload.attachments.map((file) => file.name);

    /*
     * 输入框不再承载命令：写了 /xxx 当成「用户还在用旧心智」，直接说清楚。
     * 五类能力一视同仁 —— 优化场的要求是自然语言专家指引（拼进 `--expert-guidance`），
     * 也不该以 `/` 开头。
     */
    if (/^\s*\//u.test(text)) {
      setError(t('home.error.slashCommand'));
      return false;
    }
    if (sendBlockedReason !== null) return false;

    setError(null);

    /*
     * 选了知识检索就必须写需求：参数是拼在命令后面的，正文为空时首条消息根本不带命令，
     * 知识库会静默丢失（只挂附件也一样）。
     */
    if (supportsKnowledge && knowledge !== null && text === '') {
      setError(t('knowledge.needsPrompt'));
      return false;
    }

    switch (capability) {
      case 'agent.create':
        return createAgent(text, attachments);

      case 'agent.optimize': {
        const list = await loadAgents();
        if (list === null) return false;
        if (list.length === 0) {
          setError(t('home.error.noAgentToOptimize'));
          return false;
        }
        const resolved = agentTarget
          ? ({ kind: 'direct', item: agentTarget } as const)
          : resolveAgent(text, list);
        if (resolved.kind === 'pick') {
          setPicker({ kind: 'agent', mode: 'submit', text, attachments, options: resolved.matches });
          setError(t('home.error.needTarget'));
          return false;
        }
        return optimizeAgent(resolved.item, text, attachments);
      }

      case 'skill.create':
        /*
         * 工坊自己拼 `/agent-genesis:skill-foundry …` 前缀（capability-routing.md §3.3），
         * 首页只交用户写的正文，别在这里再拼一遍命令。
         */
        navigate('/workshop', { state: { firstPrompt: text, attachments } });
        return true;

      case 'skill.evolve': {
        const list = await loadSkills();
        if (list === null) return false;
        if (list.length === 0) {
          setError(t('home.error.noSkill'));
          return false;
        }
        const resolved = skillTarget
          ? ({ kind: 'direct', item: skillTarget } as const)
          : resolveByName(text, list, (skill) => skill.name);
        if (resolved.kind === 'pick') {
          setPicker({ kind: 'skill', mode: 'submit', text, attachments, options: resolved.matches });
          setError(t('home.error.needTarget'));
          return false;
        }
        openSkill(resolved.item, text, attachments);
        return true;
      }

      case 'agent.evaluate': {
        const list = await loadAgents();
        if (list === null) return false;
        if (list.length === 0) {
          setError(t('home.error.noAgent'));
          return false;
        }
        const resolved = agentTarget
          ? ({ kind: 'direct', item: agentTarget } as const)
          : resolveAgent(text, list);
        if (resolved.kind === 'pick') {
          setPicker({ kind: 'agent', mode: 'submit', text, attachments, options: resolved.matches });
          setError(t('home.error.needTarget'));
          return false;
        }
        openAgent(resolved.item, text, attachments);
        return true;
      }
    }
  }

  /** 提交时要清单：拉失败就把原始原因套成一句人话摆在发送框下面 */
  async function loadAgents(): Promise<Agent[] | null> {
    try {
      return await ensureAgents();
    } catch (err) {
      setAgentError(describeTargetError(err));
      setError(t('home.target.loadFailed', { error: describeTargetError(err) }));
      return null;
    }
  }

  async function loadSkills(): Promise<Skill[] | null> {
    try {
      return await ensureSkills();
    } catch (err) {
      setSkillError(describeTargetError(err));
      setError(t('home.target.loadFailed', { error: describeTargetError(err) }));
      return null;
    }
  }

  /**
   * 创建智能体：登记身份 → 跳设计页。
   *
   * 能力 chip 的字面量（「创建智能体」）不是命令，真正要发给会话的是
   * `/agent-genesis:harness-create <正文>` —— 命令在这里补，别让用户手写。
   */
  async function createAgent(text: string, attachments: string[]): Promise<boolean> {
    if (text === '' && attachments.length === 0) {
      setError(t('home.error.needPrompt'));
      return false;
    }
    setSubmitting(true);
    // 命令 + 可选知识检索参数 + 需求；正文为空时整条不发（避免空命令）
    const prompt = text === '' ? '' : composeHarnessPrompt(text, knowledge?.id ?? null);
    try {
      // 取名与撞名的改写都在 create-agent 里（会剥掉开头命令再取名）
      const agent = await createAgentFromPrompt(prompt, modelId, attachments);
      navigate(`/agents/${agent.id}/design`, {
        state: {
          firstPrompt: prompt,
          initSessionId: agent.initSessionId,
          // 端侧形态下附件就是路径；服务端在发送时再校验一遍
          attachments,
          // 后端会异步把兜底元数据刷成 AI 版；设计页拿它当基线，变了就重读详情
          metaBaseline: agent.updatedAt,
        },
      });
      return true;
    } catch (err) {
      setError(describeCreateError(err));
      // 成功那条路不用复位：`navigate` 一走这个组件就卸载了
      setSubmitting(false);
      return false;
    }
  }

  /**
   * 技能优化的落点：库技能进工坊；智能体技能回它的设计页（replay，不自动发）。
   *
   * 两条路拼的是**同一句命令**（`composeOptimizeMessage`）：智能体技能也是技能，
   * 用户点了「优化」就该拿到能跑的 skill_optimize，而不是一句自然语言让他自己补命令。
   */
  function openSkill(skill: Skill, text: string, attachments: string[]) {
    if (skill.source === 'agent' && skill.ownerAgentId !== null) {
      const replayText = composeOptimizeMessage(skillMdPath(skill), text);
      // design 页读 `location.state.replay`，只把话放进发送框（capability-routing.md §5.2）
      navigate(`/agents/${skill.ownerAgentId}/design`, {
        /*
         * 附件跟着话一起交接：这条路径与库技能那条一样，用户是「带着材料」发起的
         * 优化 —— 漏掉附件等于悄悄改了这次请求的内容，而且界面上看不出来。
         */
        state: { replay: { text: replayText, paths: attachments } },
      });
      return;
    }
    const params = new URLSearchParams({ target: skill.path, name: skill.name });
    navigate(`/workshop?${params.toString()}`, {
      state: { firstPrompt: text, attachments },
    });
  }

  /**
   * 优化智能体的落点：它自己的设计页，`harness-create` 命令 + 需求**到页即发**。
   *
   * 与「创建智能体」是**同一个技能**，但这里不新建身份：目标已经存在，改的是它自己的
   * 产物。不用 `firstPrompt` 那条路 —— 它只在目标会话为空时补发（创建语义），
   * 已有智能体的开发会话有历史，走那条什么都不会发。所以走 replay 管道并带
   * `autoSend`：设计页把它发进最近一场开发会话，会话准备好就发。
   *
   * 正文可以为空：命令本身就是一次完整的调用，harness-create 会接着问要改哪儿。
   */
  async function optimizeAgent(agent: Agent, text: string, attachments: string[]): Promise<boolean> {
    // 用户在这页改过知识检索：先写进目标智能体的配置，设计页才会按它改写这条消息。
    // 写失败就不发 —— 否则消息里的参数会被设计页按旧配置覆盖，用户的选择静默丢失。
    if (knowledgeTouched) {
      try {
        await agentsApi.update(agent.id, { knowledgeWorkflowId: knowledge?.id ?? '' });
      } catch (err) {
        setError(
          t('knowledge.saveFailed', {
            error: err instanceof Error ? err.message : String(err),
          }),
        );
        return false;
      }
    }

    const base = [capabilityDef('agent.optimize').command, text]
      .filter((part) => part !== '')
      .join(' ');
    // 优化与创建共用一条命令；选了知识检索时同样把参数拼在命令后面
    const prompt = withKnowledgeFlag(base, knowledge?.id ?? null);
    navigate(`/agents/${agent.id}/design`, {
      state: { replay: { text: prompt, paths: attachments, autoSend: true } },
    });
    return true;
  }

  /**
   * 评估的落点：设计页的评估阶段，**停掉旧会话、重开一场再立刻开跑**（同「重新评估」）。
   *
   * 发的是「评估技能的命令 + 用户在首页写的要求」：`agent-eval` 才是真正跑评估的技能，
   * 只把要求放进发送框，用户按下去也只是一句普通消息，技能根本不会执行。
   * 命令与评估阶段的「开始评估」按钮同源（`evalKickoffPrompt`），别在这里另写一份。
   *
   * `newSession` = 不复用最近一场评估会话：服务端建会话时带着 `resetSandbox` 重建
   * 沙箱（旧报告一并删掉），和用户点「重新评估」是同一个动作。旧的一轮还在跑时，
   * 评估阶段会先停掉它再重开（防止 409 退回旧会话）。
   *
   * 走 replay 而不是 `firstPrompt`：后者是「建会话后补发」的 development 载荷，
   * 评估页不消费，切回生成阶段时反而会被当成首轮发出去。
   */
  function openAgent(agent: Agent, text: string, attachments: string[]) {
    const prompt = [evalKickoffPrompt(), text].filter((part) => part !== '').join(' ');
    navigate(`/agents/${agent.id}/design?stage=evaluation`, {
      state: { replay: { text: prompt, paths: attachments, autoSend: true, newSession: true } },
    });
  }

  function pickTarget(option: PickerOption) {
    const state = picker;
    if (state === null) return;
    setPicker(null);
    setError(null);

    if (state.kind === 'agent') {
      const agent = state.options.find((item) => item.id === option.id);
      if (agent === undefined) return;
      // select：只定目标，留在首页继续写要求
      if (state.mode === 'select') {
        setAgentTarget(agent);
        return;
      }
      // 同一个选择器服务两条能力：优化落到设计页继续改，评估落到评估阶段
      if (capability === 'agent.optimize') void optimizeAgent(agent, state.text, state.attachments);
      else openAgent(agent, state.text, state.attachments);
      return;
    }

    const skill = state.options.find((item) => item.path === option.id);
    if (skill === undefined) return;
    if (state.mode === 'select') {
      setSkillTarget(skill);
      return;
    }
    openSkill(skill, state.text, state.attachments);
  }

  /** 目标 chip 的标签：选中的目标 + 正文里认出来的那一个（提交前让用户看见路由结论） */
  const demand = stripCapabilityLabel(draft, t(capabilityDef(capability).labelKey));
  const resolvedPreview = (() => {
    if (capability === 'agent.evaluate' && agentTarget === null && agents !== null) {
      const resolved = resolveAgent(demand, agents);
      return resolved.kind === 'direct' ? t('home.resolvedAgent', { name: resolved.item.name }) : null;
    }
    if (capability === 'agent.optimize' && agentTarget === null && agents !== null) {
      const resolved = resolveAgent(demand, agents);
      return resolved.kind === 'direct'
        ? t('home.resolvedAgentOptimize', { name: resolved.item.name })
        : null;
    }
    if (capability === 'skill.evolve' && skillTarget === null && skills !== null) {
      const resolved = resolveByName(demand, skills, (skill) => skill.name);
      return resolved.kind === 'direct' ? t('home.resolvedSkill', { name: resolved.item.name }) : null;
    }
    return null;
  })();

  const pickerPane = (() => {
    if (picker === null) return null;
    if (picker.kind === 'agent') {
      // 同一个选择器服务优化 / 评估：标题跟着本轮能力走，别让优化的人看到「选择要评估的」
      const optimizing = capability === 'agent.optimize';
      return (
        <TargetPicker
          title={t(optimizing ? 'home.target.pickOptimizeAgentTitle' : 'home.target.pickAgentTitle')}
          desc={t(optimizing ? 'home.target.pickOptimizeAgentDesc' : 'home.target.pickAgentDesc')}
          searchPlaceholder={t('home.target.searchAgent')}
          loading={agentLoading}
          error={agentError === null ? null : t('home.target.loadFailed', { error: agentError })}
          options={picker.options.map(agentOption)}
          onPick={pickTarget}
          onCancel={() => {
            setPicker(null);
            setError(null);
          }}
        />
      );
    }
    return (
      <TargetPicker
        title={t('home.target.pickSkillTitle')}
        desc={t('home.target.pickSkillDesc')}
        searchPlaceholder={t('home.target.searchSkill')}
        loading={skillLoading}
        error={skillError === null ? null : t('home.target.loadFailed', { error: skillError })}
        options={picker.options.map(skillOption)}
        onPick={pickTarget}
        onCancel={() => {
          setPicker(null);
          setError(null);
        }}
      />
    );
  })();

  return (
    <section className="home">
      <div className="home__inner">
        <h1 className="home__greeting">{t('home.greeting')}</h1>
        <p className="home__desc">{t('home.description')}</p>

        <div className="home__composer">
          {/* 吉祥物挂在卡片角上，position: relative 的这个包裹层就是它的锚点 */}
          <div className="home__input-wrap" ref={inputWrapRef}>
            <Mascot awake={hasContent} />
            <Composer
              variant="hero"
              chipPlacement="inline"
              value={draft}
              onChange={handleChange}
              onSubmit={submit}
              onContentChange={handleContentChange}
              disabled={submitting}
              status={submitting ? t('home.creating') : undefined}
              sendBlockedReason={sendBlockedReason}
              placeholder={t('home.inputPlaceholder')}
              pickFile={pickFile}
              fill={fill}
              model={{
                value: modelId,
                options: models.map((m) => ({ value: m.id, label: m.label })),
                onChange: setModelId,
                // 清单的三种状态（加载中 / 失败 / 空）由 Composer 表达，两页一致
                loading: modelsLoading,
                error: modelsError,
              }}
              /*
               * 知识检索：只有创建 / 优化智能体挂（都走 harness-create）。
               * 位置固定在工具栏左侧 `+` 之后，与生产会话同一颗 chip。
               */
              accessory={
                supportsKnowledge ? (
                  <KnowledgeSelect value={knowledge} onChange={changeKnowledge} disabled={submitting} />
                ) : undefined
              }
            />

            {/*
              能力 chip 在正文流里（Composer 的行内 token），点它才展开这层菜单。
              菜单只是「换个 chip」，不占输入框的版面。
            */}
            {capMenuOpen && (
              <>
                <div className="home__cap-mask" aria-hidden="true" onClick={() => setCapMenuOpen(false)} />
                <div
                  ref={capMenuRef}
                  id="home-capability-menu"
                  className="home__cap-menu"
                  role="listbox"
                  aria-label={t('home.capabilityMenuLabel')}
                  onKeyDown={(event) => {
                    if (event.key !== 'Escape') return;
                    event.preventDefault();
                    setCapMenuOpen(false);
                  }}
                  onBlur={(event) => {
                    const next = event.relatedTarget;
                    // 点能力 chip 本身交给它的 click 翻转，别在这里先关再被打开
                    if (next instanceof Element && next.closest('[data-token-kind="command"]') !== null) return;
                    // 焦点离开菜单就收起：菜单不是模态层，Tab 出去后不该留在原地
                    if (!(next instanceof Node) || !event.currentTarget.contains(next)) {
                      setCapMenuOpen(false);
                    }
                  }}
                >
                  {CAPABILITIES.map((cap) => {
                    const active = cap.key === capability;
                    return (
                      <button
                        key={cap.key}
                        type="button"
                        role="option"
                        aria-selected={active}
                        className={`home__cap-item${active ? ' is-active' : ''}`}
                        onClick={() => selectCapability(cap.key)}
                      >
                        <span
                          className="home__cap-item__icon"
                          style={{ background: `${cap.tint}18`, color: cap.tint }}
                        >
                          <Icon name={cap.icon} size={13} />
                        </span>
                        <span className="home__cap-item__body">
                          <b>{t(cap.labelKey)}</b>
                          <em>{t(cap.subKey)}</em>
                        </span>
                        {active && (
                          <span className="home__cap-item__check">
                            <Icon name="check" size={12} />
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          {/* 文件选择器自带 dialog；挂在这里，关闭时不渲染任何节点 */}
          {pickerFile.element}

          {resolvedPreview !== null && (
            <p className="home__resolved">
              <Icon name="search" size={12} />
              {resolvedPreview}
            </p>
          )}

          {error !== null && (
            <p className="home__error" role="alert">
              <Icon name="alert" size={13} />
              {error}
            </p>
          )}

          <p className="home__hint">
            <Icon name="terminal" size={12} />
            {t('home.capabilityHint')}
          </p>

          {/*
            五张能力卡：点一下 = 切到这条能力（与 chip 菜单同一动作，不预填需求）。
            卡片上**不展示命令**（用户不用记、也不该自己写 `/`）；命令只在提交时由页面拼。
          */}
          <div className="home__caps" role="group" aria-label={t('home.capabilitiesLabel')}>
            {CAPABILITIES.map((cap) => (
              <button
                key={cap.key}
                type="button"
                className={`home__cap${cap.key === capability ? ' is-active' : ''}`}
                onClick={() => selectCapability(cap.key)}
              >
                <span
                  className="home__cap-icon"
                  style={{ background: `${cap.tint}18`, color: cap.tint }}
                >
                  <Icon name={cap.icon} size={16} />
                </span>
                <span className="home__cap-body">
                  <span className="home__cap-label">{t(cap.labelKey)}</span>
                  <span className="home__cap-sub">{t(cap.subKey)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {pickerPane}
    </section>
  );
}

/**
 * 手搓一颗能力 chip，与 Composer 的命令 token 同构。
 *
 * Composer 的 `buildCommandToken` 不对外导出，而这里只需要「不能被删、能被读回」的最小一份：
 * 字面量放 `data-token-text`（`readEditorText` 认它，提交时再剥掉），
 * **不挂 ×** —— 能力在这一轮里是固定的，不给删除入口。
 */
function buildCapabilityChip(label: string): HTMLElement {
  const token = document.createElement('span');
  token.className = 'command-chip';
  token.contentEditable = 'false';
  // token 是原子的 contenteditable=false 节点，默认不在 Tab 序列里；
  // 显式给它一个键盘落点，Enter / Space 由页面的委托监听打开能力菜单。
  token.tabIndex = 0;
  token.setAttribute('role', 'button');
  token.setAttribute('aria-haspopup', 'listbox');
  token.setAttribute('aria-expanded', 'false');
  token.setAttribute('aria-controls', 'home-capability-menu');
  token.setAttribute('aria-label', label);
  token.setAttribute('data-token-id', `cap-${Date.now().toString(36)}`);
  token.setAttribute('data-token-kind', 'command');
  token.setAttribute('data-token-text', label);
  token.title = label;

  const name = document.createElement('span');
  name.className = 'command-chip__name';
  name.textContent = label;
  token.append(name);
  return token;
}

/**
 * 光标是否正好停在这个节点**前面**（Delete 会删它）或**后面**（Backspace 会删它）。
 *
 * 只看折叠光标：有选区时按删除是用户明确要清一段，交给观察器兜底，不在键盘上拦。
 * 三种落点都要认 —— 直接在编辑器层（`container === editor`）、以及紧贴在 chip 两侧的
 * 文本节点里（光标在文本开头 / 结尾）。
 */
function caretAdjacent(
  range: Range,
  editor: HTMLElement,
  node: Node,
): 'before' | 'after' | null {
  if (!range.collapsed) return null;
  const { startContainer: container, startOffset: offset } = range;

  if (container === editor) {
    const index = Array.prototype.indexOf.call(editor.childNodes, node);
    if (index < 0) return null;
    if (offset === index) return 'before';
    if (offset === index + 1) return 'after';
    return null;
  }

  if (container.nodeType === Node.TEXT_NODE) {
    const text = container.textContent ?? '';
    if (offset === 0 && container.previousSibling === node) return 'after';
    if (offset === text.length && container.nextSibling === node) return 'before';
  }

  return null;
}

/**
 * 正文里点名目标：按名字做「包含」匹配（大小写不敏感）。
 *
 * 恰好命中一个才算直接命中；命中多个是歧义（同名技能分两路就是这种情况，只列这几个）；
 * 一个都没命中就把**全量候选**摆出来 —— 选择器的默认用途就是「正文没说，用户来选」，
 * 摆一个空列表等于告诉用户「什么都选不了」。**空正文不会命中任何项**（`includes('')`
 * 是 true，但名字都不是空串，所以这里是安全的）。
 */
function resolveByName<T>(
  text: string,
  list: T[],
  nameOf: (item: T) => string,
): Resolution<T> {
  const needle = text.toLowerCase();
  const matches = list.filter((item) => needle.includes(nameOf(item).toLowerCase()));
  if (matches.length === 1) return { kind: 'direct', item: matches[0] };
  return {
    kind: 'pick',
    matches: matches.length === 0 ? list : matches,
    ambiguous: matches.length > 1,
  };
}

/** 智能体额外认显式 id（`agt_…` 是唯一标识，命中它不算「猜」） */
function resolveAgent(text: string, list: Agent[]): Resolution<Agent> {
  const id = text.match(/agt_[a-z0-9-]{6,}/i)?.[0];
  if (id !== undefined) {
    const hit = list.find((agent) => agent.id === id);
    if (hit !== undefined) return { kind: 'direct', item: hit };
  }
  return resolveByName(text, list, (agent) => agent.name);
}

/** 选择器的一行：专家 */
function agentOption(agent: Agent): PickerOption {
  return {
    id: agent.id,
    name: agent.name,
    description: agent.description,
    title: agent.id,
  };
}

/** 选择器的一行：技能（来源写在副行，同名两路靠它区分；目录路径进 title） */
function skillOption(skill: Skill): PickerOption {
  return {
    id: skill.path,
    name: skill.name,
    description: msg(
      skill.source === 'library' ? 'home.target.sourceLibrary' : 'home.target.sourceAgent',
    ),
    title: skill.path,
  };
}

/**
 * 目标清单拉失败：说清是哪一层的问题（后端没起 / 服务端给了人话 / 网络）。
 * 存储的是原始原因，展示时由 `home.target.loadFailed` 套上「读取失败：…」。
 */
function describeTargetError(err: unknown): string {
  if (err instanceof DOMException && err.name === 'AbortError') {
    return msg('home.error.timeout');
  }
  if (isBackendDown(err)) return backendDownHint();
  if (err instanceof ApiError) return err.message;
  return err instanceof Error ? err.message : msg('common.unknownError');
}

/**
 * 把创建失败翻译成能动手的话。
 *
 * 与列表页 `describeLoadError`、创建页 `describeAgentError` 同源：**「本地服务没起」是这一族
 * 里最像后端崩了的一种**，而首页是用户见到的第一个页面，含糊的报错会让人以为是建不出来。
 * 判据只有一处（`isBackendDown`）：响应根本不是 JSON。
 *
 * 创建特有的两种失败在这里点一下就走：
 * - 400 名称/描述超上限 —— 名字由 deriveName 截过、描述由 create-agent 截到 120，正常碰不到
 * - 409 重名 —— 同一句话发第二次就会撞上，但调用方已经换名重发过一次（见 create-agent），
 *   走到这里说明连挂短码的那次都撞上了。它抛上来的是自己写的人话，不是后端的原名冲突
 */
function describeCreateError(err: unknown): string {
  // 请求被中断 / 超时：与「后端说不行」不同，用户能动手的是网络或服务本身
  if (err instanceof DOMException && err.name === 'AbortError') {
    return msg('home.error.timeout');
  }
  if (isBackendDown(err)) {
    return msg('home.error.backendDown', { hint: backendDownHint() });
  }
  if (err instanceof ApiError) {
    return msg('home.error.detail', { error: err.message });
  }
  return err instanceof Error
    ? msg('home.error.detail', { error: err.message })
    : msg('home.error.retry');
}
