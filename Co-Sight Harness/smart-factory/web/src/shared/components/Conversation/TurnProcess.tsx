/**
 * 折叠体的内容：一串过程条目 + 「还有 N 步」。
 *
 * 折叠条（那个按钮）在 Turn.tsx 里，这里只管展开之后露出来的东西 ——
 * 拆开是因为两者的展开态是**两个**记忆：「这一轮折叠条开着吗」和
 * 「这一轮条目的明细开着吗」，混在一个组件里就得在一个组件里管两套 key。
 */

import { useI18n } from '../../../i18n/useI18n';
import { Icon } from '../Icon';
import { Entry } from './Entry';
import { PROC_VISIBLE, entryKey, moreKey } from './turns';
import type { ConversationMessage } from './types';

export interface TurnProcessProps {
  /** 折叠条属于哪条消息 —— 展开态的 key 由它拼出来 */
  message: ConversationMessage;
  openKeys: ReadonlySet<string>;
  onToggle: (key: string) => void;
}

export function TurnProcess({ message, openKeys, onToggle }: TurnProcessProps) {
  const { t } = useI18n();
  const entries = message.entries ?? [];
  const more = openKeys.has(moreKey(message.id));
  // 先只露 PROC_VISIBLE 条：一屏塞四十行，就没人在看哪一步是哪一步了
  const visible = more ? entries : entries.slice(0, PROC_VISIBLE);
  const hidden = entries.length - PROC_VISIBLE;

  return (
    <div className="conversation__proc">
      {visible.map((entry, index) => {
        const key = entryKey(message.id, index);
        return (
          <Entry
            key={key}
            entry={entry}
            open={openKeys.has(key)}
            onToggle={() => onToggle(key)}
          />
        );
      })}

      {hidden > 0 && (
        <button
          type="button"
          className="conversation__more"
          aria-expanded={more}
          onClick={() => onToggle(moreKey(message.id))}
        >
          <span className="conversation__caret">
            <Icon name="chevronDown" size={12} />
          </span>
          {more
            ? t('conversation.fold.collapse')
            : t('conversation.fold.more', { count: hidden })}
        </button>
      )}
    </div>
  );
}
