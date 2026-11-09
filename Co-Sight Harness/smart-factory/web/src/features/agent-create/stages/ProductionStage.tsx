/**
 * 生成阶段（智能体创建第一步）：左对话 / 右产物浏览。
 *
 * 阶段专属的事只有一件：一轮对话结束后给文件树一个重拉信号 —— 产物接口没有订阅，
 * 跑完再拉一次，是「刚生成的文件马上能看见」最省事的做法。
 * 模型选择器三个阶段都有，由页面统一传进来（值来自会话自己的 `modelId`），这里只往下传。
 */

import { useEffect, useRef, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type { Agent } from '../../../shared/api/agents';
import type { KnowledgeWorkflow } from '../../../shared/api/knowledge';
import { usePresetCommands } from '../../../shared/commands/preset-commands';
import type { ComposerModel } from '../../../shared/components/Composer';
import { Icon } from '../../../shared/components/Icon';
import { KnowledgeSelect } from '../../../shared/components/KnowledgeSelect';
import { FileViewer } from '../components/FileViewer';
import {
  BootState,
  ConversationPane,
  LinkPill,
} from '../components/ConversationPane';
import { SplitLayout } from '../components/SplitLayout';
import type { SplitWidth } from '../components/SplitLayout';
import { ProductSkillsDialog } from '../components/ProductSkillsDialog';
import { WorkHead } from '../components/WorkHead';
import type { CreationChat } from '../useCreationChat';

export function ProductionStage({
  agentId,
  agent,
  chat,
  split,
  model,
  sendBlockedReason,
  knowledge,
  knowledgeSaving,
  knowledgeError,
  knowledgeStale,
  onKnowledgeChange,
  onRebuildWithoutKnowledge,
}: {
  agentId: string;
  /** 详情还没回来时为 null：目录先显示「读取中…」 */
  agent: Agent | null;
  chat: CreationChat;
  split: SplitWidth;
  model?: ComposerModel;
  /** 没有可用模型等外部条件挡住发送的原因 */
  sendBlockedReason?: string | null;
  /**
   * 当前绑定的知识检索工作流（Composer 工具栏那颗 chip）。
   * 来源见 `AgentCreatePage`：本页新选 > 智能体配置（`Agent.knowledgeWorkflowId`）。
   */
  knowledge: KnowledgeWorkflow | null;
  /** 正在把选择写库：锁住 chip，避免连点 */
  knowledgeSaving?: boolean;
  /** 写库失败的人话，显示在 chip 旁边 */
  knowledgeError?: string | null;
  /**
   * 配置已取消、但产物里仍注入了知识检索技能。
   *
   * 取消只影响下一次构建，已经生成的产物不会自己变 —— 这里提示并给一个重建入口。
   */
  knowledgeStale?: boolean;
  onKnowledgeChange: (next: KnowledgeWorkflow | null) => void;
  /** 发起「移除知识检索并重建」（用 harness-create 现有接口发一条重建请求） */
  onRebuildWithoutKnowledge?: () => void;
}) {
  const { t } = useI18n();
  /** `/` 词表走前端预设（与首页 / 评估同源）：这一阶段本来就在跑 harness-create，列同一份技能 */
  const commands = usePresetCommands();
  /**
   * 右栏文件树的重拉信号：一轮对话结束后加一。
   *
   * `running` 由 true 落到 false 才算一轮结束 —— 首次挂载（false → false）不触发。
   * 放在这个组件里就够了：FileViewer 也在这里，阶段没挂载时不需要刷新。
   */
  const [workspaceRefresh, setWorkspaceRefresh] = useState(0);
  /** 产物技能弹层：列表就是产物 .claude/skills（构建生成与装配进来的同构） */
  const [skillsOpen, setSkillsOpen] = useState(false);
  const wasRunningRef = useRef(false);
  useEffect(() => {
    if (wasRunningRef.current && !chat.running) {
      setWorkspaceRefresh((current) => current + 1);
    }
    wasRunningRef.current = chat.running;
  }, [chat.running]);

  return (
    <>
    <SplitLayout
      split={split}
      left={
        <ConversationPane
          chat={chat}
          status={<LinkPill link={chat.link} />}
          empty={<BootState link={chat.link} />}
          placeholder={t('create.production.placeholder')}
          model={model}
          commands={commands}
          sendBlockedReason={sendBlockedReason}
          /*
           * 与首页同一颗 chip、同一个槽位：工具栏左侧 `+` 之后。
           * 换完只影响下一轮以 harness-create 开头的消息（见 useCreationChat）。
           */
          accessory={
            <>
              <KnowledgeSelect
                value={knowledge}
                onChange={onKnowledgeChange}
                disabled={chat.running || knowledgeSaving === true}
                saveError={knowledgeError ?? null}
              />
              {knowledgeStale === true && (
                <span className="knowledge-stale">
                  <Icon name="alert" size={12} />
                  <span className="knowledge-stale__text">{t('knowledge.stale')}</span>
                  <button
                    type="button"
                    className="knowledge-stale__rebuild"
                    disabled={chat.running || sendBlockedReason !== null}
                    title={sendBlockedReason ?? t('knowledge.rebuildHint')}
                    onClick={onRebuildWithoutKnowledge}
                  >
                    {t('knowledge.rebuild')}
                  </button>
                </span>
              )}
            </>
          }
        />
      }
      workClassName="ac-work ac-work--files"
      right={
        <>
          <WorkHead
            title={t('create.production.title')}
            desc={t('create.production.desc')}
            dir={agent?.dir ?? t('create.production.dirLoading')}
            skill="harness-create"
            onManageSkills={() => setSkillsOpen(true)}
          />
          <FileViewer
            agentId={agentId}
            refreshSignal={workspaceRefresh}
            // md / html 真渲染要拼 /fs/raw 地址；详情还没回来时交给 FileViewer 退回源码视图
            baseDir={agent === null ? null : `${agent.dir.replace(/\/+$/u, '')}/development`}
          />
        </>
      }
    />

    {skillsOpen && (
      <ProductSkillsDialog
        agentId={agentId}
        onClose={() => setSkillsOpen(false)}
        onOptimize={(text) => chat.replayInto(text, [])}
      />
    )}
    </>
  );
}
