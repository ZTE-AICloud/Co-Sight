// SPDX-License-Identifier: Apache-2.0
/**
 * @file prompt-editor.ts
 * @description 输入框（contentEditable）与 DOM 的边界工具。
 *
 * 为什么从 textarea 换成 contentEditable：斜杠命令选中后要变成一颗
 * “蓝字 + 淡蓝底”的 token，textarea 无法只给其中一段文字加样式。
 *
 * token 用 `contentEditable=false` 的 `<span>` 实现：
 * - 读正文时用 `data-command-text` 还原成 `/<name>`（不依赖可见文字，改样式不会丢）；
 * - 退格会整颗删除，不会留下半截命令；
 * - 光标可以停在 token 前后，但不能进入 token 内部。
 */

import type { SlashCommandItem } from "./slash-commands";

const COMMAND_TEXT_ATTR = "data-command-text";

/** 读编辑器正文：token 还原成 `/<name>`，其余文本原样拼接。 */
export function readPromptText(root: HTMLElement): string {
  let text = "";

  const walk = (node: Node): void => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) {
        text += child.textContent ?? "";
        continue;
      }
      if (!(child instanceof HTMLElement)) continue;
      const commandText = child.getAttribute(COMMAND_TEXT_ATTR);
      if (commandText !== null) {
        text += commandText;
        continue;
      }
      if (child.tagName === "BR") {
        text += "\n";
        continue;
      }
      walk(child);
    }
  };

  walk(root);
  // 空 contentEditable 常被浏览器留一个 <br>，不能算一个换行
  return text === "\n" && root.childNodes.length === 1 ? "" : text;
}

/** 命令 token：蓝字 + 淡底，样式见 index.css 的 `.slash-command-chip`。 */
export function buildCommandToken(command: SlashCommandItem): HTMLSpanElement {
  const token = document.createElement("span");
  token.className = "slash-command-chip";
  token.contentEditable = "false";
  token.setAttribute(COMMAND_TEXT_ATTR, `/${command.name}`);
  token.title = command.description === "" ? `/${command.name}` : command.description;
  token.textContent = `/${command.name}`;
  return token;
}

/** 光标是否在编辑器内；在则返回“编辑器开头到光标”的字符数。 */
export function caretOffset(root: HTMLElement): number | null {
  const selection = window.getSelection();
  if (selection === null || selection.rangeCount === 0 || !selection.isCollapsed) return null;

  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer)) return null;

  const before = document.createRange();
  before.selectNodeContents(root);
  before.setEnd(range.startContainer, range.startOffset);
  return before.toString().length;
}

/** 把光标放到某个节点之后（用于插入 token 后继续输入）。 */
export function placeCaretAfter(node: Node): void {
  const range = document.createRange();
  range.setStartAfter(node);
  range.collapse(true);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

/** 在当前光标处插入纯文本（粘贴 / Shift+Enter 换行）。 */
export function insertPlainTextAtCaret(root: HTMLElement, text: string): void {
  root.focus();
  const selection = window.getSelection();
  if (selection === null || selection.rangeCount === 0) {
    root.append(document.createTextNode(text));
    placeCaretAfter(root.lastChild ?? root);
    return;
  }

  const range = selection.getRangeAt(0);
  if (!root.contains(range.startContainer)) {
    root.append(document.createTextNode(text));
    placeCaretAfter(root.lastChild ?? root);
    return;
  }

  range.deleteContents();
  const node = document.createTextNode(text);
  range.insertNode(node);
  placeCaretAfter(node);
}

/** 外部 value → DOM；值相同时不重写（否则打字时光标会跳）。 */
export function syncEditorText(root: HTMLElement, value: string): void {
  if (readPromptText(root) === value) return;
  root.replaceChildren();
  if (value !== "") root.textContent = value;
}
