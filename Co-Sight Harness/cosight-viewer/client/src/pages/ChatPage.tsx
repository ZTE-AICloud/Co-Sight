// SPDX-License-Identifier: Apache-2.0
/**
 * @file ChatPage.tsx
 * @description `/chat` —— 分享用的轻量对话页。
 *
 * 空态是大标题 + 输入框;点发送进入对话态。智能体/审批模式/推理强度在输入框左下角
 * `+` 菜单里选,模型在右下角。
 *
 * 只做对话,不含 RunPage 的历史会话恢复与仪表盘弹窗。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, FolderOpen, Loader2, X } from "lucide-react";
import { AgentPickerDialog } from "../components/chat/AgentPickerDialog";
import { ChatComposer } from "../components/chat/ChatComposer";
import { ChatConversation } from "../components/chat/ChatConversation";
import { FilesDrawer } from "../components/chat/files/FilesDrawer";
import { useChatSession } from "./chat/useChatSession";
import { resolveWorkspaceRoot } from "./chat/workspace-root";
import {
  agentLinkRoots,
  pathKey,
  resolveSessionPath,
  sessionFileFromPath,
  useSessionFiles,
  type SessionFile,
} from "./chat/useSessionFiles";

/**
 * 「召唤更多智能体」= 打开 `AgentPickerDialog` —— **本模块自己实现的选择器**。
 *
 * 这里只负责开关,以及把选中的专家落到会话上;取数、搜索、筛选、卡片渲染都在那个
 * 组件里,数据直接来自框架 `GET /api/experts`(与 `+` 菜单同一个来源)。
 *
 * 历史:更早是 `window.open(宿主 /experts)` 开新标签 —— 那是宿主 sandbox 不给
 * `allow-top-navigation` 时唯一跳得过去的做法,代价是把用户甩到另一个标签;
 * 中间还试过"弹框里 iframe 嵌宿主专家页",但它会把宿主的侧栏外壳一起带进框里,
 * 选择结果也只能靠跨源 postMessage 传回来。现在改成自己画。
 */

export function ChatPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const [prompt, setPrompt] = useState("");
  /** 「召唤更多智能体」弹框是否打开。 */
  const [pickerOpen, setPickerOpen] = useState(false);

  const session = useChatSession({
    initialAgentId: searchParams.get("agentId"),
    // 与 agentId 搭配;只传 agentId 时取该智能体的第一个版本
    initialVersionId: searchParams.get("versionId"),
    // 会话菜单 / 会话详情「恢复会话」跳转过来
    initialSessionId: searchParams.get("agentRuntimeSessionId"),
    // 只有引擎 resume 标识时先反查（`sessions/list?resumeSessionId=`）
    initialResumeSessionId: searchParams.get("resumeSessionId"),
  });

  /*
   * 本次对话产生/修改的文件。数据来自 `messages`（历史 + 实时工具结果），
   * 只认成功的 Write/Edit 系工具调用，不扫目录 —— 见 useSessionFiles 的文件头。
   */
  const { files, runtimeRoot } = useSessionFiles({
    messages: session.messages,
    toolExecutions: session.toolExecutions,
    agentId: session.selectedAgent?.id ?? null,
    agentDir: session.selectedAgent?.dir,
    agentRuntimeDir: session.selectedAgent?.runtimeDir,
    agentSource: session.selectedAgent?.source,
  });
  /**
   * 正文相对链接的候选基准：会话 cwd → development → 智能体根 → 工作区根。
   * 真正哪个成立由服务端校验（见 `useResolvedLinks`），这里只负责按优先级列出。
   */
  const linkRoots = useMemo(
    () => agentLinkRoots(runtimeRoot, session.selectedAgent?.dir),
    [runtimeRoot, session.selectedAgent?.dir]
  );

  /** 右侧文件抽屉是否打开 */
  const [filesOpen, setFilesOpen] = useState(false);
  /** 当前点开的文件；非 null 时抽屉显示预览 */
  const [selectedFile, setSelectedFile] = useState<SessionFile | null>(null);
  /**
   * 预览来源：会话正文/工具卡 vs 工作区树。
   *
   * 会话文件可能根本不在工作区里（runtime / 产物目录），所以不能总是把它
   * 摆在目录树右侧 —— 那会让人以为它属于当前工作区。
   */
  const [previewSource, setPreviewSource] = useState<"session" | "workspace">("workspace");

  /**
   * 会话工作区根：优先由 agent.dir 反推，其次按 workspaceId 查，最后退回当前默认工作区。
   * 换智能体（含恢复会话还原出的 agent）时重算。
   */
  const [workspaceRoot, setWorkspaceRoot] = useState<string | null>(null);
  const [workspaceRootLoading, setWorkspaceRootLoading] = useState(false);
  const agentDir = session.selectedAgent?.dir;
  const agentWorkspaceId = session.selectedAgent?.workspaceId;
  const agentId = session.selectedAgent?.id;
  useEffect(() => {
    let cancelled = false;
    setWorkspaceRootLoading(true);
    void resolveWorkspaceRoot(
      agentId === undefined ? null : { dir: agentDir, workspaceId: agentWorkspaceId }
    ).then((root) => {
      if (cancelled) return;
      setWorkspaceRoot(root);
      setWorkspaceRootLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [agentId, agentDir, agentWorkspaceId]);

  /**
   * 点工具卡路径 / 正文文件引用：打开右侧抽屉并展示这个文件。
   *
   * 命中文档产物集合就复用集合里的对象（能跟着“写入中 → 完成”更新）；
   * 没命中（例如正文里显式写出的脚本产物路径）就按路径合成一个只读条目。
   */
  const openFile = useCallback(
    (rawPath: string) => {
      const resolved = resolveSessionPath(rawPath, runtimeRoot);
      const match = files.find((file) => pathKey(file.path) === pathKey(resolved));
      setSelectedFile(match ?? sessionFileFromPath(rawPath, runtimeRoot));
      setPreviewSource("session");
      setFilesOpen(true);
    },
    [files, runtimeRoot]
  );

  /** 工作区树里点开一个文件：绝对路径直接进预览。 */
  const openWorkspaceFile = useCallback(
    (path: string) => {
      setSelectedFile(sessionFileFromPath(path, runtimeRoot));
      setPreviewSource("workspace");
      setFilesOpen(true);
    },
    [runtimeRoot]
  );

  // 换智能体（含从“无”到“有”）时收起抽屉：旧会话的文件不该留在新会话里
  useEffect(() => {
    setSelectedFile(null);
    setPreviewSource("workspace");
  }, [session.selectedAgent?.id]);

  /*
   * 抽屉里用“当前对象”而不是点击那一刻的快照：文件从“写入中”变成“完成”时，
   * 同路径的条目会被替换，这里要跟着用新对象。
   */
  const activeFile =
    selectedFile === null
      ? null
      : (files.find((file) => pathKey(file.path) === pathKey(selectedFile.path)) ??
        selectedFile);

  /** 抽屉折叠时的入口：会话态与空态都渲染，恢复会话后同样能打开工作区。 */
  const filesToggle = filesOpen ? null : (
    <button
      type="button"
      onClick={() => setFilesOpen(true)}
      aria-label={t("run.filesOpen")}
      title={t("run.filesOpen")}
      aria-expanded={false}
      className="absolute right-3 top-3 z-10 flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 bg-surface-2/90 text-muted shadow-sm backdrop-blur transition-colors hover:bg-surface-3 hover:text-primary"
    >
      <FolderOpen className="h-4 w-4" />
    </button>
  );

  const filesDrawer = filesOpen ? (
    <FilesDrawer
      source={previewSource}
      onClose={() => {
        setFilesOpen(false);
        // 关闭后回到工作区视图：下次从右上角打开时不应还停在上一张会话文件上
        setSelectedFile(null);
        setPreviewSource("workspace");
      }}
      workspaceRoot={workspaceRoot}
      workspaceRootLoading={workspaceRootLoading}
      file={activeFile}
      onOpenPath={openWorkspaceFile}
    />
  ) : null;

  /*
   * 注意:宿主专家页「使用」回跳带的 `?expert=<uuid>` **不在本页处理** ——
   * 它由 `lib/host-params.ts` 的 `applyHostEntry()` 在 Router 挂载之前翻译成
   * 本模块自己的 `?agentId=<uuid>`,于是这里的预选走的就是与商业版完全相同的
   * 一条路:交给 `useChatSession` 的 `initialAgentId`(只生效一次)。
   *
   * 这样本页与商业版逐行一致,也避免"URL 参数变成持续约束、用户改不了专家"那类问题。
   */

  /** “召唤更多智能体”:弹框嵌宿主的专家广场(见上方说明与 `AgentPickerDialog`)。 */
  function handleBrowseMoreAgents() {
    setPickerOpen(true);
  }

  /** 框内选好了:关框并设成当前智能体 —— 与 `+` 菜单里选中走的是同一个 API。 */
  function handleExpertPicked(expertId: string) {
    setPickerOpen(false);
    void session.selectAgent(expertId);
  }

  const composer = (
    <ChatComposer
      session={session}
      prompt={prompt}
      onPromptChange={setPrompt}
      onBrowseMoreAgents={handleBrowseMoreAgents}
      variant={session.isRunning ? "inline" : "hero"}
    />
  );

  /** 弹框元素:空态与对话态都要挂 —— 否则只有其中一种状态下能打开。 */
  const picker = pickerOpen ? (
    <AgentPickerDialog
      onClose={() => setPickerOpen(false)}
      onPicked={handleExpertPicked}
    />
  ) : null;

  const errorBanner = session.error && (
    <div className="mx-auto mt-4 flex w-full max-w-4xl items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-sm text-red-400">
      <span className="min-w-0 flex-1">{session.error}</span>
      <button
        type="button"
        onClick={session.clearError}
        aria-label={t("common:close")}
        className="flex-shrink-0 text-red-300 transition-colors hover:text-red-200"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );

  /**
   * 连接提示分三态：
   * - 重连中（未到阈值）：显示第 N 次 + 「立即重试」；
   * - 无法连接（达到阈值）：显示降级文案 + 「重新连接 / 刷新页面」；
   * - 刚恢复：绿色成功提示，2.5s 后自动收起。
   */
  const [showRecovered, setShowRecovered] = useState(false);
  // 重连过程是 disconnected → connecting → connected，中间会经过 connecting，
  // 所以不能用"上一次状态"判断，用一个跨越 connecting 的标记。
  // 同时要排除"本页首次连接"：新标签页打开时 socket 初始就是 disconnected，
  // 首连成功不能显示成"已重新连接"。
  const wasDisconnectedRef = useRef(false);
  const hasConnectedRef = useRef(false);
  useEffect(() => {
    if (
      session.connectionState === "disconnected" ||
      session.connectionState === "error"
    ) {
      if (hasConnectedRef.current) wasDisconnectedRef.current = true;
      return;
    }
    if (session.connectionState !== "connected") return;
    const recovered = hasConnectedRef.current && wasDisconnectedRef.current;
    hasConnectedRef.current = true;
    wasDisconnectedRef.current = false;
    if (!recovered || !session.hasSession) return;
    setShowRecovered(true);
    const timer = setTimeout(() => setShowRecovered(false), 2500);
    return () => clearTimeout(timer);
  }, [session.connectionState, session.hasSession]);

  const connectionBanner = session.isOffline ? (
    <div className="mx-auto mt-4 flex w-full max-w-4xl items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-sm text-red-400">
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <span className="min-w-0 flex-1">{t("run.connectionOffline")}</span>
      <button
        type="button"
        onClick={session.reconnect}
        disabled={session.connectionState === "connecting"}
        className="flex-shrink-0 rounded-lg bg-red-500/15 px-3 py-1 text-xs font-medium transition-colors hover:bg-red-500/25 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {t("run.reconnect")}
      </button>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="flex-shrink-0 rounded-lg px-3 py-1 text-xs font-medium text-red-300 transition-colors hover:bg-red-500/15"
      >
        {t("run.refreshPage")}
      </button>
    </div>
  ) : session.hasSession && session.connectionState !== "connected" ? (
    <div className="mx-auto mt-4 flex w-full max-w-4xl items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-600 dark:text-amber-400">
      <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin" />
      <span className="min-w-0 flex-1">
        {t("run.reconnectingAttempt", {
          attempt: Math.max(session.reconnectAttempts, 1),
        })}
      </span>
      <button
        type="button"
        onClick={session.reconnect}
        disabled={session.connectionState === "connecting"}
        className="flex-shrink-0 rounded-lg bg-amber-500/15 px-3 py-1 text-xs font-medium transition-colors hover:bg-amber-500/25 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {t("run.reconnectNow")}
      </button>
    </div>
  ) : session.hasSession && showRecovered ? (
    <div className="mx-auto mt-4 flex w-full max-w-4xl items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-600 dark:text-emerald-400">
      <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
      <span>{t("run.reconnected")}</span>
    </div>
  ) : null;

  // ─── 空态 ───
  if (!session.isRunning) {
    return (
      /*
       * 高度必须是**确定值**（与对话态一致），不能只给 min-height：
       * 右侧抽屉靠 flex stretch 铺满，如果父容器高度由内容撑开，预览一份长文档
       * 会把整个页面拉到几千像素高，分割线也跟着跑。
       */
      <div className="flex h-[calc(100vh-3rem)] min-w-0">
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          {errorBanner}
          {connectionBanner}
          {picker}
          {/*
            空态整体比几何居中**略高一点**(设计稿观感):靠上下不对称的内边距实现 ——
            内容在 padding box 里用 `m-auto` 居中（而不是 `justify-center`），这样
            窗口矮、内容溢出时仍然可以滚动，不会被居中裁掉。加大下边距的效果就是整体
            上移 `(pb − pt) / 2` = 44px。想再高/再低只改 `pb-32` 这一个值。
          */}
          <div className="flex min-h-0 flex-1 overflow-y-auto px-4 pb-32 pt-10 sm:px-6">
            <div className="m-auto flex w-full flex-col items-center gap-10">
              {/* 与原型一致:只有大标题,没有副标题 */}
              <h1 className="text-center text-4xl font-semibold tracking-tight text-primary sm:text-5xl">
                {t("run.emptyTitle")}
              </h1>
              <div className="w-full max-w-3xl">{composer}</div>
            </div>
          </div>
          {filesToggle}
        </div>
        {filesDrawer}
      </div>
    );
  }

  // ─── 对话态 ───
  // 用固定高度的 flex 列 + 消息区自己滚,composer 常驻底部。
  // 不依赖 Layout 的 overflow 行为:它的 `overflow-x-hidden` 会把 overflow-y
  // 计算成 auto,从而自带一个滚动容器,`sticky` 在那里并不可靠。
  return (
    <div className="flex h-[calc(100vh-3rem)] min-w-0 overflow-hidden">
      {/* 左：对话；右：文件抽屉（打开时挤压对话区，而不是盖在上面） */}
      <div className="relative flex min-w-0 flex-1 flex-col">
        {errorBanner}
        {connectionBanner}
        {picker}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <ChatConversation
            messages={session.messages}
            historyReady={session.historyReady}
            streamingContent={session.streamingContent}
            toolExecutions={session.toolExecutions}
            pendingApprovals={session.pendingApprovals}
            interactiveTools={session.interactiveTools}
            toolAnswers={session.toolAnswers}
            connectionState={session.connectionState}
            isLoading={session.isLoading}
            producedFiles={files}
            linkRoots={linkRoots}
            onAnswerChange={session.setToolAnswer}
            onApprovalRespond={session.respondApproval}
            onToolSubmit={session.respondTool}
            onOpenFile={openFile}
          />
        </div>
        {/*
          输入框外层**刻意不画上边框**:设计稿里消息区与输入框之间不留分割线。
          但 `bg-surface-1` 必须留着 —— 消息区是独立滚动容器,没有这层不透明底色,
          消息滚过输入框下方时会透出来。
        */}
        <div className="shrink-0 bg-surface-1 px-4 pb-4 pt-3 sm:px-6">
          <div className="mx-auto w-full max-w-4xl">{composer}</div>
        </div>
        {filesToggle}
      </div>

      {filesDrawer}
    </div>
  );
}
