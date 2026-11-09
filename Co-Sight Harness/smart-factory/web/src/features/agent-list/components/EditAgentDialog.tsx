import { useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import { agentsApi } from '../../../shared/api/agents';
import type { Agent, AgentUpdateInput } from '../../../shared/api/agents';
import { ApiError } from '../../../shared/api/client';
import { Icon } from '../../../shared/components/Icon';
import { TAGS_MAX, tagProblem } from '../tags';
import { CoverField } from './CoverField';
import { Dialog } from './Dialog';

interface EditAgentDialogProps {
  agent: Agent;
  onClose: () => void;
  /** 成功即由页面关掉本弹窗并重拉列表 */
  onUpdated: (agent: Agent) => void;
}

/** 长度上限与后端一致（contract 5.01 的 Agent.name / Agent.description）。 */
const NAME_MAX = 40;
const DESC_MAX = 120;

/**
 * 编辑专家。
 *
 * 初值直接取列表里那条记录，**不重新拉详情**：契约 5.01 里详情与列表返回的是同一条记录的
 * 两种切法（`GET /agents/{id}` 的形状与列表项完全一致），再发一次请求只会多一个
 * 「打开弹窗要等一下」的加载态。真到了详情比列表多字段那天，这里再补请求。
 *
 * 提交时**只发改动过的字段**：契约要求 update 至少给一个字段（一个都不给是 400），
 * 所以「一个都没改」时保存键直接禁掉，而不是让后端来报错。
 * 简介的「改成空串」是**清空**（不是「没改」）—— 这正是要把空串发出去的那种情况；
 * 标签同理：全删光发的是 `tags: []`，那也是「改」，不是「没改」。
 *
 * ── 两处与上一版不同 ─────────────────────────────────────────────────────
 *
 * - **状态不在这里改**（2026-10-16 撤掉的那三个分段按钮）：草稿 → 就绪是创建页那场会话
 *   跑通的**结果**，不是给人手拨的开关。手改只会造出一个「状态说就绪、产物目录还空着」
 *   的假象 —— 那比不能改更糟。要看状态去详情弹窗的徽标（`AgentDetailDialog`），只读的。
 * - **标签能编辑了**（原来只在卡面上看）：已加的一颗颗摆着，点 × 拿掉，输入框回车 / 逗号
 *   加一颗。规则（≤10 个、每项 1–10 字、不含 `" \ % _`）照后端抄在 `../tags.ts`。
 *   输入框里**还没回车的这一句也算数**（点保存时自动带上），免得敲了标签点保存白敲；
 *   反过来，草稿有问题时保存键是灰的 —— 见下面 `canSubmit` 那段。
 * - **来源不在这个表单里**：它是 `Agent.source` 字段（用户建的 / 内置的），不是一颗标签，
 *   所以既没有「只读 chip」也没有锁。`内置` / `自定义` 是保留字，输入时 `../tags.ts` 就拦，
 *   后端写入侧同样 400。来源只由服务端决定，见 `shared/agent-source.ts`。
 *
 * 版式照 2026-10-16 那版设计稿做过一遍（宽度、亲疏、光晕都在 `agent-list.css` 的
 * `.al-dialog--edit` 一节）：标题行右边是一枚弱化的身份芯片，每个字段下面是「左边说事、
 * 右边计数」的辅助行，封面与标签都是**一个框里装两样**（头像 + 地址 / 胶囊 + 输入框）。
 * 一处**没照做**：标签胶囊用蓝色而不是卡面那套灰 —— 表单里它是「待提交的输入项」，
 * 蓝色表示可以删、还没保存；卡面上的灰标签是只读展示。封面那格仍留着一行辅助文字
 * （设计稿只把它写进了 placeholder —— 取舍见 `CoverField`）。
 */
export function EditAgentDialog({ agent, onClose, onUpdated }: EditAgentDialogProps) {
  const { t } = useI18n();
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description);
  const [tags, setTags] = useState<string[]>(agent.tags);
  const [icon, setIcon] = useState<string>(agent.icon);
  /** 标签输入框里还没回车的那一段 */
  const [tagDraft, setTagDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedName = name.trim();

  const draftTag = tagDraft.trim();
  /** 草稿的问题；null = 没问题（没输入时也是 null） */
  const draftProblem = draftTag === '' ? null : tagProblem(draftTag, tags);
  const tagsFull = tags.length >= TAGS_MAX;

  /**
   * 真正会提交的那份标签：**草稿只要没问题就一起带上**。
   * 不带的话，「敲完标签直接点保存」会把这句悄悄丢掉，而用户以为加上了。
   */
  const nextTags = draftTag !== '' && draftProblem === null ? [...tags, draftTag] : tags;

  const patch = buildPatch(agent, {
    name: trimmedName,
    description: description.trim(),
    tags: nextTags,
    icon,
  });
  /**
   * 草稿有毛病时保存键是灰的：不能「把错的丢掉、把对的存下去」—— 用户看着框里那句还在，
   * 却已经保存完了，回来还得再想一遍刚才少的是什么。要留就改到能加，不要就把那句删了。
   */
  const canSubmit = trimmedName !== '' && draftProblem === null && patch !== null && !submitting;

  /** 把草稿加一颗。回车 / 逗号 / 点保存都走这里（点保存那条由 nextTags 兜） */
  function addTag() {
    if (draftProblem !== null || tagsFull) return;
    setTags((current) => [...current, draftTag]);
    setTagDraft('');
  }

  function onTagKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    // 组字中的回车不算「加一颗」（中文输入法选词也是回车，别把人家的词吃掉）
    if (event.nativeEvent.isComposing) return;

    if (event.key === 'Enter' || event.key === ',') {
      // 回车不拦这一下会顺手提交整个表单（表单里回车的默认动作），逗号则会留在框里
      event.preventDefault();
      addTag();
      return;
    }

    // 框里空着时退格 = 删掉最后一颗（chip 输入框的老规矩）
    if (event.key === 'Backspace' && tagDraft === '') {
      if (tags.length === 0) return;
      event.preventDefault();
      setTags((current) => current.slice(0, -1));
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit || patch === null) return;

    setSubmitting(true);
    setError(null);
    try {
      onUpdated(await agentsApi.update(agent.id, patch));
    } catch (err) {
      // 409 改名撞车、404 已被别处删掉 —— 两种都把后端原话透出来
      setError(err instanceof ApiError ? err.message : t('agentList.edit.saveFailed'));
      setSubmitting(false);
    }
  }

  return (
    <Dialog onDismiss={submitting ? undefined : onClose} className="al-dialog--edit">
      <form className="al-form" onSubmit={submit}>
        {/* 标题行：身份挪到右边那枚芯片上 —— 38 个字符的 id 摆在标题旁边会把标题挤没。
            完整的值在 tooltip 里，跟「不可改」的说明同一处。 */}
        <div className="al-form-head">
          <h2 className="al-dialog-title">{t('agentList.edit.title')}</h2>
          <span
            className="al-form-id"
            title={t('agentList.edit.idLocked', { id: agent.id })}
          >
            ID: {shortId(agent.id)}
          </span>
        </div>

        <label className="al-field">
          <span className="al-field-label">
            {t('agentList.edit.name')}
            <span className="al-field-required">*</span>
          </span>
          <input
            className="al-input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={NAME_MAX}
            placeholder={t('agentList.edit.namePlaceholder')}
            autoFocus
          />
          <span className="al-field-hint">
            <span>{t('agentList.edit.nameHint')}</span>
            <span>
              {name.length}/{NAME_MAX}
            </span>
          </span>
        </label>

        <label className="al-field">
          <span className="al-field-label">{t('agentList.edit.description')}</span>
          <textarea
            className="al-textarea"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={DESC_MAX}
            rows={3}
            placeholder={t('agentList.edit.descriptionPlaceholder')}
          />
          <span className="al-field-hint">
            <span>
              {description === '' && agent.description !== ''
                ? t('agentList.edit.descriptionCleared')
                : ''}
            </span>
            <span>
              {description.length}/{DESC_MAX}
            </span>
          </span>
        </label>

        <CoverField value={icon} name={trimmedName} onChange={setIcon} />

        {/* 标签：已加的一颗颗 + 一个输入框，装在同一个框里（边框画在 .al-tags 上）。
            胶囊**不跟卡面走那套按文本派生的颜色**：表单里它是待提交的输入项，不是展示徽标 —— 见 css 里那节 */}
        <div className="al-field">
          <span className="al-field-label">{t('agentList.edit.tags')}</span>

          <div className="al-tags">
            {tags.map((tag) => (
              <span key={tag} className="al-tag-chip">
                {tag}
                <button
                  type="button"
                  className="al-tag-chip-x"
                  aria-label={t('agentList.edit.removeTag', { tag })}
                  onClick={() => setTags((current) => current.filter((item) => item !== tag))}
                >
                  ×
                </button>
              </span>
            ))}

            <input
              className="al-tags-input"
              value={tagDraft}
              onChange={(event) => setTagDraft(event.target.value)}
              onKeyDown={onTagKeyDown}
              // 失焦不提交：光标走开不该悄悄多出一颗（要加就回车/逗号，要存就点保存）
              placeholder={
                tagsFull
                  ? t('agentList.edit.tagsFull', { max: TAGS_MAX })
                  : t('agentList.edit.addTagPlaceholder')
              }
              disabled={tagsFull}
              aria-label={t('agentList.edit.addTagAria')}
            />
          </div>

          <span className="al-field-hint">
            <span>
              {draftProblem !== null ? (
                <span className="al-field-problem">{draftProblem}</span>
              ) : draftTag !== '' ? (
                t('agentList.edit.draftReady')
              ) : (
                <>
                  {t('agentList.edit.tagsHint')}
                  {tags.length === 0 && agent.tags.length > 0
                    ? t('agentList.edit.tagsCleared')
                    : ''}
                </>
              )}
            </span>
            <span>
              {tags.length}/{TAGS_MAX}
            </span>
          </span>
        </div>

        {error !== null && (
          <p className="al-form-error" role="alert">
            <Icon name="alert" size={13} />
            {error}
          </p>
        )}

        <div className="al-dialog-actions">
          <button type="button" className="al-btn" onClick={onClose} disabled={submitting}>
            {t('agentList.edit.cancel')}
          </button>
          <button type="submit" className="al-btn al-btn--primary" disabled={!canSubmit}>
            {submitting ? (
              <>
                <span className="al-spin" />
                {t('agentList.edit.saving')}
              </>
            ) : (
              t('agentList.edit.save')
            )}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

/**
 * 生成 update 的请求体：**只装改过的字段**，一个都没改时返回 null。
 *
 * 比对的是 trim 后的值 —— 用户只多敲了个空格不算改动，提交上去反而会白白刷新 updatedAt、
 * 把这张卡顶到列表最前面。标签是**逐项比**（长度 + 顺序）：后端保序，顺序变了就是真改动。
 */
function buildPatch(
  agent: Agent,
  next: { name: string; description: string; tags: string[]; icon: string },
): AgentUpdateInput | null {
  const patch: AgentUpdateInput = {};
  if (next.name !== agent.name) patch.name = next.name;
  if (next.description !== agent.description) patch.description = next.description;
  if (!sameTags(next.tags, agent.tags)) patch.tags = next.tags;
  if (next.icon !== agent.icon) patch.icon = next.icon;
  return Object.keys(patch).length === 0 ? null : patch;
}

/** 两个标签数组一模一样？（长度 + 逐项，顺序也算） */
function sameTags(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((tag, index) => tag === b[index]);
}

/**
 * 身份芯片里的短 id：`agt_fbcf…1bda`。
 *
 * 只为了「一眼认得出是同一条」，完整值在 tooltip 里（标题旁边摆不下 38 个字符）。
 * 够短就原样显示 —— `agt_` 后面那串 uuid 是服务端生成的，客户端不得解析其内容。
 */
function shortId(id: string): string {
  return id.length <= 20 ? id : `${id.slice(0, 8)}…${id.slice(-4)}`;
}
