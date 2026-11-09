// SPDX-License-Identifier: Apache-2.0
/**
 * @file AgentAvatar.tsx
 * @description 智能体头像:优先用 `agent.icon`,空则回落到 Bot 图标。
 * `icon` 可能是 emoji,也可能是图片 URL,两种都支持。
 * 被 composer 的已选 chip 与 `+` 菜单的智能体列表共用。
 */

import { Bot } from "lucide-react";

interface AgentAvatarProps {
  icon?: string;
  name?: string;
  /** sm = 20px(chip / 列表),md = 24px */
  size?: "sm" | "md";
}

/** 判断 icon 是图片地址而不是 emoji。 */
function isImageIcon(icon: string): boolean {
  return /^(https?:|data:|\/)/.test(icon);
}

export function AgentAvatar({ icon, name, size = "sm" }: AgentAvatarProps) {
  const box = size === "sm" ? "h-5 w-5 text-[11px]" : "h-6 w-6 text-xs";

  if (icon && isImageIcon(icon)) {
    return (
      <img
        src={icon}
        alt={name ?? ""}
        className={`${box} flex-shrink-0 rounded-full object-cover`}
      />
    );
  }

  return (
    <span
      className={`${box} flex flex-shrink-0 items-center justify-center rounded-full bg-surface-4 ${
        icon ? "" : "text-muted"
      }`}
      aria-hidden="true"
    >
      {icon || <Bot className="h-3.5 w-3.5" />}
    </span>
  );
}
