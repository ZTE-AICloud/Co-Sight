import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { msg, useI18n } from '../../i18n/useI18n';
import { backendDownHint, agentsApi, isBackendDown } from '../../shared/api/agents';
import type { Agent } from '../../shared/api/agents';
import { ApiError } from '../../shared/api/client';
import { useWorkspaces } from '../../shared/api/useWorkspaces';
import { Icon } from '../../shared/components/Icon';
import { frameworkBaseUrl, leaveToFramework } from '../../shared/framework';
import { SkillLibraryPanel } from '../skill-library/SkillLibraryPanel';
import { AgentCard } from './components/AgentCard';
import { AgentDetailDialog } from './components/AgentDetailDialog';
import { ConfirmDialog } from './components/ConfirmDialog';
import { EditAgentDialog } from './components/EditAgentDialog';
import { FilterSelect } from './components/FilterSelect';
import { TagFilter } from './components/TagFilter';
import type { SourceKey, StatusKey } from './display';
import { sourceFilters, sourceLabel, statusFilters, statusLabel } from './display';
import './agent-list.css';

/**
 * 专家 · 技能页：一屏可浏览的专家卡片，点卡片看详情，详情里能改名 / 删除。
 *
 * **2026-10-22 起技能库也长在这一页**，用 tab 切换（`?tab=skills`）。两个 tab 共用
 * 页头（标题 / tab 条 / 当前工作区徽标），内容各自取数：专家 tab 还是下面这套，
 * 技能 tab 是 `features/skill-library/SkillLibraryPanel`。`/skills` 这条老地址在
 * `App.tsx` 里重定向到 `?tab=skills`（首页快捷卡指向它）。
 *
 * 数据入口是 `shared/api/agents.ts`，后端就在本仓（`server/src/modules/agent/`，
 * 契约 `server/docs/05-openapi/5.01-agent-openapi.yaml`）—— 不再是 mock。
 * 版式照 `web/专家页面.png`：圆形封面头像 + 名称 + 简介。
 *
 * **本页只展示框架「当前生效工作区」里的智能体**（`useWorkspaces`）。一个工作区
 * 可以有多个智能体，但跨工作区的记录不混在一起；没有当前工作区时显示空态并停止
 * 取数，不拿列表第一项兜底。工作区的切换在框架界面完成，这里只显示、不提供切换器。
 *
 * **本页没有「新增」入口**：登记一个专家只有首页「创建智能体」那条路
 * （一句话 → 后端建身份 → 跳创建页）。两个入口的输入模型不一样（首页一句话、
 * 表单要填名称/简介/封面），留着迟早分叉成两套默认值；封面这类事后再编辑。
 *
 * 动作的落点（详情弹窗是只读信息层，不再挂动作条）：
 *   - 「构建」（卡底，2026-10-30 前叫「设计」）→ 设计页 `/agents/:agentId/design`
 *   - 「评估」（卡底）→ **同一个设计页**，地址带 `?stage=evaluation` 直接落在评估阶段；
 *     那页的对话本来就跑在评估沙箱里，不需要另开一个页面
 *   - 「使用」（卡底）→ **离开本模块**，整页跳框架首页（会话页），
 *     地址里带 `?expert=<智能体 id>`；地址口径与写法的理由见 `useExpertInFramework`
 *   - 编辑 / 删除由本页叠层：编辑弹窗 / 删除确认，叠在详情之上
 *
 * 本页也是前端三态（加载 / 空 / 错误）的样板，后续页面照抄。
 */

/**
 * 每页条数，取契约上限（5.00 的 PageSize：缺省 20、上限 200，超出按 200 截断）。
 *
 * 不调成后端缺省的 20：专家页是「一屏浏览」，200 以内根本不该出现翻页动作。
 * 于是分页控件也以它为界 —— **只有总数超过 200 才显示**（见 `total > PAGE_SIZE`）。
 */
const PAGE_SIZE = 200;

/** 搜索防抖：真正发出去的查询参数晚这么久跟上输入 */
const DEBOUNCE_MS = 250;

/**
 * 这一页的两个 tab（`capability-routing.md` 2026-10-22 改版后：技能库与专家列表同页）。
 *
 * tab 进地址（`?tab=skills`）而不是纯组件状态：刷新 / 从首页快捷卡进来要能直接落在
 * 技能库上。`?tab` 缺省 = 专家，所以 `/agents` 这条老地址行为不变。
 */
type CapabilityTab = 'experts' | 'skills';

const TAB_PARAM = 'tab';

/**
 * 「使用」＝去跟这个专家对话，而对话页在**框架**那边（宿主首页挂的是 conversation 模块）——
 * 所以这一步是**离开本模块**的整页跳转，不是模块内的一次路由。
 *
 * 地址带 `?expert=<智能体 id>`（如 `http://localhost:4310/?expert=…`）：框架首页把整条
 * 查询串原样转给会话模块（`framework/web` 的 `ModuleHost`），会话模块再把宿主参数翻成
 * 自己的 `agentId`（cosight-viewer 的 `host-params.ts`），于是进来就替用户选好了这个专家。
 * 前端只负责把 id 带上；这个 id 在框架 experts 表里能不能查到（模块回写）是链路另一头的事。
 *
 * 两件事都是**只能这么写**，不是随手定的：
 *
 * 1. **id 原样带，不做任何解析。** smart-factory 的智能体 id 是 `agt_<uuid>`（服务端生成，
 *    客户端不得拆解 —— 见 `shared/api/agents.ts`）。框架侧按同一个 id 找专家，两边是不是
 *    同一个空间由回写那条链路负责，前端不能靠"去前缀"/"拼前缀"来猜。
 * 2. **框架在哪个源、怎么整页跳** 由 `shared/framework.ts` 统一推（嵌态按 referrer 的源、
 *    单跑按 `VITE_FRAMEWORK_HOME_URL`；顶层跳转被沙箱拦下时回落成开新标签）。
 *    设计页「返回」用的是同一套口径，拆开写迟早会漂。
 */
function frameworkHomeUrl(expertId: string): string {
  /*
   * 用 URL 拼而不是字符串加 `?`：基址可能自带查询串（`VITE_FRAMEWORK_HOME_URL` 配成
   * 带参数的地址），`searchParams.set` 不会拼出两个问号，也不会覆盖掉别的参数。
   */
  const url = new URL(frameworkBaseUrl());
  url.searchParams.set('expert', expertId);
  return url.toString();
}

/** 把「使用某个专家」这件事交回框架。同步执行，理由见 `leaveToFramework` 的第 2 条。 */
function useExpertInFramework(expertId: string): void {
  leaveToFramework(frameworkHomeUrl(expertId));
}

export function AgentListPage() {
  const { t } = useI18n();
  const navigate = useNavigate();

  /**
   * 当前 tab。读地址而不是 `useState` —— 理由见 `CapabilityTab` 上面的注释。
   * `searchParams` 原样保留：将来给本页加别的查询参数时，切 tab 不该把它们丢掉。
   */
  const [searchParams] = useSearchParams();
  const tab: CapabilityTab = searchParams.get(TAB_PARAM) === 'skills' ? 'skills' : 'experts';
  /**
   * 技能 tab 访问过一次就保持挂载（用 hidden 藏起来）。
   * 条件卸载会把面板里的搜索词、筛选与滚动位置一起丢掉；首次不挂载则避免在专家 tab
   * 上白打一次 `GET /skills`。
   */
  const [skillsMounted, setSkillsMounted] = useState(tab === 'skills');
  /** 切回技能 tab 时让面板静默重拉一次（面板保持挂载，数据不会自己变新） */
  const [skillsRefresh, setSkillsRefresh] = useState(0);
  const prevTabRef = useRef<CapabilityTab | null>(null);
  useEffect(() => {
    if (tab === 'skills') setSkillsMounted(true);
    if (tab === 'skills' && prevTabRef.current !== null && prevTabRef.current !== 'skills') {
      setSkillsRefresh((value) => value + 1);
    }
    prevTabRef.current = tab;
  }, [tab]);

  /** 切 tab 的地址：只改 `tab`，其它查询参数原样带着（见上一条注释） */
  function tabHref(next: CapabilityTab): string {
    const params = new URLSearchParams(searchParams);
    if (next === 'experts') params.delete(TAB_PARAM);
    else params.set(TAB_PARAM, next);
    const query = params.toString();
    return query === '' ? '/agents' : `/agents?${query}`;
  }

  /**
   * 当前工作区。专家页只展示**这一个工作区**里的智能体 —— 一个工作区可以有多个，
   * 跨工作区的记录不混在一起。`workspaceId` 缺省等于全库查询，所以它没解析出来时
   * 下面的 `load` 不会发请求（见那里的 guard）。
   */
  const {
    workspace,
    loading: workspaceLoading,
    error: workspaceError,
    refresh: refreshWorkspace,
  } = useWorkspaces();
  const workspaceId = workspace?.id;

  const [keywordInput, setKeywordInput] = useState('');
  /** 防抖后的关键词，也是真正发给接口的那个 */
  const [keyword, setKeyword] = useState('');
  /**
   * 来源筛选：`all` 不筛，`user` 只留用户建的，`builtin` 只留随产品提供的。
   * 取值直接进 `?source=`；它不是排序 —— 三种来源下都沿用接口的 updatedAt 降序。
   */
  const [source, setSource] = useState<SourceKey>('all');
  /**
   * 状态筛选：`all` 不筛，其余直接进 `?status=`（服务端按现算状态过滤）。
   * 与来源 / 关键词 / 标签都是 AND 关系；三种来源下都沿用接口的 updatedAt 降序。
   */
  const [status, setStatus] = useState<StatusKey>('all');
  /**
   * 当前标签筛选，`null` = 不筛。单选：点另一个标签就替换，点同一个就取消。
   * 后端一次只收一个 `tag`，与 `keyword` 是 AND 关系。
   */
  const [tag, setTag] = useState<string | null>(null);

  /**
   * 当前页码，从 1 起（契约 5.00 的 Page）。换筛选条件时回到第 1 页 ——
   * 否则会停在「上一批结果」的页码上，新结果不够长时看到一张空页。
   */
  const [page, setPage] = useState(1);

  /** null = 首屏还没回来。用它当哨兵，省掉一个 loading 枚举 */
  const [agents, setAgents] = useState<Agent[] | null>(null);
  /**
   * 「刷新」按钮的在飞状态。**只由这颗按钮推进**：搜索防抖也会走 `load`，
   * 但那不是刷新动作，跟着一起把按钮置灰只会让工具条一直闪。
   */
  const [refreshing, setRefreshing] = useState(false);
  /** 过滤后的全量条数（不是本页条数），既用于「共 N 个」也用于算总页数 */
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  /** 详情弹窗当前看的是谁。编辑 / 删除都从这一层再往上叠 */
  const [detail, setDetail] = useState<Agent | null>(null);
  const [pendingEdit, setPendingEdit] = useState<Agent | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Agent | null>(null);
  const [deleting, setDeleting] = useState(false);

  /** 连着改关键词会有多个请求在飞，只认最后一个的响应 */
  const requestSeq = useRef(0);
  /** 翻页后滚回这里（整页标题），否则视口还停在页脚 */
  const topRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setKeyword(keywordInput.trim());
      // 关键词变了就不再停在旧结果的第 N 页，见 page 的注释
      setPage(1);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [keywordInput]);

  /**
   * 工作区变了（含从「有」变成「没有」）：旧列表、已选标签、页码都不再属于新工作区。
   * 同时推进请求序号，让还在路上的旧工作区请求作废 —— 否则它回来后会把上一个
   * 工作区的卡片写进新页面。
   *
   * 来源 / 状态筛选不在这里重置：它们不绑定工作区（换工作区后「只看已就绪」通常仍然成立）。
   * 标签要重置，因为标签下拉的候选是按工作区取的。
   */
  useEffect(() => {
    requestSeq.current += 1;
    setAgents(null);
    setTotal(0);
    setPage(1);
    setTag(null);
    setError(null);
  }, [workspaceId]);

  const load = useCallback(async () => {
    /*
     * 工作区还没解析出来（加载中 / 没有生效工作区）就不发查询。
     * 不传 `workspaceId` 的列表是**全库** —— 先闪一下别的工作区的智能体、
     * 再跳回当前工作区，是最糟的一种「已加载」错觉。
     */
    if (workspaceId === undefined) return;

    const seq = ++requestSeq.current;
    /*
     * 来源筛选由服务端做（`?source=user|builtin`，契约 5.01）：和标签下拉是 AND 关系，
     * 分页也照常交给服务端 —— 不再把匹配结果全量拉下来在前端切页。
     */
    const query = {
      keyword: keyword === '' ? undefined : keyword,
      tag: tag ?? undefined,
      workspaceId,
      source: source === 'all' ? undefined : source,
      status: status === 'all' ? undefined : status,
      pageSize: PAGE_SIZE,
    };

    try {
      const result = await agentsApi.list({ ...query, page });

      if (seq !== requestSeq.current) return;

      /*
       * 页码越界：删掉最后一页的最后几条、或改筛选后总数变少时会走到这里。
       * 退到最后一页让 effect 再拉一次 —— 停在页码大于总页数的空页上，用户会以为数据没了。
       */
      const lastPage = Math.max(1, Math.ceil(result.total / PAGE_SIZE));
      if (page > lastPage) {
        // 总数先跟上，翻页条在等下一次响应的间隙里才不会还按旧页数显示
        setTotal(result.total);
        setPage(lastPage);
        return;
      }

      setAgents(result.items);
      setTotal(result.total);
      setError(null);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      // 失败不清空已有数据：重试失败时旧列表还在，比整屏变空白好判断
      setError(describeLoadError(err));
    }
  }, [keyword, page, source, status, tag, workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * 工具条上的「刷新」：与技能 tab 那颗同语义 —— 进页面拉一次之外的唯一手动重拉。
   * 等 `load` 落地再放开按钮，连点不会叠出多个请求。
   */
  const refreshList = useCallback(async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  /**
   * 卡片 / 详情里那颗「使用」。落点在**框架**（见 `useExpertInFramework`）：
   * 这里是"去跟这个专家对话"，而对话页不是本模块的页面。
   * 地址里带上这个智能体的 id，让会话页进来就预选它。
   */
  function openUse(agent: Agent) {
    useExpertInFramework(agent.id);
  }

  /**
   * 卡底「构建」。落点是设计页 —— 那一页整页围着这个专家的 development 会话转
   * （阶段①是真会话），是这个仓里目前唯一一个「对某个专家动手」的页面。
   */
  function openDesign(agent: Agent) {
    navigate(`/agents/${agent.id}/design`);
  }

  /**
   * 卡底「评估」。**同一个设计页，只是带着阶段参数进去** —— 评估会话、报告右栏、
   * 产物状态门禁都在那一页，卡片再点一次「构建」再手点步骤条只是多一步。
   * 参数名与取值的口径见 `AgentCreatePage` 的 `readStageParam`。
   */
  function openEvaluate(agent: Agent) {
    navigate(`/agents/${agent.id}/design?stage=evaluation`);
  }

  /**
   * 编辑成功：关掉编辑层 → 重拉列表。
   *
   * 编辑是从卡面文字链打开的，详情那层通常没开；开着的话顺手把记录换成新的，
   * 关掉编辑后回到详情看到的就不是旧数据。
   */
  function handleUpdated(updated: Agent) {
    setPendingEdit(null);
    setDetail((current) => (current === null ? null : updated));
    void load();
  }

  async function confirmDelete() {
    const target = pendingDelete;
    if (target === null) return;

    setDeleting(true);
    try {
      await agentsApi.remove(target.id);
      // 记录没了，详情那层也就没有可看的东西 —— 两层一起收掉
      setPendingDelete(null);
      setDetail(null);
      await load();
    } catch (err) {
      // 409（内置智能体 / 重名等）、404（已被别处删掉）都靠这句话说清楚，不要吞掉
      setPendingDelete(null);
      setError(err instanceof ApiError ? err.message : t('agentList.error.deleteFailed'));
    } finally {
      setDeleting(false);
    }
  }

  const filtering = keyword !== '' || source !== 'all' || status !== 'all' || tag !== null;

  /** 来源筛选在空态文案里的说法（`内置` / `自定义`）；不筛来源时为 null */
  const shownSource = source === 'all' ? null : sourceLabel(source, t);

  /** 总页数。`total` 是过滤后的全量，所以它跟着关键词 / 标签一起变。 */
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  /**
   * 点标签：同一个再点一次取消，换一个就替换。
   * 不清关键词 / 排序 —— 三者在工具条上各自可见，后端也是 AND 叠加。
   */
  function toggleTag(next: string) {
    setTag((current) => (current === next ? null : next));
    setPage(1);
  }

  /** 下拉的「全部标签」传 `null`；其余与卡片点击走同一个 toggle。 */
  function chooseTag(next: string | null) {
    if (next === null) {
      setTag(null);
      setPage(1);
      return;
    }
    toggleTag(next);
  }

  function clearFilters() {
    setKeywordInput('');
    setKeyword('');
    setSource('all');
    setStatus('all');
    setTag(null);
    setPage(1);
  }

  /** 换来源等价于换一整批内容，同样回到第 1 页。 */
  function chooseSource(next: SourceKey) {
    setSource(next);
    setPage(1);
  }

  /** 换状态同样是一整批内容，回到第 1 页（理由同 `chooseSource`）。 */
  function chooseStatus(next: StatusKey) {
    setStatus(next);
    setPage(1);
  }

  /** 翻页。页码由这里夹住，按钮的 disabled 只是视觉兜底。 */
  function goToPage(next: number) {
    setPage(Math.min(Math.max(next, 1), pageCount));
    /*
     * 页面内容换了一整屏，视口却停在页脚 —— 滚回顶部，别让人以为点了没反应。
     *
     * **不能平滑滚动**：新一页如果短（如最后一页只有十几条），文档高度会在动画期间
     * 缩到视口附近，浏览器把滚动位置夹到新的最大值，动画就停在了底部。即时滚动发生在
     * React 提交之前，落点是旧文档的顶部（0），换页后也还是 0。
     */
    topRef.current?.scrollIntoView({ block: 'start' });
  }

  /**
   * 空态文案按「状态 / 来源 / 关键词 / 标签」的组合说清楚是哪一层没命中。
   * 选了来源却不提来源，会让人以为库里一条都没有。
   *
   * 状态单独占一条：它是最容易被听漏的一层（卡片上只是名称下面一行小字），
   * 且与其它条件叠加时组合数会翻倍，所以措辞统一收在「当前筛选下」这一句里。
   */
  const shownTag = tag;
  const emptyText = (() => {
    if (status !== 'all') {
      return t('agentList.empty.status', { status: statusLabel(status, t) });
    }
    if (shownSource !== null) {
      if (shownTag !== null && keyword !== '') {
        return t('agentList.empty.sourceBoth', { keyword, tag: shownTag, source: shownSource });
      }
      if (shownTag !== null) {
        return t('agentList.empty.sourceTag', { tag: shownTag, source: shownSource });
      }
      if (keyword !== '') {
        return t('agentList.empty.sourceKeyword', { keyword, source: shownSource });
      }
      return t('agentList.empty.sourceOnly', { source: shownSource });
    }
    if (shownTag !== null && keyword !== '') {
      return t('agentList.empty.both', { keyword, tag: shownTag });
    }
    if (shownTag !== null) return t('agentList.empty.tagOnly', { tag: shownTag });
    if (keyword !== '') return t('agentList.empty.keywordOnly', { keyword });
    return t('agentList.empty.none', {
      workspace: workspace?.name ?? t('agentList.empty.currentWorkspace'),
    });
  })();

  function renderBody() {
    const skeleton = (
      <div className="al-grid">
        {Array.from({ length: 12 }, (_, index) => (
          <div key={index} className="al-card al-card--skeleton" />
        ))}
      </div>
    );

    // 工作区还在读：先摆骨架。不能先按「全库」拉一次列表（见 load 的 guard）
    if (workspace === null && workspaceLoading) return skeleton;

    // 没有当前工作区：不展示任何工作区的智能体，给出下一步
    if (workspace === null) {
      // 首次读取失败：错误条已经说明原因，正文不再重复
      if (workspaceError !== null) return null;
      return (
        <div className="al-empty">
          <Icon name="folder" size={22} />
          <p>{t('agentList.workspaceMissing')}</p>
          <p className="al-empty-hint">{t('agentList.workspaceMissingHint')}</p>
          <button type="button" className="al-btn al-btn--sm" onClick={refreshWorkspace}>
            <Icon name="refresh" size={12} />
            {t('agentList.refresh')}
          </button>
        </div>
      );
    }

    // 首屏失败：不摆骨架屏，直接让错误条说清楚
    if (agents === null) {
      if (error !== null) return null;
      return skeleton;
    }

    if (agents.length === 0) {
      return (
        <div className="al-empty">
          <Icon name={filtering ? 'search' : 'sparkle'} size={22} />
          <p>{emptyText}</p>
          {/* 空态不给「新增」按钮：本页没有登记入口了，下一步在首页那条路上 */}
          <button
            type="button"
            className="al-btn al-btn--sm"
            onClick={filtering ? clearFilters : () => navigate('/')}
          >
            {filtering ? t('agentList.empty.clearFilters') : t('agentList.empty.create')}
          </button>
        </div>
      );
    }

    return (
      <>
        <div className="al-grid">
          {agents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onOpenDetail={setDetail}
              onUse={openUse}
              onEdit={setPendingEdit}
              onDesign={openDesign}
              onEvaluate={openEvaluate}
              onDelete={setPendingDelete}
              onTagClick={toggleTag}
              activeTag={tag}
            />
          ))}
        </div>

        {/*
          只有一页时不摆控件（本页每页 200 条，200 以内翻页没有意义）。
          控件里那颗「总数」是一页装不下时才需要的信息；一页装得下就是网格里全部。
        */}
        {pageCount > 1 && (
          <nav className="al-pager" aria-label={t('agentList.pager.label')}>
            <span className="al-pager__info">
              {t('agentList.pager.info', { page, count: pageCount, total })}
            </span>
            <div className="al-pager__actions">
              <button
                type="button"
                className="al-btn al-btn--sm"
                disabled={page <= 1}
                onClick={() => goToPage(page - 1)}
              >
                {t('agentList.pager.prev')}
              </button>
              <button
                type="button"
                className="al-btn al-btn--sm"
                disabled={page >= pageCount}
                onClick={() => goToPage(page + 1)}
              >
                {t('agentList.pager.next')}
              </button>
            </div>
          </nav>
        )}
      </>
    );
  }

  return (
    <section className="al" ref={topRef}>
      <header className="al-top">
        <div className="al-top-lead">
          {/*
            两个 tab：专家 / 技能。用 Link 而不是按钮 + 状态 —— 它们本来就是两个地址，
            中键开新标签、刷新、从首页快捷卡直达都该成立；选中态靠 `aria-current`。
          */}
          <nav className="al-tabs" aria-label={t('agentList.tabs.label')}>
            <Link
              to={tabHref('experts')}
              className={`al-tab${tab === 'experts' ? ' al-tab--on' : ''}`}
              aria-current={tab === 'experts' ? 'page' : undefined}
            >
              {t('agentList.tabs.experts')}
            </Link>
            <Link
              to={tabHref('skills')}
              className={`al-tab${tab === 'skills' ? ' al-tab--on' : ''}`}
              aria-current={tab === 'skills' ? 'page' : undefined}
            >
              {t('agentList.tabs.skills')}
            </Link>
          </nav>
        </div>
      </header>

      {/*
        专家 tab 的全部内容。技能 tab 只挂 `SkillLibraryPanel` —— 它自己拉数据，
        不复用本页的 agents 状态；本页的详情 / 编辑 / 删除叠层也因此不会跟到技能 tab 上。
      */}
      {tab === 'experts' && (
        <>
          {workspace !== null && (
            <div className="al-toolbar">
              <div className="al-toolbar-left">
                {/*
                  来源 / 状态两颗下拉（2026-10-29 由一排 chip 改过来）：两组 chip 都以
                  「全部」打头，并排放着分不清哪颗属于哪一组；收起后也省下一截工具条。
                  取值仍直接是接口的 `?source=` / `?status=`。
                */}
                <FilterSelect
                  label={t('agentList.sourceLabel')}
                  value={source}
                  options={sourceFilters(t)}
                  onChange={chooseSource}
                />
                <FilterSelect
                  label={t('agentList.statusLabel')}
                  value={status}
                  options={statusFilters(t)}
                  onChange={chooseStatus}
                />

                {/* 标签的发现入口：当前工作区的标签 + 搜索。卡片上的标签点击是它的快捷方式。 */}
                <TagFilter workspaceId={workspace.id} value={tag} onChange={chooseTag} />

                {/*
                  已选标签。整颗 chip 就是清除按钮 —— 不在 chip 里再套一颗 ×，
                  那会变成按钮套按钮。它只清标签，关键词与排序留在原处。
                */}
                {tag !== null && (
                  <button
                    type="button"
                    className="al-chip al-chip--on al-chip--tag"
                    title={t('agentList.clearTagFilter', { tag: shownTag ?? '' })}
                    aria-label={t('agentList.clearTagFilter', { tag: shownTag ?? '' })}
                    onClick={() => setTag(null)}
                  >
                    <span className="al-chip-tag-text">
                      {t('agentList.tagChip', { tag: shownTag ?? '' })}
                    </span>
                    <Icon name="close" size={12} />
                  </button>
                )}
              </div>

              <div className="al-toolbar-actions">
                <label className="al-search">
                  <Icon name="search" size={14} />
                  <input
                    value={keywordInput}
                    onChange={(event) => setKeywordInput(event.target.value)}
                    placeholder={t('agentList.search')}
                    aria-label={t('agentList.searchAria')}
                  />
                  {keywordInput !== '' && (
                    <button
                      type="button"
                      className="al-search-clear"
                      onClick={() => setKeywordInput('')}
                      aria-label={t('agentList.clearSearch')}
                    >
                      <Icon name="close" size={12} />
                    </button>
                  )}
                </label>
                {/*
                  与技能 tab 工具条同一颗「刷新」：两边同页切换，只有一边能手动重拉
                  会让人以为专家列表是死的（工坊改完专家记录回来正是要看它）。
                */}
                <button
                  type="button"
                  className="al-btn al-btn--sm"
                  onClick={() => void refreshList()}
                  disabled={refreshing}
                >
                  <Icon name="refresh" size={12} />
                  {t('agentList.refreshList')}
                </button>
              </div>
            </div>
          )}

          {/* 工作区读取失败优先说：列表这时压根没发请求，报「列表失败」会误导人 */}
          {(workspaceError !== null || error !== null) && (
            <div className="al-error" role="alert">
              <Icon name="alert" size={14} />
              <span>{workspaceError ?? error}</span>
              <button
                type="button"
                className="al-btn al-btn--sm"
                onClick={() => {
                  if (workspaceError !== null) refreshWorkspace();
                  if (error !== null) void load();
                }}
              >
                <Icon name="refresh" size={12} />
                {t('agentList.retry')}
              </button>
            </div>
          )}

          {renderBody()}

          {/*
            两处叠层：编辑弹窗 / 删除确认。两者都可能从卡面直接触发，
            也可能是在详情开着时触发（那就叠在详情上）—— 各自按需挂载，关掉上层回到原处。
          */}
          {detail !== null && (
            <AgentDetailDialog agent={detail} onClose={() => setDetail(null)} />
          )}

          {pendingEdit !== null && (
            <EditAgentDialog agent={pendingEdit} onClose={() => setPendingEdit(null)} onUpdated={handleUpdated} />
          )}

          {pendingDelete !== null && (
            <ConfirmDialog
              agent={pendingDelete}
              busy={deleting}
              onCancel={() => setPendingDelete(null)}
              onConfirm={() => void confirmDelete()}
            />
          )}
        </>
      )}

      {/* `hidden` 只在视觉与可访问树上藏起面板，状态（搜索词 / 滚动位置）留着 */}
      <div hidden={tab !== 'skills'}>
        {skillsMounted && (
          <SkillLibraryPanel workspaceId={workspace?.id} refreshSignal={skillsRefresh} />
        )}
      </div>
    </section>
  );
}

/**
 * 把加载失败翻译成能动手的话。
 *
 * 「本地服务没起」是这一族里最像后端崩了的一种，而它偏偏是开发态最常见的一种
 * （后端没 npm run dev）。判据见 `isBackendDown`：**响应根本不是 JSON** ——
 * 整个后端没起、或 vite 代理没配时才会是这个长相；后端自己在报错（有 JSON 的 4xx/5xx）
 * 就走下面那条，把它的原话透出来。
 */
function describeLoadError(err: unknown): string {
  if (isBackendDown(err)) return msg('agentList.error.listUnavailable', { hint: backendDownHint() });
  if (err instanceof ApiError)
    return msg('agentList.error.listStatus', { message: err.message, status: err.status });
  return err instanceof Error ? err.message : msg('agentList.error.listFailed');
}
