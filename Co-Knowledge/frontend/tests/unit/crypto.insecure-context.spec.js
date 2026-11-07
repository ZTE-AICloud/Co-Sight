// `@/lib/crypto`：请求签名（HMAC-SHA256）的唯一实现。
//
// 背景：WebCrypto 的 `crypto.subtle` **只在安全上下文存在**（HTTPS / localhost）。产品以
// `http://<host>` 部署时它是 `undefined`，在 `importKey` 处抛 TypeError，把
// 「上传前取签名配置」这一步整个带崩 —— 于是建库成功、文件一个没传，而向导把异常
// 吞了，用户看不到任何提示。因此**非安全上下文降级为不带签名**（后端全仓不校验
// 该签名；需要签名的网关部署天然是 HTTPS，签名照常）。
//
// 这组用例钉两件事，缺一不可：
//   ① 阳性对照：安全上下文下签名**必须**还是真的 HMAC-SHA256（否则「降级」变成「永远不签」）；
//   ② 阴性：非安全上下文下不抛错、返回空签名。

import { createHmac } from 'node:crypto'

const realCrypto = globalThis.crypto

// `lib/crypto.js` 经 `lib/message` 触达 `element-plus` 的 ElMessage，而本 spec 跑在
// node 环境（见 vitest.config.mjs：需要 DOM 的 spec 才按文件 opt-in jsdom）。
// 照 message.spec.js 的写法把 ElMessage 换成 spy —— 被测的是签名，不是提示。
vi.mock('element-plus', () => {
  const base = vi.fn()
  return {
    ElMessage: Object.assign(base, {
      success: vi.fn(), warning: vi.fn(), info: vi.fn(), error: vi.fn(), closeAll: vi.fn()
    })
  }
})

import Crypto from '@/shared/lib/crypto'

// 把 `crypto` 换成**没有 subtle** 的形状（浏览器在非安全上下文里就是这个形状：
// 只有 getRandomValues）。注意必须连 `subtle` 键都不存在，而不是置 undefined ——
// 实现用的是 `!!crypto.subtle`。
function withInsecureCrypto (fn) {
  vi.stubGlobal('crypto', { getRandomValues: realCrypto.getRandomValues.bind(realCrypto) })
  try {
    return fn()
  } finally {
    vi.stubGlobal('crypto', realCrypto)
  }
}

describe('Crypto.AES.encrypt', () => {
  it('安全上下文：产出真正的 HMAC-SHA256 十六进制串（与 node:crypto 对齐）', async () => {
    const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    // 固定时间才能与 node:crypto 比对 —— 签名内容里含 `YYYYMMDDHHmm`
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-16T17:30:00+08:00'))
    try {
      const sig = await Crypto.AES.encrypt('my-kb-id:202610161730', 'secret-key')

      const expected = createHmac('sha256', 'secret-key')
        .update('my-kb-id:202610161730')
        .digest('hex')

      expect(sig).toBe(expected)
      expect(sig).toMatch(/^[0-9a-f]{64}$/)
    } finally {
      vi.useRealTimers()
      spy.mockRestore()
    }
  })

  it('非安全上下文：不抛错，返回空签名（并只告警一次）', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const sig = await withInsecureCrypto(() => Crypto.AES.encrypt('x:202610161730', 'k'))
      expect(sig).toBe('')
      expect(warn).toHaveBeenCalled()
      // 降级只提示一次，别把控制台刷满（上传链路每次都会走到这里）
      await withInsecureCrypto(() => Crypto.AES.encrypt('y:202610161730', 'k'))
      expect(warn).toHaveBeenCalledTimes(1)
    } finally {
      warn.mockRestore()
    }
  })
})

describe('Crypto.AES.doSignature', () => {
  it('非安全上下文：仍返回时间戳，Signature 为空串（调用方拿到的 headers 形状不变）', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const out = await withInsecureCrypto(() => Crypto.AES.doSignature('kb-id', 'secret'))
      expect(Object.keys(out).sort()).toEqual(['Signature', 'Timestamp'])
      expect(out.Signature).toBe('')
      expect(typeof out.Timestamp).toBe('number')
    } finally {
      warn.mockRestore()
    }
  })

  it('入参缺失：仍然提示，且非安全上下文下不再因加密抛错', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const out = await withInsecureCrypto(() => Crypto.AES.doSignature('', ''))
      expect(out.Signature).toBe('')
    } finally {
      warn.mockRestore()
    }
  })
})
