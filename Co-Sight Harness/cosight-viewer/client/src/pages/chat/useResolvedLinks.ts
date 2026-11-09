// SPDX-License-Identifier: Apache-2.0
/**
 * @file useResolvedLinks.ts
 * @description 正文里的**相对**文件链接：先问服务端"这个路径在某个候选根下真的存在吗"，
 * 存在才渲染成可点按钮。
 *
 * 为什么需要校验：相对路径是自由文本，基准目录**不一定**是会话 cwd ——
 * 可能是 `development/`、智能体根、甚至工作区根。只按一个基准拼，要么打不开，
 * 要么指到另一个同名文件上。
 *
 * 交互取舍：
 * - 校验是**异步、批量、去重**的（`POST /session-files/resolve`），一个链接一次请求太贵；
 * - 未校验完 / 不存在 → 保持纯文本（不制造死链）；
 * - 文件可能在对话过程中才写出来，所以"不存在"的结果会按 `RECHECK_NULL_MS` 重试；
 * - 换智能体（候选根变化）时旧结果整体作废。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fsApi } from "../../api/fs-api";
import { collectRelativeMarkdownLinks } from "./file-mentions";

/** 输入变化后等这么久再发请求：流式输出期间别每个 delta 都打一次。 */
const RESOLVE_DEBOUNCE_MS = 300;
/** "不存在"结果的冷却时间：产物可能在几秒后才落盘。 */
const RECHECK_NULL_MS = 3000;

/**
 * @param texts 需要扫描的正文（历史助手消息 + 流式中的正文）
 * @param roots 候选基准，按优先级排列（见 `agentLinkRoots`）
 * @param extraTargets 额外要校验的相对路径（例如行内代码里与产物同名的路径）
 * @returns 解析函数：命中的相对路径 → 真实绝对路径；其余 → `undefined`（保持纯文本）
 */
export function useResolvedLinks(
  texts: readonly string[],
  roots: readonly string[],
  extraTargets: readonly string[] = []
): (raw: string) => string | undefined {
  const [resolved, setResolved] = useState<Readonly<Record<string, string | null>>>({});
  const resolvedRef = useRef(resolved);
  resolvedRef.current = resolved;

  /** 每个路径上次问服务端的时间（用于"不存在"的冷却重试）。 */
  const checkedAtRef = useRef(new Map<string, number>());
  /** 正在请求中的路径：避免同一批还没回来又发一次。 */
  const inFlightRef = useRef(new Set<string>());
  const rootsKey = roots.join("\u0000");

  // 候选根变了（通常 = 换了智能体）：旧解析结果全部作废
  useEffect(() => {
    resolvedRef.current = {};
    checkedAtRef.current.clear();
    setResolved({});
  }, [rootsKey]);

  const targets = useMemo(() => {
    const all = new Set<string>();
    for (const text of texts) {
      for (const raw of collectRelativeMarkdownLinks(text ?? "")) all.add(raw);
    }
    // 行内代码里的候选由调用方先按“与产物同名”过滤，避免普通代码引用也去请求
    for (const raw of extraTargets) all.add(raw);
    return [...all];
  }, [texts, extraTargets]);

  useEffect(() => {
    const now = Date.now();
    const pending = targets.filter((raw) => {
      if (inFlightRef.current.has(raw)) return false;
      const value = resolvedRef.current[raw];
      if (value === undefined) return true;
      if (value !== null) return false;
      return now - (checkedAtRef.current.get(raw) ?? 0) >= RECHECK_NULL_MS;
    });
    if (pending.length === 0) return;

    let cancelled = false;
    const timer = window.setTimeout(() => {
      const rootsSnapshot = [...roots];
      for (const raw of pending) inFlightRef.current.add(raw);

      void fsApi
        .resolve(pending.map((path) => ({ path, roots: rootsSnapshot })))
        .then((items) => {
          if (cancelled) return;
          const at = Date.now();
          for (const item of items) checkedAtRef.current.set(item.path, at);
          setResolved((prev) => {
            const next = { ...prev };
            for (const item of items) next[item.path] = item.resolved;
            return next;
          });
        })
        .catch(() => {
          // 解析失败不报错：保持纯文本，输入下次变化或冷却到期后再试
        })
        .finally(() => {
          for (const raw of pending) inFlightRef.current.delete(raw);
        });
    }, RESOLVE_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // roots 由调用方 memo 化；rootsKey 已覆盖其内容变化
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targets, rootsKey]);

  return useCallback(
    (raw: string) => resolved[raw] ?? undefined,
    [resolved]
  );
}
