import { useEffect, useState } from 'react';
import { knowledgeApi } from './knowledge';
import type { KnowledgeWorkflow } from './knowledge';

/**
 * 把「只有 id」的知识检索值补成完整工作流，chip 上才有名称可显示。
 *
 * 设计页打开时，自动恢复出来的值来自会话消息 / `Agent.initialInput`，那里只存了
 * `--knowledge-workflow-id <id>` 这一段 —— 没有名称。这里拉一次已发布列表按 id 匹配：
 *
 * - 匹配上 → 返回真实工作流（名称、描述都有）；
 * - 匹配不上 / 列表拉失败 → 返回 null，调用方退回显示 id。
 *
 * 名称只是展示优化：拉不到不该把 chip 弄没，也不该在这里弹错误 —— 用户点开弹层时
 * `KnowledgeSelect` 自己会再拉一次并显式报错。只在有 id 时才请求。
 */
export function useKnowledgeWorkflow(id: string | null): KnowledgeWorkflow | null {
  const [resolved, setResolved] = useState<KnowledgeWorkflow | null>(null);

  useEffect(() => {
    // 换了 id 先清掉：不能拿上一条的名称顶着新 id 显示
    setResolved(null);
    if (id === null) return;

    let cancelled = false;
    knowledgeApi
      .listWorkflows()
      .then((result) => {
        if (cancelled) return;
        setResolved(result.items.find((item) => item.id === id) ?? null);
      })
      .catch(() => {
        // 名称补不上就显示 id（见文件头注释）
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  return resolved;
}
