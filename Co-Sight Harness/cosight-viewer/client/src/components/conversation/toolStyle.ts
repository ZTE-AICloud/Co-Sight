// SPDX-License-Identifier: Apache-2.0
/**
 * @file toolStyle.ts
 * @description Per-tool visual styling — icon component, accent colour, and tinted
 * surface classes. Keeps the conversation viewer's tool blocks visually distinct so
 * users can scan a long transcript quickly.
 */

import {
  Wrench,
  Terminal,
  FileText,
  FilePlus2,
  FilePen,
  Search,
  Globe,
  Bot,
  ListTodo,
  Clock,
  Sparkles,
  FolderTree,
  type LucideIcon,
} from "lucide-react";

export interface ToolStyle {
  Icon: LucideIcon;
  /** Tailwind text colour for the icon and tool name. */
  text: string;
  /** Tailwind tinted background for the icon chip (15% opacity — sits behind
   *  the icon glyph; staying low-saturation keeps the icon legible). */
  chip: string;
  /** Tailwind background for solid fills like progress bars (60% opacity —
   *  high enough to read at a glance against the dark surface, distinct
   *  from the chip used for the icon backdrop). */
  bar: string;
  /** Tailwind border colour for the tool block when not in error state. */
  border: string;
}

const VIOLET: ToolStyle = {
  Icon: Wrench,
  text: "text-violet-300",
  chip: "bg-violet-500/15 text-violet-300",
  bar: "bg-violet-500/60",
  border: "border-violet-500/20",
};

const STYLES: Record<string, ToolStyle> = {
  bash: {
    Icon: Terminal,
    text: "text-emerald-300",
    chip: "bg-emerald-500/15 text-emerald-300",
    bar: "bg-emerald-500/60",
    border: "border-emerald-500/20",
  },
  read: {
    Icon: FileText,
    text: "text-sky-300",
    chip: "bg-sky-500/15 text-sky-300",
    bar: "bg-sky-500/60",
    border: "border-sky-500/20",
  },
  write: {
    Icon: FilePlus2,
    text: "text-violet-300",
    chip: "bg-violet-500/15 text-violet-300",
    bar: "bg-violet-500/60",
    border: "border-violet-500/20",
  },
  edit: {
    Icon: FilePen,
    text: "text-amber-300",
    chip: "bg-amber-500/15 text-amber-300",
    bar: "bg-amber-500/60",
    border: "border-amber-500/20",
  },
  multiedit: {
    Icon: FilePen,
    text: "text-amber-300",
    chip: "bg-amber-500/15 text-amber-300",
    bar: "bg-amber-500/60",
    border: "border-amber-500/20",
  },
  grep: {
    Icon: Search,
    text: "text-cyan-300",
    chip: "bg-cyan-500/15 text-cyan-300",
    bar: "bg-cyan-500/60",
    border: "border-cyan-500/20",
  },
  glob: {
    Icon: FolderTree,
    text: "text-cyan-300",
    chip: "bg-cyan-500/15 text-cyan-300",
    bar: "bg-cyan-500/60",
    border: "border-cyan-500/20",
  },
  webfetch: {
    Icon: Globe,
    text: "text-blue-300",
    chip: "bg-blue-500/15 text-blue-300",
    bar: "bg-blue-500/60",
    border: "border-blue-500/20",
  },
  websearch: {
    Icon: Globe,
    text: "text-blue-300",
    chip: "bg-blue-500/15 text-blue-300",
    bar: "bg-blue-500/60",
    border: "border-blue-500/20",
  },
  task: {
    Icon: Bot,
    text: "text-pink-300",
    chip: "bg-pink-500/15 text-pink-300",
    bar: "bg-pink-500/60",
    border: "border-pink-500/20",
  },
  agent: {
    Icon: Bot,
    text: "text-pink-300",
    chip: "bg-pink-500/15 text-pink-300",
    bar: "bg-pink-500/60",
    border: "border-pink-500/20",
  },
  todowrite: {
    Icon: ListTodo,
    text: "text-rose-300",
    chip: "bg-rose-500/15 text-rose-300",
    bar: "bg-rose-500/60",
    border: "border-rose-500/20",
  },
  schedulewakeup: {
    Icon: Clock,
    text: "text-orange-300",
    chip: "bg-orange-500/15 text-orange-300",
    bar: "bg-orange-500/60",
    border: "border-orange-500/20",
  },
  skill: {
    Icon: Sparkles,
    text: "text-fuchsia-300",
    chip: "bg-fuchsia-500/15 text-fuchsia-300",
    bar: "bg-fuchsia-500/60",
    border: "border-fuchsia-500/20",
  },
};

export function styleForTool(toolName: string | undefined | null): ToolStyle {
  if (!toolName) return VIOLET;
  const key = toolName.toLowerCase().replace(/[^a-z0-9]/g, "");
  return STYLES[key] ?? VIOLET;
}
