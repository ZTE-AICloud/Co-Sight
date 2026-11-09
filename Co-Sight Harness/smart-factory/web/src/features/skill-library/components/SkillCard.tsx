import { useI18n } from '../../../i18n/useI18n';
import type { Skill } from '../../../shared/api/skills';
import { AgentAvatar } from '../../../shared/components/AgentAvatar';
import { Icon } from '../../../shared/components/Icon';
import { timeAgo } from '../../../shared/time';

interface SkillCardProps {
  skill: Skill;
  /** 优化：库技能进工坊；智能体技能回它的设计页（replay），见 `capability-routing.md` §4.3 */
  onOptimize?: () => void;
  /** 历史：库技能打开工坊抽屉并筛到这一场；智能体技能跳设计页 */
  onHistory?: () => void;
  /** 智能体技能：直接去设计页（不预填） */
  onDesign?: () => void;
  /** 装配：把这一版技能复制进某个智能体的产物（弹层选目标） */
  onAssemble?: () => void;
}

/**
 * 技能卡片（`capability-routing.md` §4.2）。
 *
 * **与专家卡同一套版式**（2026-10-22 按评审对齐）：20px 内边距 / 10px 圆角、
 * 40px 卡头图标、16px 名称、来源徽标贴右上角、13px 两行简介、底部一条发丝线 +
 * 12px 文字链动作。技能卡只是字段更少，不再自己造一套按钮与字号。
 *
 * 读法与专家卡一致：名称后面紧跟版本，来源在右上角，动作与更新时间在卡底一行。
 * 动作落到哪里由 `SkillLibraryPanel` 决定：
 *   库技能  → `/workshop?target=…`（优化） / 技能库页内的历史抽屉（历史，点会话再进工坊）
 *   智能体技能 → 该智能体的设计页（优化带 replay，去设计页不带）
 *
 * 卡片不可点（没有详情层）：这里展示的字段本来就都在卡上。目录路径挂在 `title` 上，
 * 排查「两路同名」时悬停能看到是哪一个。
 */
export function SkillCard({ skill, onOptimize, onHistory, onDesign, onAssemble }: SkillCardProps) {
  const { t, locale } = useI18n();

  /*
   * 来源徽标只写「技能库」/「智能体」这档短字 —— 库技能是全局资产（不跟工作区分叉），
   * 智能体名称进 title，也进卡底那句提示。
   *
   * 不把归属智能体名直接挂在徽标上（2026-10-27）：卡片宽度与专家卡一样之后，右上角
   * 一串名字会把主标识（技能名）挤到只剩几个像素。专家卡的徽标本来也只有两个字。
   *
   * `ownerName` 理论上不会为空（`source === 'agent'` 时后端一定给），仍按空串兜底。
   */
  const ownerName =
    skill.ownerName !== null && skill.ownerName !== '' ? skill.ownerName : null;
  const sourceLabel =
    skill.source === 'library'
      ? t('skillLibrary.source.library')
      : t('skillLibrary.source.agent');

  return (
    <article className="sl-card" title={skill.path}>
      <header className="sl-card-head">
        {/*
          技能没有封面图，卡头图标就用名称首字 + 派生色（与专家卡同一个组件，同一套
          配色规则）。种子用 `path` 而不是名字：名字可改，path 不可改 —— 同一个技能
          在卡片上不该因为改名换一个颜色。
        */}
        <AgentAvatar icon="" name={skill.name} seed={skill.path} size={40} />

        {/*
          名称 + 版本是一组：名称**不伸张**（`flex: 0 1 auto`），版本才会紧跟在它后面；
          否则名称吃满整行，版本被顶到来源旁边，读起来像「名称 …… v1 来源」。
          来源用 `margin-left: auto` 单独靠右。
        */}
        {/* 最多两行就截断（见 skill-library.css）：完整名称挂在 title 上 */}
        <h3 className="sl-card-name" title={skill.name}>
          {skill.name}
        </h3>
        {skill.version !== '' && <span className="sl-card-version">{skill.version}</span>}

        {/* 来源徽标与专家卡同一档描边签：库技能用蓝（系统资产），智能体技能用紫（用户资产） */}
        <span
          className={`al-card-badge sl-card-source${
            skill.source === 'library' ? ' al-card-badge--builtin' : ''
          }`}
          title={t('skillLibrary.source.title', { source: ownerName ?? sourceLabel })}
        >
          {sourceLabel}
        </span>
      </header>

      {/* 简介与专家卡同款：13px、两行、定高；空着时摆占位，同一行卡片高度才会齐 */}
      <p className="al-card-desc">
        {skill.description === '' ? (
          <em>{t('skillLibrary.noDescription')}</em>
        ) : (
          skill.description
        )}
      </p>

      {skill.source === 'agent' && (
        <p className="sl-card-hint">
          <Icon name="alert" size={11} />
          {t('skillLibrary.actions.agentHint', { owner: ownerName ?? sourceLabel })}
        </p>
      )}

      {/*
        底部动作区：左边是文字链动作，右边是更新时间 —— 沿用专家卡 footer 的
        发丝线与 `.al-card-action` 的字号 / 悬停色，换成技能卡的动作而已。
      */}
      <footer className="al-card-footer">
        <div className="al-card-actions">
          {onOptimize !== undefined && (
            <>
              <button type="button" className="al-card-action" onClick={onOptimize}>
                {t('skillLibrary.actions.optimize')}
              </button>
              <span className="al-card-sep" aria-hidden="true">
                ·
              </span>
            </>
          )}
          {onOptimize !== undefined &&
            (skill.source === 'agent'
              ? onDesign !== undefined && (
                  <button type="button" className="al-card-action" onClick={onDesign}>
                    {t('skillLibrary.actions.design')}
                  </button>
                )
              : onHistory !== undefined && (
                  <button type="button" className="al-card-action" onClick={onHistory}>
                    {t('skillLibrary.actions.history')}
                  </button>
                ))}
          {onAssemble !== undefined && (
            <>
              <span className="al-card-sep" aria-hidden="true">
                ·
              </span>
              <button type="button" className="al-card-action sl-card-assemble" onClick={onAssemble}>
                {t('skillLibrary.actions.assemble')}
              </button>
            </>
          )}
        </div>
        <span className="sl-card-time">{timeAgo(skill.updatedAt, locale)}</span>
      </footer>
    </article>
  );
}
