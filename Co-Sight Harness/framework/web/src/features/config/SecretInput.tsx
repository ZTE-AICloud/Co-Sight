/**
 * 密钥 / 令牌输入（含"已配置"状态与待保存的「清除」）。
 *
 * 模型密钥与代理令牌的规则完全一样（D26），所以这里只有一份实现：两份各写一遍的话，
 * "留空到底是保持还是清除"这种决定性细节迟早会在其中一份里走样，而它在界面上
 * 看不出来——只有提交之后密钥没了才会发现。
 */

import { cn } from '../../lib/cn';
import { Button } from '../../components/ui/Button';
import { SecretField } from '../../components/ui/form/TextField';
import { toggleClear, typeSecret, type SecretDraft } from './secret';
import styles from './config.module.css';

export interface SecretLabels {
  /** 已配置时的提示（`apiKeySet` / `tokenSet`）。 */
  set: string;
  /** 尚未配置时的提示（`apiKeyUnset` / `tokenUnset`）。 */
  unset: string;
  /** 「清除密钥」/「清除令牌」。 */
  clear: string;
  /** 待保存状态下的那句"将清除（点此撤销）"。 */
  clearPending: string;
}

export interface SecretInputProps {
  id: string;
  label: string;
  labels: SecretLabels;
  draft: SecretDraft;
  onChange: (next: SecretDraft) => void;
  /** 读侧只有"配没配"（D26）：决定提示语，也决定要不要给「清除」按钮。 */
  configured: boolean;
  /**
   * 追加在"已配置 / 尚未配置"那一句之后的补充说明。
   *
   * 存在的理由：知识库的 API Key 有一个"留空会回落到服务端默认"的第三态，
   * 而 `labels.set` / `labels.unset` 说的是通用 D26 语义，掺进资源特有的规则
   * 会让另外两个表单读到不相关的句子。
   */
  hint?: string | undefined;
  disabled?: boolean;
  error?: string | undefined;
  className?: string | undefined;
}

export function SecretInput({
  id,
  label,
  labels,
  draft,
  onChange,
  configured,
  hint,
  disabled = false,
  error,
  className,
}: SecretInputProps) {
  return (
    <div className={cn(styles.secret, className)}>
      <SecretField
        id={id}
        label={label}
        value={draft.value}
        onChange={(value) => {
          onChange(typeSecret(value));
        }}
        hint={[configured ? labels.set : labels.unset, hint].filter((line) => line).join(' ')}
        error={error}
        disabled={disabled}
      />

      {/*
       * 没配过密钥的条目不显示「清除」：那里没有东西可清，一个点了不改变任何状态的
       * 按钮只会让人怀疑刚才那一下没生效。新建时同理（`configured` 恒为 false）。
       */}
      {configured ? (
        <div className={styles.secretAction}>
          {/*
           * 用默认（secondary）而不是 danger：`Button.module.css` 把 danger 限定在
           * 确认框的确认按钮与表单底部的删除上——列表里常驻的破坏性操作用红色会把
           * "需要停留的那一下"稀释掉。这里的状态差异由按钮文字承担，那是更明确的
           * 信号：它直接写着这一步还没有发生。
           */}
          <Button
            size="sm"
            disabled={disabled}
            onClick={() => {
              onChange(toggleClear(draft));
            }}
          >
            {draft.clearing ? labels.clearPending : labels.clear}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
