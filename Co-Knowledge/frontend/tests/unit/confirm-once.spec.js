import { describe, it, expect, beforeEach } from 'vitest'
import { onceConfirm, __resetConfirmOnce } from '@/shared/lib/confirm-once'

describe('onceConfirm', () => {
  beforeEach(() => __resetConfirmOnce())

  it('确认返回 true，取消返回 false（不抛错）', async () => {
    expect(await onceConfirm(() => Promise.resolve())).toBe(true)
    expect(await onceConfirm(() => Promise.reject(new Error('cancel')))).toBe(false)
  })

  it('已有确认框在开时，后来的调用直接返回 false 且不再打开新框', async () => {
    let opened = 0
    let release
    const slow = onceConfirm(() => {
      opened += 1
      return new Promise(resolve => { release = resolve })
    })
    // 第二个/第三个调用必须被闸门挡住（这就是「连点叠 2~3 层」的成因）
    expect(await onceConfirm(() => { opened += 1; return Promise.resolve() })).toBe(false)
    expect(await onceConfirm(() => { opened += 1; return Promise.resolve() })).toBe(false)
    expect(opened).toBe(1)

    release()
    expect(await slow).toBe(true)
  })

  it('前一个结束后闸门放开，可以再开', async () => {
    await onceConfirm(() => Promise.resolve())
    let opened = false
    await onceConfirm(() => { opened = true; return Promise.resolve() })
    expect(opened).toBe(true)
  })

  it('open() 同步抛错也当作取消，且闸门要复位', async () => {
    expect(await onceConfirm(() => { throw new Error('boom') })).toBe(false)
    let opened = false
    await onceConfirm(() => { opened = true; return Promise.resolve() })
    expect(opened).toBe(true)
  })
})
