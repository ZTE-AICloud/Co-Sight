/**
 * RAG 知识库表单的草稿、校验与请求体映射（纯逻辑，不碰 React 也不碰 i18n）。
 *
 * 与 `agentProxyForm.ts` 同一种分工：校验规则跟着契约（`harness-shared` 里的
 * `RAG_KB_*` 上限与 `ragKnowledgeRouteUrlSchema`），措辞留给 `features/config/issues.ts`。
 *
 * `routeUrl` 是这里唯一有安全含义的地址字段，所以规则比"是不是 http(s)"多一条：
 * **不能内嵌账号密码**。服务端也会拒（契约里的 refine），前端再判一次是纵深防御——
 * 用户不该先看到一次 422 才知道自己填的地址会被浏览器带着凭据发出去。
 * 要登录就把账号密码填在下面两栏里，那是**存储**，不是拼进地址。
 *
 * 密码完全复用 `features/config/secret.ts` 的 D26 三态（留空保持 / 送值覆盖 /
 * 送 `null` 清除），与模型密钥、代理令牌同一套实现：两份各写一遍的话，
 * "留空到底是保持还是清除"迟早会在其中一份里走样。
 */

import {
  RAG_KB_API_KEY_MAX_LENGTH,
  RAG_KB_DESCRIPTION_MAX_LENGTH,
  RAG_KB_NAME_MAX_LENGTH,
  RAG_KB_PASSWORD_MAX_LENGTH,
  RAG_KB_ROUTE_MAX_LENGTH,
  RAG_KB_USERNAME_MAX_LENGTH,
  type CreateRagKnowledgeBaseInput,
  type RagKnowledgeBase,
  type UpdateRagKnowledgeBaseInput,
} from 'harness-shared';

import type { FieldIssue } from '../config/issues';
import { isHttpUrl } from '../config/parse';
import { EMPTY_SECRET, resolveSecret, type SecretDraft } from '../config/secret';

export interface RagKnowledgeDraft {
  name: string;
  routeUrl: string;
  /** 登录账号；空串表示这条路由不需要登录。 */
  username: string;
  /** 密码草稿（D26）：永远是空串或刚敲进去的东西，绝不回显已存的密码。 */
  password: SecretDraft;
  /**
   * 模块访问知识服务用的 Agent API Key（`CO_KNOWLEDGE_API_KEY`）草稿。
   * 与密码同一条 D26：留空不显示原值，三态由 `resolveSecret` 决定。
   */
  apiKey: SecretDraft;
  description: string;
  /**
   * 只在**新建**时有意义（编辑态的生效切换在列表行的「设为可用」上）。
   * 默认不勾：新增的动机常常只是先把地址存下来，替用户激活会悄悄换掉正在用的那条。
   */
  isActive: boolean;
}

/** 能出错的字段名。开关不可能有非法值，因此不在其中。 */
export type RagKnowledgeField =
  | 'name'
  | 'routeUrl'
  | 'username'
  | 'password'
  | 'apiKey'
  | 'description';

export function emptyRagKnowledgeDraft(): RagKnowledgeDraft {
  return {
    name: '',
    routeUrl: '',
    username: '',
    password: EMPTY_SECRET,
    apiKey: EMPTY_SECRET,
    description: '',
    isActive: false,
  };
}

export function draftFromRagKnowledge(record: RagKnowledgeBase): RagKnowledgeDraft {
  return {
    name: record.name,
    routeUrl: record.routeUrl,
    username: record.username ?? '',
    // 密码与 API Key 恒为空串（D26：明文读不到），"已配置"由旁边的提示语表达。
    password: EMPTY_SECRET,
    apiKey: EMPTY_SECRET,
    description: record.description ?? '',
    isActive: record.isActive,
  };
}

/** 地址里是否内嵌了 `user:pass@`。解析不了时返回 `false`——那是 `url` 那一档的事。 */
export function hasUrlCredentials(raw: string): boolean {
  try {
    const url = new URL(raw);
    return url.username !== '' || url.password !== '';
  } catch {
    return false;
  }
}

/**
 * 提交前校验。只登记**出错的**字段，返回空对象表示可以提交。
 *
 * 地址的四条规则与契约同序：空 → 不是 http(s) → 带凭据 → 超长。它们互斥，
 * 用户一次只需要看到一条真正相关的说明。账号密码只判长度：空账号是合法的
 * （不需要登录），密码的"留空 = 保持"由 `resolveSecret` 表达，不是校验问题。
 */
export function validateRagKnowledgeDraft(
  draft: RagKnowledgeDraft,
): Partial<Record<RagKnowledgeField, FieldIssue>> {
  const issues: Partial<Record<RagKnowledgeField, FieldIssue>> = {};

  const name = draft.name.trim();
  if (name === '') {
    issues.name = { kind: 'required' };
  } else if (name.length > RAG_KB_NAME_MAX_LENGTH) {
    issues.name = { kind: 'tooLong', max: RAG_KB_NAME_MAX_LENGTH };
  }

  const routeUrl = draft.routeUrl.trim();
  if (routeUrl === '') {
    issues.routeUrl = { kind: 'required' };
  } else if (!isHttpUrl(routeUrl)) {
    issues.routeUrl = { kind: 'url' };
  } else if (hasUrlCredentials(routeUrl)) {
    issues.routeUrl = { kind: 'credentials' };
  } else if (routeUrl.length > RAG_KB_ROUTE_MAX_LENGTH) {
    issues.routeUrl = { kind: 'tooLong', max: RAG_KB_ROUTE_MAX_LENGTH };
  }

  if (draft.username.trim().length > RAG_KB_USERNAME_MAX_LENGTH) {
    issues.username = { kind: 'tooLong', max: RAG_KB_USERNAME_MAX_LENGTH };
  }

  if (draft.password.value.length > RAG_KB_PASSWORD_MAX_LENGTH) {
    issues.password = { kind: 'tooLong', max: RAG_KB_PASSWORD_MAX_LENGTH };
  }

  if (draft.apiKey.value.length > RAG_KB_API_KEY_MAX_LENGTH) {
    issues.apiKey = { kind: 'tooLong', max: RAG_KB_API_KEY_MAX_LENGTH };
  }

  if (draft.description.trim().length > RAG_KB_DESCRIPTION_MAX_LENGTH) {
    issues.description = { kind: 'tooLong', max: RAG_KB_DESCRIPTION_MAX_LENGTH };
  }

  return issues;
}

/** 空说明写 `null`（契约里 `description` 可空），与服务端的存法一致。 */
function descriptionOf(draft: RagKnowledgeDraft): string | null {
  const text = draft.description.trim();
  return text === '' ? null : text;
}

/** 空账号写 `null`（`username` 可空），不让空串流到读模型里。 */
function usernameOf(draft: RagKnowledgeDraft): string | null {
  const text = draft.username.trim();
  return text === '' ? null : text;
}

/** 新建的请求体。`isActive` 由表单里的勾选框决定。 */
export function ragKnowledgeCreatePayload(draft: RagKnowledgeDraft): CreateRagKnowledgeBaseInput {
  return {
    name: draft.name.trim(),
    routeUrl: draft.routeUrl.trim(),
    username: usernameOf(draft),
    // 留空 = 不设置（`null`），不是空串：服务端对密钥是 `min(1)`，空串会 422。
    password: resolveSecret(draft.password, 'create'),
    apiKey: resolveSecret(draft.apiKey, 'create'),
    description: descriptionOf(draft),
    isActive: draft.isActive,
  };
}

/**
 * 编辑的请求体（`PATCH`）。
 *
 * 文本字段都送：编辑表单显示的就是全部可改内容，用户清空说明就是要清空（`null`）。
 * 密码走 D26 三态：留空时 `resolveSecret` 返回 `undefined`，那个键会从序列化结果里
 * 消失，服务端据此保持原密码。
 *
 * `isActive` **不送**——生效切换是列表行上的独立动作，混进保存里会让"只是改个名字"
 * 顺手把正在用的那一条换掉。
 */
export function ragKnowledgeUpdatePayload(draft: RagKnowledgeDraft): UpdateRagKnowledgeBaseInput {
  const password = resolveSecret(draft.password, 'edit');
  const apiKey = resolveSecret(draft.apiKey, 'edit');
  return {
    name: draft.name.trim(),
    routeUrl: draft.routeUrl.trim(),
    username: usernameOf(draft),
    description: descriptionOf(draft),
    ...(password === undefined ? {} : { password }),
    ...(apiKey === undefined ? {} : { apiKey }),
  };
}
