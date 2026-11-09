/**
 * 预览调试阶段（智能体创建第二步）：只有一场真实对话。
 *
 * 与生成阶段的区别不是「有没有右栏」，而是**在哪个目录跑**：这里连的是
 * `stage = 'preview'` 的会话，服务端在每次 run 前把开发产物整体拷到预览沙箱，
 * Claude Code 因此会按这个智能体自己的 CLAUDE.md 运行。产物只落在预览目录，
 * 不会回流生成阶段。
 *
 * 「重新开始预览」= 用生成阶段的最新产出重建沙箱，并开一场新会话。
 * 沙箱只在建会话时重拷，所以改完生成阶段后必须点它，否则跑的还是旧副本。
 */

import { useEffect, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import { agentSkillsApi } from '../../../shared/api/agent-skills';
import type { ComposerCommand, ComposerModel } from '../../../shared/components/Composer';
import { Icon } from '../../../shared/components/Icon';
import {
  BootState,
  ConversationPane,
  LinkPill,
  previewBootCopy,
} from '../components/ConversationPane';
import type { CreationChat } from '../useCreationChat';

export function PreviewStage({
  agentId,
  chat,
  model,
  sendBlockedReason,
}: {
  agentId: string;
  chat: CreationChat;
  /** 右下角模型选择器；三个阶段统一都有 */
  model?: ComposerModel;
  /** 没有可用模型等外部条件挡住发送的原因 */
  sendBlockedReason?: string | null;
}) {
  const { t } = useI18n();

  /*
   * 预览的 `/` 词表 = 这个智能体产物里真正有的技能（backlog #12）。
   * 项目技能的命令就是 `/＜目录名＞`，不带插件前缀；产物没就绪时词表为空，
   * 发送框照常可用（预览阶段本身已被产物门禁挡住）。
   */
  const [commands, setCommands] = useState<ComposerCommand[]>([]);
  useEffect(() => {
    let alive = true;
    void agentSkillsApi
      .list(agentId)
      .then((result) => {
        if (!alive || !result.ready) return;
        setCommands(
          result.items.map((item) => ({
            value: `/${item.name}`,
            ...(item.description === '' ? {} : { description: item.description }),
          })),
        );
      })
      .catch(() => {
        if (alive) setCommands([]);
      });
    return () => {
      alive = false;
    };
  }, [agentId]);
  /*
   * 会话没准备好、通道没连上、或正在跑一轮时不给重开：
   * - 服务端对「同 agent 同 stage 的实例已有活跃 run」回 409；
   * - 准备中再点一次只会把准备过程重来一遍；
   * - 断开时建不了会话，点了也只会把动作挂起到重连之后。
   * 没有可用模型时也不给重开：新会话建出来也跑不起来。
   */
  const canRestart =
    (sendBlockedReason ?? null) === null &&
    chat.link.conn === 'ready' &&
    chat.link.phase === 'ready' &&
    !chat.running;

  return (
    <div className="ac-main ac-main--single">
      <ConversationPane
        className="ac-conv--single"
        chat={chat}
        title={t('create.preview.title')}
        status={
          <span className="ac-head-actions">
            <button
              type="button"
              className="ac-restart"
              disabled={!canRestart}
              onClick={() => chat.restart()}
              title={t('create.preview.restartTitle')}
            >
              <Icon name="refresh" size={12} />
              {t('create.preview.restart')}
            </button>
            <LinkPill link={chat.link} />
          </span>
        }
        empty={<BootState link={chat.link} copy={previewBootCopy(t)} />}
        placeholder={t('create.preview.placeholder')}
        model={model}
        // 词表来自产物 .claude/skills（`GET /agents/:id/skills`），不是首页那份产品预设
        commands={commands}
        sendBlockedReason={sendBlockedReason}
      />
    </div>
  );
}
