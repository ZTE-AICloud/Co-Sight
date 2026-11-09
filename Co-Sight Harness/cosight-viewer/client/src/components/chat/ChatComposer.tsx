// SPDX-License-Identifier: Apache-2.0
/**
 * @file ChatComposer.tsx
 * @description `/chat` 的输入框。布局对齐设计稿:
 * 上部是输入区,底部一行左侧是 `+` 与已选智能体 chip、右侧是模型选择器与圆形发送按钮。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { ArrowUp, Check, ChevronDown, ChevronUp, Loader2, Plus, Square, X } from "lucide-react";
import type { UseChatSessionResult } from "../../pages/chat/useChatSession";
import type { AttachmentRef } from "../../attachments/types";
import { fetchEngineCommands, type EngineSlashCommand } from "../../api/harness-api";
import { useAttachmentPicker } from "../../attachments/useAttachmentPicker";
import mascotUrl from "../../assets/robot.png";
import { AgentAvatar } from "./AgentAvatar";
import { ComposerMenu, useFixedStyle } from "./ComposerMenu";
import { FileChip } from "./FileChip";
import { SlashCommandMenu, type SlashCommandAnchor } from "./SlashCommandMenu";
import {
  buildEngineSlashCommands,
  buildSlashCommands,
  groupSlashCommands,
  slashContextAt,
  type SlashCommandItem,
} from "./slash-commands";
import {
  buildCommandToken,
  caretOffset,
  insertPlainTextAtCaret,
  placeCaretAfter,
  readPromptText,
  syncEditorText,
} from "./prompt-editor";

/** 与下方 `w-72` 保持一致,用于判断向左还是向右对齐。 */
const MODEL_MENU_WIDTH = 288;

/** 一轮最多挂多少个附件：与服务端 `ATTACHMENTS_MAX` 同值。 */
const MAX_ATTACHMENTS = 20;

/** 引擎命令探测失败后的冷却时间：避免每次输入都重试一次 10 秒的探测进程。 */
const ENGINE_COMMANDS_RETRY_MS = 30_000;
/** 自由对话命令词的刷新周期：菜单再次打开且超过该时长时后台重取。 */
const ENGINE_COMMANDS_TTL_MS = 60_000;
/** 上一次成功的引擎命令清单；页面刷新后先用它秒开菜单，再后台刷新。 */
export const ENGINE_COMMANDS_CACHE_KEY = "cosight-viewer.engine-slash-commands.v1";

interface EngineCommandsCache {
  fetchedAt: number;
  items: EngineSlashCommand[];
}

/** 读本地缓存；损坏 / 不可用一律当作没有缓存。 */
function readEngineCommandsCache(): EngineCommandsCache | null {
  try {
    if (typeof window === "undefined") return null;
    const raw = window.localStorage.getItem(ENGINE_COMMANDS_CACHE_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw) as { fetchedAt?: unknown; items?: unknown };
    if (typeof parsed.fetchedAt !== "number" || !Array.isArray(parsed.items)) return null;
    const items = parsed.items.filter(
      (item): item is EngineSlashCommand =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as { name?: unknown }).name === "string" &&
        typeof (item as { description?: unknown }).description === "string",
    );
    return { fetchedAt: parsed.fetchedAt, items };
  } catch {
    return null;
  }
}

function writeEngineCommandsCache(items: EngineSlashCommand[]): void {
  try {
    if (typeof window === "undefined") return;
    const cache: EngineCommandsCache = { fetchedAt: Date.now(), items };
    window.localStorage.setItem(ENGINE_COMMANDS_CACHE_KEY, JSON.stringify(cache));
  } catch {
    /* localStorage 不可用（隐私模式 / 配额）时静默跳过 */
  }
}

/**
 * 词表是否完全一致（含顺序）。
 *
 * 后台刷新最常见的结果就是“一个字符都没变”；此时保持原数组引用，避免一次
 * 无意义的重渲染。菜单的滚动 effect 依赖 `items`，重渲染会把用户正在浏览的
 * 列表拉回当前高亮项，这是要避免的实际体感问题。
 */
export function sameSlashCommands(
  left: readonly SlashCommandItem[],
  right: readonly SlashCommandItem[],
): boolean {
  if (left.length !== right.length) return false;
  return left.every((item, index) => {
    const other = right[index];
    return (
      other !== undefined &&
      item.kind === other.kind &&
      item.name === other.name &&
      item.description === other.description
    );
  });
}

/** `/` 菜单状态；`start` 是 `/` 的下标，插入时从它开始替换 */
interface SlashState {
  query: string;
  start: number;
  active: number;
  anchor: SlashCommandAnchor;
}

export interface ChatComposerProps {
  session: UseChatSessionResult;
  prompt: string;
  onPromptChange: (value: string) => void;
  /** “召唤更多智能体”跳转(由页面决定路由) */
  onBrowseMoreAgents: () => void;
  /**
   * 空态用 hero(输入区更高、字号更大);对话态用 inline(紧凑)。
   */
  variant?: "hero" | "inline";
}

export function ChatComposer({
  session,
  prompt,
  onPromptChange,
  onBrowseMoreAgents,
  variant = "inline",
}: ChatComposerProps) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const plusRef = useRef<HTMLButtonElement>(null);
  const modelTriggerRef = useRef<HTMLButtonElement>(null);
  const modelMenuRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  /** 整个输入卡片：`/` 菜单以它为锚点，避免盖住底部工具栏 */
  const rootRef = useRef<HTMLDivElement>(null);
  const [attachments, setAttachments] = useState<AttachmentRef[]>([]);
  const [pickError, setPickError] = useState<string | null>(null);
  const { pick: pickFiles, element: pickerElement } = useAttachmentPicker();
  /** `/` 菜单；null = 未打开 */
  const [slash, setSlash] = useState<SlashState | null>(null);
  /**
   * 用户按 Esc 关掉菜单时的正文。keyup / 光标移动会再次判断上下文，
   * 没有这个标记的话 Esc 会被同一次按键的 keyup 立刻重新打开。
   * 只要用户继续输入就清空。
   */
  const dismissedSlashRef = useRef<string | null>(null);
  /**
   * 自由对话的 `/` 词表来自引擎（`/engine/commands/list`）。
   *
   * 该接口冷启动约 10 秒，所以不能在输入时同步取；挂载后后台预取一次，
   * 失败 30 秒内不重试，避免每次按键都拉起一次探测进程。
   */
  const [initialEngineCache] = useState(readEngineCommandsCache);
  const [engineCommands, setEngineCommands] = useState<SlashCommandItem[]>(() =>
    initialEngineCache === null ? [] : buildEngineSlashCommands(initialEngineCache.items),
  );
  /** 首次（无缓存）冷启动时给菜单一个即时反馈；有缓存时直接显示旧列表。 */
  const [engineCommandsLoading, setEngineCommandsLoading] = useState(false);
  const engineCommandsLoadedRef = useRef(initialEngineCache !== null);
  const engineCommandsFetchedAtRef = useRef(initialEngineCache?.fetchedAt ?? 0);
  const engineCommandsInFlightRef = useRef<Promise<void> | null>(null);
  const engineCommandsFailedAtRef = useRef(0);

  /**
   * 取引擎命令。
   *
   * - `force`：页面刚挂载时用，即使本地缓存还新鲜也后台刷新一次；
   * - 非 force：限定 TTL，菜单重复开关不重复请求；
   * - 失败：保留旧词表，30 秒内不重试；页面刷新/重进会重新取。
   */
  const loadEngineCommands = useCallback((force = false) => {
    if (engineCommandsInFlightRef.current !== null) return;

    const hasFreshCommands =
      engineCommandsLoadedRef.current &&
      Date.now() - engineCommandsFetchedAtRef.current < ENGINE_COMMANDS_TTL_MS;
    if (!force && hasFreshCommands) return;

    if (Date.now() - engineCommandsFailedAtRef.current < ENGINE_COMMANDS_RETRY_MS) return;

    setEngineCommandsLoading(true);
    const task = fetchEngineCommands()
      .then((items) => {
        engineCommandsLoadedRef.current = true;
        engineCommandsFetchedAtRef.current = Date.now();
        const next = buildEngineSlashCommands(items);
        // 内容与顺序都没变时保持原引用：不触发重渲染，也不会扰动菜单滚动
        setEngineCommands((prev) => (sameSlashCommands(prev, next) ? prev : next));
        writeEngineCommandsCache(items);
      })
      .catch((error: unknown) => {
        engineCommandsFailedAtRef.current = Date.now();
        console.warn("[ChatComposer] failed to load engine slash commands:", error);
      })
      .finally(() => {
        if (engineCommandsInFlightRef.current === task) {
          engineCommandsInFlightRef.current = null;
          setEngineCommandsLoading(false);
        }
      });
    engineCommandsInFlightRef.current = task;
  }, []);

  const {
    selectedAgent,
    models,
    modelId,
    setModelId,
    refreshAgents,
    refreshModels,
    refreshingModels,
    isLoading,
    hasSession,
    switchingModel,
    connectionState,
  } = session;

  /**
   * 断线期间发送和停止都不可用：避免"发送后才报错"和"假停止"。
   *
   * 注意首屏与"还没建立会话"的情况：此时 socket 本来就是 disconnected，
   * 首帧由 `send` 自己按需 connect，不能把发送按钮锁死；只有在
   * **已有会话**且连接断开，或重连次数达到阈值时才禁用。
   */
  const isOffline = session.isOffline;
  const disconnected = isOffline || (hasSession && connectionState !== "connected");
  const isHero = variant === "hero";
  const selectedModelName =
    models.find((model) => model.id === modelId)?.name ?? t("run.selectModel");
  const placeholderText = disconnected
    ? t("run.inputWaitingReconnect")
    : t("run.inputMessage");

  const isFreeChat = session.selectedAgent == null;

  /**
   * 菜单词表：
   * - 选中智能体：只用该智能体详情里的命令 + 技能；
   * - 自由对话：用引擎 `/` 菜单（用户级 + 插件；不传 cwd，不含工作区项目级命令）。
   *
   * 智能体命令为空时**不**回落到引擎清单：避免显示智能体实际不可执行的命令。
   */
  const slashCommands = useMemo(
    () =>
      isFreeChat
        ? engineCommands
        : buildSlashCommands(session.selectedAgent?.commands, session.selectedAgent?.skills),
    [
      isFreeChat,
      engineCommands,
      session.selectedAgent?.commands,
      session.selectedAgent?.skills,
    ]
  );

  /** 首次冷启动、还没有任何词表时，菜单先显示“正在读取命令…”。 */
  const engineMenuLoading =
    isFreeChat && engineCommandsLoading && slashCommands.length === 0;

  /** 根据当前输入与光标刷新 `/` 菜单；不满足首 token 条件就关闭 */
  const syncSlash = useCallback(
    (value: string, caret: number) => {
      const el = editorRef.current;
      if (el === null) {
        setSlash(null);
        return;
      }
      // Esc 关闭后同一段文本不再弹（否则 keyup 会把它重新打开）
      if (dismissedSlashRef.current === value) {
        setSlash(null);
        return;
      }
      // 只在光标位于末尾时触发：在已有文本中间编辑时不猜测插入位置
      if (caret !== value.length) {
        setSlash(null);
        return;
      }

      const context = slashContextAt(value, caret);
      if (context === null) {
        setSlash(null);
        return;
      }
      const showLoading = isFreeChat && engineCommandsLoading && slashCommands.length === 0;
      if (slashCommands.length === 0 && !showLoading) {
        setSlash(null);
        return;
      }
      if (groupSlashCommands(slashCommands, context.query).length === 0 && !showLoading) {
        setSlash(null);
        return;
      }

      // 锚整个输入卡片：菜单在输入框上方展开，宽度与输入框一致
      const anchorRect = (rootRef.current ?? el).getBoundingClientRect();
      const anchor: SlashCommandAnchor = {
        left: anchorRect.left,
        top: anchorRect.top,
        bottom: anchorRect.bottom,
        width: anchorRect.width,
      };
      setSlash((current) =>
        current !== null && current.query === context.query && current.start === context.start
          ? { ...current, anchor }
          : { query: context.query, start: context.start, active: 0, anchor }
      );
    },
    [slashCommands, isFreeChat, engineCommandsLoading]
  );

  const slashItems = useMemo(
    () => (slash === null ? [] : groupSlashCommands(slashCommands, slash.query)),
    [slashCommands, slash]
  );

  // 外部改 prompt（发送后清空 / 预置填充）→ 回写编辑器；值相同不重写，避免光标跳
  useEffect(() => {
    const el = editorRef.current;
    if (el === null) return;
    syncEditorText(el, prompt);
  }, [prompt]);

  // 外部 prompt 变化 / 详情里的命令与技能到达时重新判断
  useEffect(() => {
    const el = editorRef.current;
    if (el === null) return;
    syncSlash(readPromptText(el), caretOffset(el) ?? -1);
  }, [prompt, slashCommands, syncSlash]);

  // 自由对话挂载后后台预取引擎命令；即使有本地缓存也强制刷新一次
  useEffect(() => {
    if (!isFreeChat) return;
    loadEngineCommands(true);
  }, [isFreeChat, loadEngineCommands]);

  // 上次失败已过冷却期：用户再次输入 `/` 时补一次重试
  useEffect(() => {
    if (!isFreeChat || engineCommands.length > 0) return;
    const el = editorRef.current;
    if (el === null) return;
    if (slashContextAt(readPromptText(el), caretOffset(el) ?? -1) === null) return;
    loadEngineCommands();
  }, [prompt, isFreeChat, engineCommands.length, loadEngineCommands]);

  /*
   * 菜单再次打开时检查词表是否过期。
   *
   * 命令可能在本机被增删；页面一直开着时不能只靠挂载那一次。超过 TTL 就后台
   * 重取，旧列表继续可点，新结果回来后由 `slashCommands` 的 effect 刷新菜单。
   */
  const slashOpen = slash !== null;
  useEffect(() => {
    if (!isFreeChat || !slashOpen) return;
    loadEngineCommands();
  }, [slashOpen, isFreeChat, loadEngineCommands]);

  // 换智能体 / 清空智能体：旧词表不该继续弹
  useEffect(() => {
    setSlash(null);
  }, [session.selectedAgent?.id]);

  // 点击菜单以外的地方关闭（菜单项自己 preventDefault，不会丢焦点）
  useEffect(() => {
    if (slash === null) return;
    const onMouseDown = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (target?.closest("[data-slash-menu]") !== null) return;
      if (editorRef.current?.contains(target as Node)) return;
      // 用户主动点走 = 关闭；后台命令刷新到达时不能把菜单重新弹出来
      const el = editorRef.current;
      dismissedSlashRef.current = el === null ? null : readPromptText(el);
      setSlash(null);
    };
    document.addEventListener("mousedown", onMouseDown, true);
    return () => document.removeEventListener("mousedown", onMouseDown, true);
  }, [slash]);

  // 随内容长高,到 max-h 后内部滚动
  useEffect(() => {
    const el = editorRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [prompt, isHero]);

  // 智能体一旦开聊就不可再改（会话级属性）。
  const agentLocked = hasSession;
  // 模型可在 run 结束后切换：run 进行中或切换在途时锁住下拉。
  // 悲观切换期间保持显示旧模型，避免展示尚未生效的值。
  const modelLocked = isLoading || switchingModel;

  // 锁住时收起对应浮层；`+` 仍保留（只用于添加文件），智能体项由菜单自行隐藏
  useEffect(() => {
    if (agentLocked) setMenuOpen(false);
    if (modelLocked) setModelOpen(false);
  }, [agentLocked, modelLocked]);

  /*
   * 打开模型下拉时重拉一次。
   *
   * 模型是在宿主的「设置弹窗」里增删/切换的——不换路由、不重建 iframe，模块拿不到
   * 变更事件，只能在下拉打开这一刻对齐。请求很轻（框架本机一次 GET），失败时
   * hook 会保留旧列表，不会把下拉变成空态。
   */
  useEffect(() => {
    if (modelOpen) void refreshModels();
  }, [modelOpen, refreshModels]);

  /** 打开 `+` 的「智能体」二级菜单时重拉：智能体同上，也是在别处增删的。 */
  const handleOpenAgentSection = useCallback(() => {
    void refreshAgents();
  }, [refreshAgents]);

  // 模型浮层的关闭:外部点击 / Esc
  useEffect(() => {
    if (!modelOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setModelOpen(false);
    };
    const onMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (modelTriggerRef.current?.contains(target)) return;
      if (modelMenuRef.current?.contains(target)) return;
      setModelOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onMouseDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onMouseDown, true);
    };
  }, [modelOpen]);

  const modelMenuStyle = useFixedStyle(modelOpen, () => {
    const rect = modelTriggerRef.current?.getBoundingClientRect();
    if (!rect) return {};
    const right = Math.max(8, window.innerWidth - rect.right);
    const bottom = Math.max(8, window.innerHeight - rect.top + 8);
    // 放不下就以左边界为准
    return rect.right - MODEL_MENU_WIDTH < 8 ? { left: 8, bottom } : { right, bottom };
  }, []);

  /** 把编辑器正文同步给父组件；输入、粘贴、Shift+Enter 共用。 */
  function emitPrompt(): void {
    const el = editorRef.current;
    if (el === null) return;
    const value = readPromptText(el);
    dismissedSlashRef.current = null;
    onPromptChange(value);
    syncSlash(value, caretOffset(el) ?? -1);
  }

  /** 光标移动（鼠标点选 / 方向键）后重新判断是否还是 `/` 上下文。 */
  function syncSlashFromEditor(): void {
    const el = editorRef.current;
    if (el === null) return;
    syncSlash(readPromptText(el), caretOffset(el) ?? -1);
  }

  /** 输入法拼字中途不弹菜单：那时正文里是拼音，等候选词落定再判断。 */
  function handleInput(event: React.FormEvent<HTMLDivElement>) {
    const el = event.currentTarget;
    const value = readPromptText(el);
    dismissedSlashRef.current = null;
    onPromptChange(value);
    if ((event.nativeEvent as InputEvent).isComposing === true) {
      setSlash(null);
      return;
    }
    syncSlash(value, caretOffset(el) ?? -1);
  }

  /**
   * 把选中的命令/技能插成一颗不可拆分的 token，并把光标放到 token 之后。
   * 只在首 token 上下文里触发，因此可以直接替换编辑器内容。
   */
  function acceptCommand(command: SlashCommandItem) {
    const el = editorRef.current;
    if (el === null) return;

    const value = readPromptText(el);
    const context = slashContextAt(value, caretOffset(el) ?? value.length);
    if (context === null) {
      setSlash(null);
      return;
    }

    const token = buildCommandToken(command);
    const space = document.createTextNode(" ");
    el.replaceChildren(token, space);
    onPromptChange(`/${command.name} `);
    setSlash(null);
    el.focus();
    placeCaretAfter(space);
  }

  /**
   * 菜单打开时先把键盘交给菜单：Enter 是“选中命令”，不是“发送”，
   * 不拦就会把半截 `/bu` 发出去。
   *
   * 其余情况：Enter 发送，Shift+Enter 换行。
   */
  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.nativeEvent.isComposing) return;

    // 词表还在加载：菜单里只有提示行，Enter / Tab 不能被当成“发送”
    if (slash !== null && engineMenuLoading && slashItems.length === 0) {
      if (event.key === "Escape") {
        event.preventDefault();
        const el = editorRef.current;
        dismissedSlashRef.current = el === null ? null : readPromptText(el);
        setSlash(null);
      }
      if (
        event.key === "Enter" ||
        event.key === "Tab" ||
        event.key === "ArrowDown" ||
        event.key === "ArrowUp"
      ) {
        event.preventDefault();
      }
      return;
    }

    if (slash !== null && slashItems.length > 0) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setSlash((current) =>
          current === null
            ? current
            : {
                ...current,
                active:
                  (current.active + step + slashItems.length) % slashItems.length,
              }
        );
        return;
      }
      if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
        event.preventDefault();
        const choice = slashItems[slash.active] ?? slashItems[0];
        if (choice !== undefined) acceptCommand(choice);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        const el = editorRef.current;
        dismissedSlashRef.current = el === null ? null : readPromptText(el);
        setSlash(null);
        return;
      }
    }

    if (event.key === "Enter" && event.shiftKey) {
      // contentEditable 默认会插入 <div>/<br>，读正文时形状不稳定；
      // 这里统一插一个 "\n" 文本节点，white-space: pre-wrap 负责显示。
      event.preventDefault();
      const el = editorRef.current;
      if (el === null) return;
      insertPlainTextAtCaret(el, "\n");
      emitPrompt();
      return;
    }

    if (event.key !== "Enter") return;
    event.preventDefault();
    void submit();
  }

  /** 只收纯文本，避免把外部 HTML 结构带进编辑器。 */
  function handlePaste(event: React.ClipboardEvent<HTMLDivElement>) {
    event.preventDefault();
    const el = editorRef.current;
    if (el === null) return;
    insertPlainTextAtCaret(el, event.clipboardData.getData("text/plain"));
    emitPrompt();
  }

  /** 打开「添加文件 → 本地文件」选择器；选中项并入待发附件。 */
  async function addFiles() {
    if (attachments.length >= MAX_ATTACHMENTS) return;
    setPickError(null);
    try {
      const picked = await pickFiles(MAX_ATTACHMENTS - attachments.length);
      if (picked.length === 0) return;
      setAttachments((current) => {
        const next = [...current];
        for (const file of picked) {
          if (next.length >= MAX_ATTACHMENTS) break;
          // 同一路径只挂一份（服务端发送时也会去重）
          if (next.some((item) => item.id === file.id)) continue;
          next.push(file);
        }
        return next;
      });
    } catch (error) {
      setPickError(error instanceof Error ? error.message : String(error));
    }
  }

  async function submit() {
    if (
      (!prompt.trim() && attachments.length === 0) ||
      isLoading ||
      switchingModel ||
      disconnected
    )
      return;
    const text = prompt;
    // 以 hook 的返回值为准,避免"已发出但输入框没清"或反之。
    // 被拒(未选智能体等)时保留输入与附件,由 hook 给出提示。
    const sent = await session.send(text, attachments);
    if (sent) {
      onPromptChange("");
      setAttachments([]);
    }
  }

  return (
    <div
      ref={rootRef}
      className={`chat-composer relative ${isHero ? "px-4 pb-3 pt-4" : "px-3 pb-2.5 pt-3"}`}
    >
      {/*
        首页(空态)输入框右上角的小机器人:整个露在框体上沿之上、下沿与顶边齐平。
        只在 hero 出现 —— 对话态的输入框挤在底部,再挂一张图只会添乱。纯装饰:alt 为空
        + aria-hidden,且不接指针事件(定位见 `index.css` 的 `.chat-composer-mascot`)。
      */}
      {isHero && <img src={mascotUrl} alt="" aria-hidden="true" className="chat-composer-mascot" />}

      {attachments.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5 px-1">
          {attachments.map((file) => (
            <FileChip
              key={file.id}
              file={{ name: file.name, path: file.path }}
              removeDisabled={isLoading}
              onRemove={() =>
                setAttachments((current) => current.filter((item) => item.id !== file.id))
              }
            />
          ))}
        </div>
      )}

      {pickError !== null && (
        <p className="mb-1 px-1 text-xs text-red-400" role="alert">
          {pickError}
        </p>
      )}

      {/*
        用 contentEditable 而不是 textarea：命令/技能选中后要变成一颗
        蓝字 + 淡蓝底的 token，textarea 无法只给其中一段文字加样式。
        正文仍是纯字符串（`readPromptText` 负责 token → `/name` 的还原）。
      */}
      <div className="relative">
        <div
          ref={editorRef}
          role="textbox"
          aria-multiline="true"
          aria-label={t("run.inputMessage")}
          contentEditable
          suppressContentEditableWarning
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          onKeyUp={syncSlashFromEditor}
          onMouseUp={syncSlashFromEditor}
          onPaste={handlePaste}
          className={`chat-composer-editor w-full overflow-y-auto whitespace-pre-wrap break-words bg-transparent px-1 leading-relaxed text-primary focus:outline-none ${
            isHero ? "max-h-[40vh] min-h-[5.5rem] text-base" : "max-h-52 min-h-[2.25rem] text-sm"
          }`}
        />
        {prompt === "" && (
          <span
            aria-hidden="true"
            className={`pointer-events-none absolute left-1 top-0 select-none leading-relaxed text-muted ${
              isHero ? "text-base" : "text-sm"
            }`}
          >
            {placeholderText}
          </span>
        )}
      </div>

      {/* 底部行:左侧 `+`（添加文件 / 开聊前选智能体）、已选智能体 chip、模型与发送键 */}
      <div className="flex items-center gap-2">
        <button
          ref={plusRef}
          type="button"
          onClick={() => setMenuOpen((prev) => !prev)}
          aria-label={menuOpen ? t("common:close") : t("run.openMenu")}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-4 hover:text-primary"
        >
          {menuOpen ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
        </button>

        {/* 已选智能体 chip。开聊后只作展示,不再提供移除。 */}
        {selectedAgent && (
          <span className="flex min-w-0 items-center gap-1.5 rounded-full bg-surface-4 py-1 pl-1.5 pr-2 text-xs text-secondary">
            <AgentAvatar icon={selectedAgent.icon} name={selectedAgent.name} />
            <span className={`max-w-[10rem] truncate ${agentLocked ? "" : "pr-0.5"}`}>
              {selectedAgent.name}
            </span>
            {selectedAgent.resolving && <Loader2 className="h-3 w-3 animate-spin text-muted" />}
            {!agentLocked && (
              <button
                type="button"
                onClick={session.clearAgent}
                aria-label={t("run.removeAgent")}
                className="flex-shrink-0 text-muted transition-colors hover:text-primary"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </span>
        )}

        <div className="flex-1" />

        {modelLocked ? (
          // run 进行中 / 切换在途：只显示当前模型。
          // 悲观切换确认前这里仍是旧值，spinner 只表示“正在切”。
          <span
            aria-label={t("run.model")}
            aria-busy={switchingModel}
            className="flex max-w-[14rem] flex-shrink-0 items-center gap-1.5 px-2 py-1.5 text-xs font-medium text-muted"
          >
            <span className="truncate">{selectedModelName}</span>
            {switchingModel && <Loader2 className="h-3 w-3 flex-shrink-0 animate-spin" />}
          </span>
        ) : (
          <button
            ref={modelTriggerRef}
            type="button"
            onClick={() => setModelOpen((prev) => !prev)}
            aria-haspopup="listbox"
            aria-expanded={modelOpen}
            aria-label={t("run.model")}
            className="flex max-w-[14rem] flex-shrink-0 items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-secondary transition-colors hover:bg-surface-4 hover:text-primary"
          >
            {/* 模型列表向上展开,所以按开合切上/下箭头(与 WorkBuddy 一致) */}
            <span className="truncate">{selectedModelName}</span>
            {modelOpen ? (
              <ChevronUp className="h-3.5 w-3.5 flex-shrink-0" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 flex-shrink-0" />
            )}
          </button>
        )}

        {isLoading && !disconnected ? (
          <button
            type="button"
            onClick={() => void session.stop()}
            aria-label={t("run.stop")}
            className="chat-stop flex h-8 w-8 flex-shrink-0 items-center justify-center transition-colors"
          >
            {/* lucide 的 `Square` 默认 `fill="none"`,只描边 —— 不补这一笔就是"白线空心
                方框",而设计要的是**实心白方块**,所以显式填充 `currentColor`(按钮前景色)。 */}
            <Square className="h-3.5 w-3.5" fill="currentColor" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void submit()}
            disabled={
              (!prompt.trim() && attachments.length === 0) || disconnected || switchingModel
            }
            aria-label={t("run.send")}
            className="chat-send flex h-8 w-8 flex-shrink-0 items-center justify-center transition-colors disabled:cursor-not-allowed"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        )}
      </div>

      {/*
        开聊后智能体不可再改，但「添加文件」仍可用；菜单由 canSelectAgent 控制
        是否显示智能体一项。
      */}
      <ComposerMenu
        open={menuOpen}
        triggerRef={plusRef}
        agents={session.agents}
        selectedAgent={selectedAgent}
        canSelectAgent={!agentLocked}
        onPickLocalFiles={() => {
          setMenuOpen(false);
          void addFiles();
        }}
        onSelectAgent={(agent) => void session.selectAgent(agent.id, undefined, agent)}
        onOpenAgentSection={handleOpenAgentSection}
        /*
         * 顺手把菜单收掉:弹框是浮在菜单**之上**的新层,菜单不会自己消失,
         * 于是选完专家回来还会看到它杵在那儿。
         */
        onBrowseMoreAgents={() => {
          setMenuOpen(false);
          onBrowseMoreAgents();
        }}
        onClose={() => setMenuOpen(false)}
      />

      {pickerElement}

      {/*
        模型列表:portal 到 document.body。
        不能留在 composer 里 —— composer 根节点带 `overflow-x: clip`,
        被裁掉的区域连命中测试都没有,浮层会既显示不全又点不中。
      */}
      {modelOpen &&
        createPortal(
          <div
            ref={modelMenuRef}
            role="listbox"
            aria-label={t("run.model")}
            style={modelMenuStyle}
            className="fixed z-[60] max-h-[60vh] w-72 overflow-y-auto rounded-2xl border border-border/60 bg-surface-2 p-1.5 shadow-2xl animate-fade-in"
          >
            {models.length === 0 ? (
              <p className="px-2 py-3 text-center text-xs text-muted">
                {refreshingModels ? t("common:loading") : t("common:noData")}
              </p>
            ) : (
              models.map((model) => {
                const isSelected = model.id === modelId;
                return (
                  <button
                    key={model.id}
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => {
                      setModelId(model.id);
                      setModelOpen(false);
                    }}
                    className={`flex w-full items-center gap-2 rounded-xl px-2.5 py-2 text-left transition-colors ${
                      isSelected ? "bg-surface-4" : "hover:bg-surface-4"
                    }`}
                  >
                    <span
                      className={`min-w-0 flex-1 truncate text-sm ${
                        isSelected ? "font-medium text-primary" : "text-secondary"
                      }`}
                    >
                      {model.name}
                    </span>
                    {isSelected && <Check className="h-4 w-4 flex-shrink-0 text-accent" />}
                  </button>
                );
              })
            )}
          </div>,
          document.body,
        )}

      {/* `/` 命令候选：同样 portal 到 body，避免被输入框容器裁剪 */}
      {slash !== null &&
        (slashItems.length > 0 || engineMenuLoading) &&
        createPortal(
          <SlashCommandMenu
            items={slashItems}
            active={Math.min(slash.active, slashItems.length - 1)}
            anchor={slash.anchor}
            label={t("run.slashCommandsLabel")}
            hint={t("run.slashCommandsHint")}
            loading={engineMenuLoading}
            loadingLabel={t("run.slashCommandsLoading")}
            sectionLabels={{
              command: t("run.slashCommandsSection"),
              skill: t("run.slashSkillsSection"),
            }}
            onActive={(index) =>
              setSlash((current) => (current === null ? current : { ...current, active: index }))
            }
            onPick={(index) => {
              const choice = slashItems[index];
              if (choice !== undefined) acceptCommand(choice);
            }}
          />,
          document.body,
        )}
    </div>
  );
}
