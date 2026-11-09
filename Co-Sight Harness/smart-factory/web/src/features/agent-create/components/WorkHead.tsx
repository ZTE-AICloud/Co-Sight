/**
 * 右栏工作区的标题块：阶段标题 + 说明 + 会话参数（目录 / 技能）。
 *
 * 生产和评估两个阶段共用；文案由各自的 Stage 传入，这里不判断阶段。
 */

import { useI18n } from '../../../i18n/useI18n';
import { Icon } from '../../../shared/components/Icon';

export function WorkHead({
  title,
  desc,
  dir,
  skill,
  onManageSkills,
}: {
  title: string;
  desc: string;
  dir: string;
  /** 为空表示不调技能，直接跑产出物 */
  skill?: string;
  /** 产物技能入口（生成阶段传；评估阶段不传就没有这颗按钮） */
  onManageSkills?: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="ac-work-head">
      <h2>{title}</h2>
      <p>{desc}</p>

      <div className="ac-work-meta">
        <span className="ac-meta-item">
          <Icon name="folder" size={13} />
          {t('create.workHead.dir')}
          <code>{dir}</code>
        </span>
        <span className="ac-meta-item">
          <Icon name="wand" size={13} />
          {t('create.workHead.skill')}
          {skill ? <code>{skill}</code> : <em>{t('create.workHead.noSkill')}</em>}
        </span>
        {onManageSkills !== undefined && (
          <button type="button" className="ac-meta-item ac-meta-item--button" onClick={onManageSkills}>
            <Icon name="layers" size={13} />
            {t('agentSkills.panelTitle')}
          </button>
        )}
      </div>
    </div>
  );
}
