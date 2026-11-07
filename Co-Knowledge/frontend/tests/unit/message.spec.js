// `@/lib/message`：全仓轻提示（toast）的统一出口 —— 默认注入 `showClose: true`，
// 让直连 ElMessage 的调用点与走 `$message` 封装（main.ts:73-88）的调用点风格一致。
//
// mock 掉整个 `element-plus` 裸导入（照 GraphControls.spec.js 的既有写法）：被测的
// 就是「实参怎么落到 ElMessage」这层收口，换成 spy 后逐项核对实参即可；真 ElMessage
// 会往 document.body 塞浮层，断言它反而绕远。mock 的形状与真实 EP 一致：
// ElMessage 自身可调用，四个便捷方法与 closeAll 挂在它上面。

const { ElMessageMock, baseSpy } = vi.hoisted(() => {
  const base = vi.fn()
  const ElMessage = Object.assign(base, {
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
    closeAll: vi.fn()
  })
  return { ElMessageMock: ElMessage, baseSpy: base }
})
vi.mock('element-plus', () => ({ ElMessage: ElMessageMock }))

import message from '@/shared/lib/message'

const typedSpies = {
  success: ElMessageMock.success,
  warning: ElMessageMock.warning,
  info: ElMessageMock.info,
  error: ElMessageMock.error
}

describe('lib/message：默认注入 showClose 的轻提示出口', () => {
  beforeEach(() => {
    baseSpy.mockClear()
    Object.values(typedSpies).forEach(spy => spy.mockClear())
    ElMessageMock.closeAll.mockClear()
  })

  test('基础调用：传入字符串时包成 { message }，并默认注入 showClose: true', () => {
    message('保存成功')

    expect(baseSpy).toHaveBeenCalledTimes(1)
    expect(baseSpy).toHaveBeenCalledWith({ showClose: true, message: '保存成功' })
  })

  test('基础调用：传入对象时逐字段展开，其余配置原样透传给 ElMessage', () => {
    message({ message: '保存失败', type: 'error', duration: 5000 })

    expect(baseSpy).toHaveBeenCalledWith({
      showClose: true,
      message: '保存失败',
      type: 'error',
      duration: 5000
    })
  })

  test('基础调用：调用方显式传 showClose: false 时以调用方为准', () => {
    message({ message: '静默同步完成', showClose: false })

    expect(baseSpy).toHaveBeenCalledWith({ showClose: false, message: '静默同步完成' })
  })

  test.each(['success', 'warning', 'info', 'error'])(
    '便捷方法 %s：字符串形态注入 showClose: true 与自身 type',
    type => {
      message[type]('提示内容')

      expect(typedSpies[type]).toHaveBeenCalledTimes(1)
      expect(typedSpies[type]).toHaveBeenCalledWith({
        showClose: true,
        message: '提示内容',
        type
      })
    }
  )

  test.each(['success', 'warning', 'info', 'error'])(
    '便捷方法 %s：对象形态同样注入默认值，显式 showClose 可覆盖',
    type => {
      message[type]({ message: '提示内容', duration: 800, showClose: false })

      expect(typedSpies[type]).toHaveBeenCalledWith({
        showClose: false,
        message: '提示内容',
        duration: 800,
        type
      })
    }
  )

  test('closeAll：透传到 ElMessage.closeAll（保持与 ElMessage 同形状）', () => {
    message.closeAll()

    expect(ElMessageMock.closeAll).toHaveBeenCalledTimes(1)
  })
})
