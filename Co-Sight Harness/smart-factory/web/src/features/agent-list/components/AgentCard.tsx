import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type { Agent } from '../../../shared/api/agents';
import { AgentAvatar } from '../../../shared/components/AgentAvatar';
import { isUsable, sourceLabel, statusLabel } from '../display';

interface AgentCardProps {
  agent: Agent;
  /** 点卡片任意处（动作 / 标签浮层之外）打开详情弹窗 */
  onOpenDetail: (agent: Agent) => void;
  /**
   * 「使用」被点了。**可选**：卡片不认识路由，跳哪儿由调用方定。
   * 没传时那颗按钮是只读占位（外观不变、tooltip 说明「这个页面还没有」）——
   * 现在的两个调用方（专家页、卡片 demo）都传了它；真页面上的落点是**离开本模块**，
   * 整页跳框架首页（会话页），见 `AgentListPage` 的 `useExpertInFramework`。
   *
   * 为什么是回调 prop 而不是 ref / 命令式方法：方向是「卡片告诉调用方发生了什么」（事件），
   * 不是「调用方命令卡片做点什么」。
   */
  onUse?: (agent: Agent) => void;
  /** 卡底文字链「编辑」。打开编辑弹窗，成功后由页面回灌新记录并重拉列表 */
  onEdit: (agent: Agent) => void;
  /** 卡底文字链「构建」（2026-10-30 前叫「设计」），落点是设计页 `/agents/:id/design` */
  onDesign: (agent: Agent) => void;
  /**
   * 卡底文字链「评估」。落点是**设计页的评估阶段**（`/agents/:id/design?stage=evaluation`）——
   * 评估会话本来就长在那页上，这里只是换个入口直接落过去，不再另开一页。
   */
  onEvaluate: (agent: Agent) => void;
  /** 卡底文字链「删除」。二次确认由页面叠一层 `ConfirmDialog`，卡片自己不弹 */
  onDelete: (agent: Agent) => void;
  /**
   * 点了某个标签。**可选**：传了才把标签渲染成按钮；demo 等只读场景不传，
   * 标签保持原来的 `span`，卡片行为完全不变。单选 / 替换由调用方决定。
   */
  onTagClick?: (tag: string) => void;
  /** 当前生效的标签，用于选中态与 `aria-pressed` */
  activeTag?: string | null;
}

/**
 * 专家卡片（2026-10-20 照新参考稿重做）。
 *
 * 自上而下五块 —— 40px 卡头（图标 / 名称 / 来源徽标）、两行简介、一行标签、
 * 一条发丝线、底部动作（文字链 + 「使用」）。
 *
 * ── 这一版改了什么 ─────────────────────────────────────────────────────
 *
 * - **动作回到卡面**：编辑 / 构建 / 评估 / 删除是一组 12px 文字链，贴在卡片底部左侧；
 *   「使用」在右侧，是唯一一块实心主色。上一版（2026-10-18）把这组动作全收进了详情弹窗，
 *   理由是「同一组动作只留一个入口」；这一版把入口挪到了**卡面**，详情弹窗随之变成
 *   **只读的信息层**（工作区 / ID / 目录 / 时间），不再挂动作条 —— 入口仍然只有一处。
 *   删除这类破坏性动作照旧走二次确认（`ConfirmDialog`，由页面叠上来）。
 * - **来源升成徽标**：`自定义` / `内置`（读 `agent.source`）从标签行挪到名称右边，画成描边小徽标。
 *   它是系统盖的戳，不该混在用户写的分类里（详情弹窗也是这么分的）。
 * - **图标换成浅底同色系首字**（见 `AgentAvatar`）：一屏十几张卡时不再块块饱和。
 * - **高度不再钉死 176px**：每块都是定量的（40 卡头 + 42 简介 + 22 标签 + 12 分隔 + 30 动作），
 *   内容怎么变都是同一个高度；钉一个数反而会在标签多一行 / 字号变化时裁掉东西。
 *
 * 标签行仍然是这一版做得最实的一块：**摆得下几个是量出来的**，不是写死「最多 3 个」——
 * 见下面 `visible` 与那段 layout effect。摆不下的收成 `+N`，点开是个浮层，
 * 全量在那儿摆着（旧版只给一个 hover 提示）。
 *
 * **2026-10-28 补上状态**：名称下面一行小字（圆点 + 词），读 `agent.status`；
 * 内置智能体恒为 `completed`，普通行才可能是生成中 / 暂停 / 失败。
 * 同一条状态也是「使用」的门禁 —— **只有 `completed` 能点**，其余 `disabled`，
 * 原因写进 tooltip。这样卡片自己就回答了「为什么这颗按钮是灰的」。
 *
 * 卡片上仍然没有的（刻意）：目录、在线小绿点 —— 目录在详情弹窗里，
 * 后者后端没有对应字段，不编。
 */
export function AgentCard({
  agent,
  onOpenDetail,
  onUse,
  onEdit,
  onDesign,
  onEvaluate,
  onDelete,
  onTagClick,
  activeTag,
}: AgentCardProps) {
  const { t } = useI18n();
  /** 标签浮层开着没有。全卡只剩这一层浮层，所以用一个 boolean 就够了 */
  const [tagsOpen, setTagsOpen] = useState(false);

  /**
   * 点标签：先收起浮层，再交给调用方。
   *
   * **浮层里的标签必须显式关** —— 文档级 click 监听对 `.al-tag-popover` 内部点击
   * 是主动 return 的（见下面 `onDocClick`），不会替我们收。
   */
  const selectTag =
    onTagClick === undefined
      ? undefined
      : (next: string) => {
          setTagsOpen(false);
          onTagClick(next);
        };

  /**
   * 标签行里摆得下几个。`null` = 全摆得下，不折叠。
   *
   * 为什么量而不是写死一个数：标签宽度差得远（「AI」两个字符、「端到端端到端…」八个），
   * 卡片宽度又随栅格变（窗口缩放、列数变化）。写死个数会在窄卡片上溢出成半截胶囊，
   * 在宽卡片上又会白白收起来几个。
   */
  const [visible, setVisible] = useState<number | null>(null);
  const tagsRef = useRef<HTMLDivElement>(null);

  /*
   * 来源（`user` / `builtin`）单独摆成卡头徽标；标签行只放用户写的分类。
   * 来源是接口字段，不再混在 tags 里 —— 详情弹窗也是这么分的。
   */
  const tags = agent.tags;

  /** 内置智能体只读：编辑 / 设计 / 评估 / 删除整组不摆，只留「使用」 */
  const readonly = agent.source === 'builtin';

  /**
   * 能不能「使用」：只有产物状态是 `completed` 才算就绪。内置智能体由服务端恒置
   * `completed`（开箱即用），`null`（读盘失败）与未完成的状态一律不放行。
   */
  const usable = isUsable(agent.status);

  const collapsed = visible !== null && visible < tags.length;
  const shown = collapsed ? tags.slice(0, visible) : tags;

  /**
   * 量出来的结果只在**标签内容变了**的时候作废。
   *
   * 依赖用这个串而不是 `tags` 本身：数组的身份每次渲染都可能是新的（页面重排、
   * 编辑后回灌），拿它当依赖会让 effect 每渲染白跑一遍。标签最多 10 个，序列化不心疼。
   */
  const tagKey = JSON.stringify(tags);

  /**
   * 量标签行，决定折叠到第几个。
   *
   * 用 layout effect：第一遍会**把所有标签都摆出来**量「一行放得下几个」，量完立刻
   * setState 重渲，这一切都发生在浏览器绘制之前 —— 用户看不到那个中间态
   * （就算看得到，行本身是 `overflow: hidden` 的，多出来的也只是被裁掉）。
   *
   * 收敛的规则只有两条，都在 measure 里：先按「第一行能放几个」起步，
   * 然后在折叠态检查「+N」有没有跟前面那几个挤在同一行，没有就让出一个位置。
   * 每让一个位置都会重渲再量一次（`visible` 在依赖里），让到 1 时必定成立，所以一定会停。
   */
  useLayoutEffect(() => {
    const box = tagsRef.current;
    if (box === null) return undefined;

    const measure = () => {
      const items = [...box.querySelectorAll<HTMLElement>('[data-tag-item]')];
      if (items.length === 0) return;

      /*
       * 「放得下」的判据是**右边缘有没有越过箱子的右边缘**，不是 offsetTop 相等 ——
       * 箱子是 nowrap 的，全都摆不下时它们照样待在同一行（offsetTop 全相等），
       * 只是右边那几颗被 `overflow: hidden` 裁掉了。按行数判断会把「裁掉了一半」
       * 读成「全放得下」（真踩过：十个标签挤成一行，右边那颗只剩半个「告」）。
       */
      const right = box.getBoundingClientRect().right;
      const fits = (el: HTMLElement) => el.getBoundingClientRect().right <= right + 0.5;
      const more = box.querySelector<HTMLElement>('[data-tag-more]');

      if (more === null) {
        // 展开态（全都摆着量）：能放几个是几个，全放得下就不折叠
        let count = 0;
        for (const item of items) {
          if (!fits(item)) break;
          count += 1;
        }
        setVisible(count >= tags.length ? null : Math.max(1, count));
        return;
      }

      // 折叠态：「+N」得也在里面；不在就再让一个位置出来（一直让到 1 一定会停）
      setVisible(fits(more) ? visible : Math.max(1, (visible ?? 0) - 1));
    };

    measure();

    if (typeof ResizeObserver === 'undefined') return undefined;
    // 卡片宽度会变（窗口缩放、栅格换列），量出来的结果会过期
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [tagKey, tags.length, visible]);

  /**
   * 点别处 / 按 Esc 收起标签浮层。
   *
   * 判据是「点的是不是这一层自己」：浮层内部留着（里面可能还要点东西），
   * 开关那颗 `+N` 也留着 —— 它自己的 onClick 按「开 / 关」翻面，
   * 这里再插一手会把刚翻开的那一层又关回去。
   */
  useEffect(() => {
    if (!tagsOpen) return undefined;

    function onDocClick(event: MouseEvent) {
      const target = event.target as Element | null;
      if (target?.closest('[data-panel-toggle], .al-tag-popover') != null) return;
      setTagsOpen(false);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setTagsOpen(false);
    }

    document.addEventListener('click', onDocClick);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('click', onDocClick);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [tagsOpen]);

  return (
    <article
      className="al-card"
      onClick={(event) => {
        // 点在动作区、标签浮层上：那是它们自己的事，不算「点卡片」
        if ((event.target as HTMLElement).closest('button, .al-card-footer, .al-tag-popover') !== null)
          return;
        // 正在拖选文字（想复制简介）：这一下是选择，不是打开
        if (window.getSelection()?.toString() !== '') return;
        // 浮层开着时第一下只负责收浮层，避免点空白顺手把详情也开了
        if (tagsOpen) {
          setTagsOpen(false);
          return;
        }
        onOpenDetail(agent);
      }}
    >
      <header className="al-card-head">
        <AgentAvatar icon={agent.icon} name={agent.name} seed={agent.id} size={40} />

        {/*
          名称 + 状态的竖排。状态写在名称下面而不是再挤一颗徽标到右边：卡头这一行
          已经被头像和来源徽标占掉大半，4 列栅格里最窄的卡只剩几十像素给名称，
          再塞一颗「已就绪」会把名字截成两个字。竖排不占横向空间，也不增高 ——
          16px 名称 + 12px 状态正好落在 40px 卡头里。
        */}
        <div className="al-card-heading">
          {/*
            整张卡仍可点开详情（鼠标习惯），但键盘落点是这颗名称按钮 —— 不再把
            `role="button"` 挂在含多个按钮的 article 上（那样读屏会把里面的动作吞掉）。
          */}
          <h3 className="al-card-name" title={agent.name}>
            <button
              type="button"
              className="al-card-name-btn"
              aria-label={t('agentList.card.viewDetail', { name: agent.name })}
              onClick={() => onOpenDetail(agent)}
            >
              {agent.name}
            </button>
          </h3>

          {/*
            产物状态：圆点给扫读，文字给语义（色弱也读得出来）。`null` 是读盘失败的
            降级值，归到「状态未知」，同样不放行「使用」。
          */}
          <span className={`al-card-status al-card-status--${agent.status ?? 'unknown'}`}>
            <span className="al-card-status-dot" aria-hidden="true" />
            {/* 文字单独一层才能省略：`text-overflow` 对 flex 容器的匿名文本项不生效 */}
            <span className="al-card-status-text">{statusLabel(agent.status, t)}</span>
          </span>
        </div>

        {/*
          来源徽标：它是系统盖的戳（`source` 字段），不是用户写的分类，所以不混进下面那行标签。
        */}
        <span
          className={`al-card-badge al-card-badge--${agent.source}`}
          title={sourceLabel(agent.source, t)}
        >
          {sourceLabel(agent.source, t)}
        </span>
      </header>

      <p className="al-card-desc">
        {agent.description === '' ? <em>{t('agentList.card.noDescription')}</em> : agent.description}
      </p>

      {/* 标签行：单行、量出来摆几个（见上面那段 layout effect）。
          一个标签都没有时这行照样留着高度 —— 同一行卡片才不会因为标签有无错位。 */}
      <div className="al-card-tags-wrap">
        <div className="al-card-tags" ref={tagsRef}>
          {shown.map((tag) => (
            <TagChip
              key={tag}
              tag={tag}
              active={tag === activeTag}
              onSelect={selectTag}
              measure
            />
          ))}

          {collapsed && (
            <button
              type="button"
              className="al-tag al-tag--more"
              data-tag-item
              data-tag-more
              data-panel-toggle
              aria-expanded={tagsOpen}
              aria-label={t('agentList.card.expandTags', {
                name: agent.name,
                count: tags.length,
              })}
              // 摆不下的那几个，点一下在这儿铺开 —— 比只给一个 hover 提示多看得到东西
              onClick={() => setTagsOpen((open) => !open)}
            >
              +{tags.length - shown.length}
            </button>
          )}
        </div>

        {tagsOpen && (
          <div className="al-tag-popover">
            {tags.map((tag) => (
              /* 浮层里的标签不参与折叠测量：不要 `data-tag-item` */
              <TagChip key={tag} tag={tag} active={tag === activeTag} onSelect={selectTag} />
            ))}
          </div>
        )}
      </div>

      {/*
        底部动作区：左边是这组「对智能体动手」的文字链，右边是唯一的实心主按钮。
        四条动作都是真的了：「评估」落在设计页的评估阶段（地址带 `?stage=evaluation`），
        与「构建」是同一个页面、不同的落点 —— 那页的对话本来就长在评估沙箱里。
        删除用危险色，但**不挪到别处** —— 它就在这组里，靠颜色和二次确认拦住误触。
        内置智能体（`readonly`）左边这组整组不出现，只留右边那颗「使用」。
      */}
      <footer className="al-card-footer">
        {!readonly && (
          <div className="al-card-actions">
            <button type="button" className="al-card-action" onClick={() => onEdit(agent)}>
              {t('agentList.card.edit')}
            </button>
            <span className="al-card-sep" aria-hidden="true">
              ·
            </span>
            <button type="button" className="al-card-action" onClick={() => onDesign(agent)}>
              {t('agentList.card.design')}
            </button>
            <span className="al-card-sep" aria-hidden="true">
              ·
            </span>
            <button type="button" className="al-card-action" onClick={() => onEvaluate(agent)}>
              {t('agentList.card.evaluate')}
            </button>
            <span className="al-card-sep" aria-hidden="true">
              ·
            </span>
            <button
              type="button"
              className="al-card-action al-card-action--danger"
              onClick={() => onDelete(agent)}
            >
              {t('agentList.card.delete')}
            </button>
          </div>
        )}

        {/*
          「使用」：落点由调用方给（真页面里是整页跳框架首页，见 `onUse` 那段注释）。
          两个门禁叠在一起：**状态必须是 `completed`**（`usable`，2026-10-28 加），
          且调用方给了 `onUse`（没给就是 demo 占位）。

          与上一版不同，这一版**真的用 `disabled`**：状态没就绪时按不动是给用户的反馈
          （全局 `.al-btn:disabled` 会压到 0.55 透明 + `not-allowed`），配合名称下面
          那行状态和 tooltip 里的原因，一眼能看出「等生成完再用」。
        */}
        <button
          type="button"
          className="al-btn al-btn--use"
          disabled={!usable || onUse === undefined}
          title={
            !usable
              ? t('agentList.card.useBlocked', { status: statusLabel(agent.status, t) })
              : onUse === undefined
                ? t('agentList.card.useUnavailable')
                : t('agentList.card.useTitle', { name: agent.name })
          }
          onClick={onUse === undefined ? undefined : () => onUse(agent)}
        >
          {t('agentList.card.use')}
        </button>
      </footer>
    </article>
  );
}

/**
 * 一颗标签。卡面行与 +N 浮层共用一份渲染：
 *
 * - 没传 `onSelect`（demo / 只读）→ 仍是 `span`，与改造前完全一致；
 * - 传了 → `button`。卡片的点击处理里有 `closest('button, ...')` 早退，所以不会
 *   误开详情；原生 button 的 Enter / Space 自带 click，也不用再补键盘处理。
 *
 * `measure` 只给卡面那一行：折叠测量会查 `[data-tag-item]`，浮层里的标签不能算进去。
 */
function TagChip({
  tag,
  active,
  onSelect,
  measure = false,
}: {
  tag: string;
  active: boolean;
  onSelect?: (tag: string) => void;
  /** 是否参与折叠测量（只有卡面那一行需要） */
  measure?: boolean;
}) {
  const { t } = useI18n();
  const label = tag;
  const className = [
    'al-tag',
    onSelect === undefined ? '' : 'al-tag--button',
    active ? 'al-tag--active' : '',
  ]
    .filter(Boolean)
    .join(' ');

  if (onSelect === undefined) {
    return (
      <span className={className} data-tag-item={measure ? true : undefined} title={label}>
        {label}
      </span>
    );
  }

  return (
    <button
      type="button"
      className={className}
      data-tag-item={measure ? true : undefined}
      title={
        active
          ? t('agentList.card.clearTag', { tag: label })
          : t('agentList.card.filterByTag', { tag: label })
      }
      aria-pressed={active}
      onClick={() => onSelect(tag)}
    >
      {label}
    </button>
  );
}
