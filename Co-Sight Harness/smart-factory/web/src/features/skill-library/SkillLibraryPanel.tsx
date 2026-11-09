import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { msg, useI18n } from '../../i18n/useI18n';
import { backendDownHint, isBackendDown } from '../../shared/api/agents';
import { ApiError } from '../../shared/api/client';
import { skillsApi } from '../../shared/api/skills';
import type { Skill, SkillsResponse } from '../../shared/api/skills';
import { Icon } from '../../shared/components/Icon';
import { composeOptimizeMessage, skillMdPath } from '../skill-workshop/compose-prompt';
import { HistoryDrawer } from '../skill-workshop/components/HistoryDrawer';
import { AssembleDialog } from './components/AssembleDialog';
import { SkillCard } from './components/SkillCard';
import './skill-library.css';

interface SkillLibraryPanelProps {
  /**
   * 当前生效工作区。给了才连带扫该工作区的智能体技能；没有工作区时**照样拉**，
   * 只是只剩技能库那一路 —— 技能库是端侧全局资产，不随工作区分叉（后端文档 §2），
   * 所以卡片上的来源叫「技能库」而不是「工作区技能库」。
   */
  workspaceId: string | undefined;
  /**
   * 重拉信号：面板保持挂载（切 tab 不卸载），由页面在切回技能 tab 时 +1，
   * 让数据静默刷新一次。搜索词与滚动位置不受影响。
   */
  refreshSignal?: number;
}

/**
 * 技能库 tab 的内容（`/agents?tab=skills`）。
 *
 * **只负责内容，不负责页头与 tab 条** —— 那两样和专家 tab 共用，长在 `AgentListPage`
 * 里。错误条 / 空态 / 按钮沿用同一页的 `.al-*` 样式；栅格也用专家的 `.al-grid`
 * —— 两个 tab 的卡片要一样大（2026-10-27 按评审拉齐，技能 tab 不再自己少排一列）。
 *
 * 数据只打真实接口 `GET /skills`（`shared/api/skills.ts`），没有 mock 兜底 ——
 * 端点没起来时照实说「技能库没拿到」，不拿假数据把页面填满。
 *
 * 刷新口径（§4.4）：进页面拉一次 + 一颗手动刷新，**不轮询、不推送**。
 * 工坊产出一个技能后回到这里，用户自己点刷新。
 */
export function SkillLibraryPanel({ workspaceId, refreshSignal = 0 }: SkillLibraryPanelProps) {
  const { t } = useI18n();
  const navigate = useNavigate();

  /** null = 还没拿到过（首屏或换工作区后）；有值期间手动刷新不清空，避免整页闪骨架 */
  const [data, setData] = useState<SkillsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);

  /**
   * 搜索词。**在前端筛**：接口没有 keyword 参数，而技能库是一屏就能看完的量级
   * （后端一次返回全部），再去后端加参数只会多一个契约。匹配 name / description /
   * 归属智能体名 —— 用户记得住「天气智能体」不一定记得住技能叫什么。
   */
  const [keywordInput, setKeywordInput] = useState('');

  /** 只认最后一次请求的响应：换工作区 / 连点刷新都可能让多个请求同时在飞 */
  const requestSeq = useRef(0);

  /** 正在装配的技能；非 null 时叠一层「装配到智能体」弹层 */
  const [assembleTarget, setAssembleTarget] = useState<Skill | null>(null);
  /** 装配成功的临时提示（不刷新列表：装配不改变库，只往产物里复制） */
  const [notice, setNotice] = useState<string | null>(null);

  /** 工坊历史抽屉；`filter` 非 null = 只看某张技能卡的会话（`优化 <name>`） */
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyFilter, setHistoryFilter] = useState<string | null>(null);

  useEffect(() => {
    if (notice === null) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  /**
   * 换工作区等于换一批「智能体技能」：旧结果不再属于这一屏，先清空再拉。
   * 同时推进序号，让还在路上的旧请求作废。
   */
  useEffect(() => {
    requestSeq.current += 1;
    setData(null);
    setError(null);
  }, [workspaceId]);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    setFetching(true);
    try {
      const result = await skillsApi.list(workspaceId);
      if (seq !== requestSeq.current) return;
      setData(result);
      setError(null);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      // 失败不清空已有数据：手动刷新失败时旧卡片还在，比整屏变空白好判断
      setError(describeLoadError(err));
    } finally {
      if (seq === requestSeq.current) setFetching(false);
    }
  }, [workspaceId, refreshSignal]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * 两个动作的落点（`capability-routing.md` §4.3）。
   *
   * **库技能 → 工坊**：「优化」走 `?target=` 绝对路径（不传名字选，两路可能同名）；
   * 「历史」在**当前页**开抽屉并按「优化 <name>」筛，点会话后才进工坊。
   * **智能体技能 → 设计页**：「优化」把话放进发送框（replay，不自动发）；
   * 「去设计页」/「历史」就是那一场开发对话本身。
   */
  function openOptimize(skill: Skill) {
    if (skill.source === 'agent') {
      if (skill.ownerAgentId === null) return;
      navigate(`/agents/${skill.ownerAgentId}/design`, {
        // 与工坊、首页拼同一句命令（`composeOptimizeMessage`）：卡片上只点「优化」、
        // 没写要求，所以不带 `--expert-guidance`
        state: { replay: { text: composeOptimizeMessage(skillMdPath(skill), ''), paths: [] } },
      });
      return;
    }
    const params = new URLSearchParams({ target: skill.path, name: skill.name });
    navigate(`/workshop?${params.toString()}`);
  }

  function openHistory(skill: Skill) {
    if (skill.source === 'agent') {
      openDesign(skill);
      return;
    }
    openWorkshopHistory(`优化 ${skill.name}`);
  }

  function openDesign(skill: Skill) {
    if (skill.ownerAgentId === null) return;
    navigate(`/agents/${skill.ownerAgentId}/design`);
  }

  /**
   * 工坊历史：在**技能库这一页**开抽屉，点会话才进工坊（`/workshop?session=`）。
   *
   * 不直接跳 `/workshop?history=1`：那样进工坊先看到的是一块空对话区，用户只是为了
   * 挑一场会话 —— 入口落在哪一页，就在哪一页把选择做完，别让空页面白开一次。
   *
   * 技能库空着时这是唯一能找回「还在跑 / 刚跑完」那场的地方：卡上的「优化 / 历史」
   * 都还没出现，首页「创建技能」又会另起一场新会话。
   */
  function openWorkshopHistory(filter: string | null = null) {
    setHistoryFilter(filter);
    setHistoryOpen(true);
  }

  /** 搜索词（去空白）与筛后的列表。大小写不敏感，三处字段任一命中即保留 */
  const query = keywordInput.trim();
  const allItems = data?.items ?? [];
  const visibleItems =
    query === ''
      ? allItems
      : allItems.filter((skill) =>
          [skill.name, skill.description, skill.ownerName ?? ''].some((value) =>
            value.toLowerCase().includes(query.toLowerCase()),
          ),
        );

  /** 首屏：骨架卡与专家 tab 同款，切 tab 时不会一边有内容一边空白 */
  function renderBody() {
    if (data === null) {
      if (error !== null) return null;
      return (
        <div className="al-grid">
          {Array.from({ length: 8 }, (_, index) => (
            <div key={index} className="sl-card sl-card--skeleton" />
          ))}
        </div>
      );
    }

    // 真·空库：给下一步，而不是只留一句「还没有技能」——空态是中途离开工坊后最容易卡住的地方
    if (allItems.length === 0) {
      return (
        <div className="al-empty">
          <Icon name="layers" size={22} />
          <p>{t('skillLibrary.empty')}</p>
          <p className="al-empty-hint">{t('skillLibrary.emptyHint')}</p>
          {/*
            空态只补**创建**这一条：回首页并预选「创建技能」（创建只有首页那一个入口，
            框架 `/agent-dev` 里嵌的就是首页），命令由首页提交时拼，这里不另起一场会话。
            「历史会话」不放这儿 —— 工具条那颗一直在，空库时也点得到，重复摆只会让人
            以为两个入口去的是不同地方。
          */}
          <button
            type="button"
            className="al-btn al-btn--sm"
            onClick={() => navigate('/', { state: { capability: 'skill.create' } })}
          >
            <Icon name="blocks" size={12} />
            {t('skillLibrary.emptyCreateSkill')}
          </button>
        </div>
      );
    }

    // 有技能但没命中：说清楚是搜索没中，给一颗清空而不是「创建一个」
    if (visibleItems.length === 0) {
      return (
        <div className="al-empty">
          <Icon name="search" size={22} />
          <p>{t('skillLibrary.emptyNoMatch', { keyword: query })}</p>
          <button
            type="button"
            className="al-btn al-btn--sm"
            onClick={() => setKeywordInput('')}
          >
            {t('skillLibrary.clearSearch')}
          </button>
        </div>
      );
    }

    return (
      <div className="al-grid">
        {visibleItems.map((skill) => (
          <SkillCard
            key={`${skill.source}:${skill.path}`}
            skill={skill}
            onOptimize={() => openOptimize(skill)}
            onHistory={() => openHistory(skill)}
            onDesign={() => openDesign(skill)}
            onAssemble={() => setAssembleTarget(skill)}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="sl">
      <div className="sl-toolbar">
        {/*
          计数兼「技能库在哪」：`root` 由接口给，前端不拼路径。
          还没拿到时显示加载文案，数量未知就摆 0 会让人以为库是空的。
        */}
        <span className="sl-count" title={data?.root}>
          {data !== null
            ? query === ''
              ? t('skillLibrary.count', { count: allItems.length })
              : t('skillLibrary.countFiltered', {
                  count: visibleItems.length,
                  total: allItems.length,
                })
            : fetching
              ? t('skillLibrary.loading')
              : ''}
        </span>
        <div className="sl-toolbar-actions">
          {/* 搜索：与专家 tab 同一颗输入框（`.al-search`），清空键在输入框内 */}
          <label className="al-search">
            <Icon name="search" size={14} />
            <input
              value={keywordInput}
              onChange={(event) => setKeywordInput(event.target.value)}
              placeholder={t('skillLibrary.search')}
              aria-label={t('skillLibrary.searchAria')}
            />
            {keywordInput !== '' && (
              <button
                type="button"
                className="al-search-clear"
                onClick={() => setKeywordInput('')}
                aria-label={t('skillLibrary.clearSearch')}
              >
                <Icon name="close" size={12} />
              </button>
            )}
          </label>
          {/*
            库空 / 库非空都要有这条路：卡上的「历史」按技能进，技能没产出来时就没了；
            这里不选技能，直接进工坊的历史抽屉。
          */}
          <button
            type="button"
            className="al-btn al-btn--sm"
            onClick={() => openWorkshopHistory()}
            disabled={data === null}
            title={data === null ? (error ?? t('skillLibrary.loading')) : undefined}
          >
            <Icon name="clock" size={12} />
            {t('skillLibrary.workshopHistory')}
          </button>
          <button
            type="button"
            className="al-btn al-btn--sm"
            onClick={() => void load()}
            disabled={fetching}
          >
            <Icon name="refresh" size={12} />
            {t('skillLibrary.refresh')}
          </button>
        </div>
      </div>

      {error !== null && (
        <div className="al-error" role="alert">
          <Icon name="alert" size={14} />
          <span>{error}</span>
          <button type="button" className="al-btn al-btn--sm" onClick={() => void load()}>
            <Icon name="refresh" size={12} />
            {t('skillLibrary.retry')}
          </button>
        </div>
      )}

      {notice !== null && (
        <div className="sl-notice" role="status">
          <Icon name="check" size={13} />
          <span>{notice}</span>
        </div>
      )}

      {renderBody()}

      {assembleTarget !== null && (
        <AssembleDialog
          skill={assembleTarget}
          workspaceId={workspaceId}
          onClose={() => setAssembleTarget(null)}
          onDone={(agent, skill) => {
            setAssembleTarget(null);
            setNotice(t('agentSkills.done', { name: skill.name, agent: agent.name }));
          }}
        />
      )}

      {/*
        工坊历史抽屉：cwd 直接用 `GET /skills` 的 `cwd`（技能库根），不另拉一次。
        点会话才跳工坊 —— 抽屉负责「挑哪一场」，工坊只承接已经选好的那一场。
      */}
      {historyOpen && data !== null && (
        <HistoryDrawer
          cwd={data.cwd}
          currentSessionId={null}
          filter={historyFilter}
          onClose={() => setHistoryOpen(false)}
          onOpen={(session) => navigate(`/workshop?session=${encodeURIComponent(session.id)}`)}
        />
      )}
    </div>
  );
}

/**
 * 把加载失败翻译成能动手的话（与专家页同一套判据）。
 *
 * 后端还没实现这个端点时，这里会原样透出服务端的 404 文案（「无匹配路由：GET …」）——
 * 那不是前端能兜的事，说清楚比编一个空列表好。
 */
function describeLoadError(err: unknown): string {
  if (isBackendDown(err)) return msg('skillLibrary.error.unavailable', { hint: backendDownHint() });
  if (err instanceof ApiError)
    return msg('skillLibrary.error.status', { message: err.message, status: err.status });
  return err instanceof Error ? err.message : msg('skillLibrary.error.failed');
}
