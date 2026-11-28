import { shallowRef } from 'vue'

import { currentRelease } from '@/shared/constants/releases'

/**
 * 版本更新提醒的**唯一状态**。
 *
 * 触发点在 `AppShell` 挂载时：有本地账号会话就读一次「该账号当前版本是否已确认」，
 * 未确认则把提示挂到 `releaseNotice`，由 `ReleaseNotice` 弹窗消费。
 * 无认证 / 网关模式下没有本地账号（`/auth/status` 的 `user` 为 null），不弹提示，
 * 用户仍可从左栏「版本更新」查看历史。
 */
export const releaseNotice = shallowRef(null)

/** 存储不可用（或本次页面还没拿到存储键）时的兜底判重，只活到本次页面重载。 */
const acknowledgedInMemory = new Set()

const STORAGE_PREFIX = 'ragstudio-release-read'

const HEX_RADIX = 16
const HEX_BYTE_WIDTH = 2
const FNV_OFFSET_BASIS = 0x811c9dc5
const FNV_PRIME = 0x01000193
const FNV_HEX_WIDTH = 8

function toHex (bytes) {
  return Array.from(bytes, byte => byte.toString(HEX_RADIX).padStart(HEX_BYTE_WIDTH, '0')).join('')
}

/**
 * 账号摘要：已读标记按「账号 + 版本」索引，但**不把账号明文写进 localStorage**。
 *
 * `crypto.subtle` 只在安全上下文（HTTPS / localhost）存在；产品以
 * `http://<host>` 部署时它是 undefined。这里退回到 FNV-1a 这类确定性散列，
 * 让「同一账号同一版本只提示一次」在 http 部署下也能持久化（仅用于去重，
 * 不是安全边界）。
 */
async function accountDigest (account) {
  const bytes = new TextEncoder().encode(account)
  if (typeof window !== 'undefined' && window.crypto?.subtle) {
    const digest = await window.crypto.subtle.digest('SHA-256', bytes)
    return toHex(new Uint8Array(digest))
  }
  let hash = FNV_OFFSET_BASIS
  for (const byte of bytes) {
    hash ^= byte
    hash = Math.imul(hash, FNV_PRIME) >>> 0
  }
  return hash.toString(HEX_RADIX).padStart(FNV_HEX_WIDTH, '0')
}

/**
 * 返回待确认的更新提醒；没有未读版本时返回 null。
 *
 * @param {string} account 当前登录账号（`authState.user.username`）
 */
export async function getUnreadReleaseNotice (account) {
  if (!currentRelease || !account) {
    return null
  }

  const sessionKey = JSON.stringify([account, currentRelease.version])
  let storageKey = null
  try {
    storageKey = `${STORAGE_PREFIX}:${currentRelease.version}:${await accountDigest(account)}`
    if (localStorage.getItem(storageKey) === '1') {
      return null
    }
  } catch {
    // 存储不可用（隐私模式 / 配额）时仅靠内存判重，提示照常可用。
    storageKey = null
  }

  return acknowledgedInMemory.has(sessionKey) ? null : { sessionKey, storageKey }
}

/** 确认（关闭 / 「我知道了」/ 「查看版本历史」）当前提醒，并持久化已读。 */
export function acknowledgeReleaseNotice () {
  const notice = releaseNotice.value
  if (!notice) {
    return
  }

  acknowledgedInMemory.add(notice.sessionKey)
  releaseNotice.value = null
  if (notice.storageKey) {
    try {
      localStorage.setItem(notice.storageKey, '1')
    } catch {
      // 持久化失败不影响本次会话的已读状态。
    }
  }
}

/** 测试用：清空模块内状态（不动浏览器存储）。 */
export function resetReleaseNoticeState () {
  releaseNotice.value = null
  acknowledgedInMemory.clear()
}
