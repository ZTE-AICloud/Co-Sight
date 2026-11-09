import { useCallback, useState } from 'react';
import { useI18n } from '../../i18n/useI18n';
import { knowledgeApi } from '../api/knowledge';
import type { KnowledgeWorkflow } from '../api/knowledge';
import { Icon } from './Icon';
import { TargetPicker } from './TargetPicker';
import type { PickerOption } from './TargetPicker';
import './KnowledgeSelect.css';

/**
 * 「知识检索」选择器：一颗 chip + 一个弹层。
 *
 * 位置固定在 **Composer 工具栏左侧、`+` 之后**（`Composer` 的 `accessory` 槽位），
 * 首页（创建 / 优化智能体）与生产会话共用这一份 —— 两处的外观、交互与数据源完全一致。
 *
 * 选中值不是正文的一部分：发送时由页面拼进 `--knowledge-workflow-id`（见
 * `shared/commands/harness-prompt.ts`）。在生产会话里它还是智能体自己的配置 ——
 * 选 / 取消都会由页面写进后端，刷新后仍然生效；取消就是点 chip 右侧的 ×（传 `null`）。
 *
 * 列表只在第一次打开时拉；失败不缓存（关掉再打开会重试）。空列表是合法结果
 * （部署里还没有已发布工作流），与「拉失败」在弹层里给的是两句不同的话。
 */

interface KnowledgeSelectProps {
  value: KnowledgeWorkflow | null;
  onChange: (next: KnowledgeWorkflow | null) => void;
  /** 首页提交中 / 生产会话正在跑 / 正在写库：只锁这一颗，不锁输入框 */
  disabled?: boolean;
  /**
   * 保存选择失败的人话（生产会话的 chip 会把选择写进智能体配置）。
   * 显示在 chip 右侧；下一次改动静默清掉。首页不落库，不传。
   */
  saveError?: string | null;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function KnowledgeSelect({
  value,
  onChange,
  disabled = false,
  saveError = null,
}: KnowledgeSelectProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  /** null = 还没成功拉过（关掉再打开会重试） */
  const [options, setOptions] = useState<KnowledgeWorkflow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await knowledgeApi.listWorkflows();
      setOptions(result.items);
    } catch (cause) {
      setOptions(null);
      // 服务端的 502 已经是可直接显示的人话（见 4.15-知识库），原样透出
      setError(t('knowledge.loadFailed', { error: errorText(cause) }));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const openPicker = useCallback(() => {
    if (disabled) return;
    setOpen(true);
    if (options === null && !loading) void load();
  }, [disabled, load, loading, options]);

  const pickerOptions: PickerOption[] = (options ?? []).map((workflow) => ({
    id: workflow.id,
    name: workflow.name,
    // 副行放 workflowId：名字可能重名（部署里真的有两个 test）
    description:
      workflow.description === '' ? workflow.id : `${workflow.id} · ${workflow.description}`,
    title: `${workflow.name} · ${workflow.id}`,
  }));

  return (
    <>
      {value === null ? (
        <button
          type="button"
          className="knowledge-chip knowledge-chip--add"
          disabled={disabled}
          onClick={openPicker}
        >
          <Icon name="plus" size={12} />
          {t('knowledge.chip.add')}
        </button>
      ) : (
        <span className="knowledge-chip knowledge-chip--set">
          <button
            type="button"
            className="knowledge-chip__main"
            title={`${value.name} · ${value.id}`}
            disabled={disabled}
            onClick={openPicker}
          >
            <Icon name="search" size={12} />
            {t('knowledge.chip.selected', { name: value.name })}
          </button>
          <button
            type="button"
            className="knowledge-chip__x"
            aria-label={t('knowledge.chip.remove')}
            disabled={disabled}
            onClick={() => onChange(null)}
          >
            <Icon name="close" size={11} />
          </button>
        </span>
      )}

      {saveError !== null && (
        <span className="knowledge-chip__error" role="alert" title={saveError}>
          {saveError}
        </span>
      )}

      {open && (
        <TargetPicker
          title={t('knowledge.picker.title')}
          desc={t('knowledge.picker.desc')}
          searchPlaceholder={t('knowledge.picker.search')}
          loading={loading}
          error={error}
          options={pickerOptions}
          onPick={(option) => {
            const picked = options?.find((item) => item.id === option.id) ?? null;
            onChange(picked);
            setOpen(false);
          }}
          onCancel={() => setOpen(false)}
        />
      )}
    </>
  );
}
