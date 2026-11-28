// @vitest-environment jsdom
/**
 * 版本更新：发布记录数据、已读判重与页面渲染。
 *
 * 这里钉三类容易「静默坏」的行为：
 *   ① 记录顺序与中英对齐：清单第一条就是当前版本，缺译文不能渲染成空白；
 *   ② 已读标记按「账号 + 版本」隔离，且 localStorage 里不出现账号明文；
 *   ③ http 部署（无 `crypto.subtle`）时已读状态仍能持久化。
 */
import { webcrypto, createHash } from 'node:crypto'
import { vi } from 'vitest'

import { flush, mountWithPlugins, expectNoI18nMisses } from './helpers/mount'
import { currentRelease, releases, releaseText } from '@/shared/constants/releases'
import {
  acknowledgeReleaseNotice,
  getUnreadReleaseNotice,
  releaseNotice,
  resetReleaseNoticeState
} from '@/shared/composables/releaseNotice'
import ReleasePage from '@/pages/release/ReleasePage.vue'

const STORAGE_PREFIX = 'ragstudio-release-read'

const versionTuple = version => version.split('.').map(Number)

describe('发布记录数据', () => {
  it('版本号唯一且按版本倒序排列（第一条 = 当前版本）', () => {
    // Arrange
    const versions = releases.map(release => release.version)

    // Act
    const unique = new Set(versions)

    // Assert
    expect(unique.size).toBe(versions.length)
    expect(currentRelease).toBe(releases[0])
    for (let i = 1; i < versions.length; i += 1) {
      const [previousMajor, previousMinor, previousPatch] = versionTuple(versions[i - 1])
      const [major, minor, patch] = versionTuple(versions[i])
      const descending = previousMajor !== major
        ? previousMajor > major
        : previousMinor !== minor
          ? previousMinor > minor
          : previousPatch > patch
      expect(descending, `${versions[i - 1]} 应排在 ${versions[i]} 之前`).toBe(true)
    }
  })

  it('每条记录的中英标题、功能与修复条目一一对齐', () => {
    // Arrange
    const problems = []

    // Act
    for (const release of releases) {
      if (!release.title?.zh?.trim() || !release.title?.en?.trim()) {
        problems.push(`${release.version}: 标题缺少中文或英文`)
      }
      for (const field of ['features', 'fixes']) {
        const zh = release[field]?.zh || []
        const en = release[field]?.en || []
        if (zh.length !== en.length) {
          problems.push(`${release.version}.${field}: zh ${zh.length} 条 / en ${en.length} 条`)
        }
      }
    }

    // Assert
    expect(problems).toEqual([])
  })

  it('releaseText 按语言取文案，未知语言回落到中文', () => {
    // Arrange
    const release = releases.find(item => item.version === '0.1.9')

    // Act & Assert
    expect(releaseText(release, 'zh').title).toBe('图谱实体创建')
    expect(releaseText(release, 'en').title).toBe('Create graph entities')
    expect(releaseText(release, 'fr').title).toBe('图谱实体创建')
  })

  it('releaseText 在缺失译文时回落到中文，不返回空标题', () => {
    // Arrange
    const partial = { version: '9.9.9', title: { zh: '只有中文' }, features: { zh: ['条目'] } }

    // Act
    const text = releaseText(partial, 'en')

    // Assert
    expect(text.title).toBe('只有中文')
    expect(text.features).toEqual(['条目'])
    expect(text.fixes).toEqual([])
  })
})

describe('版本更新提醒（已读判重）', () => {
  beforeEach(() => {
    localStorage.clear()
    resetReleaseNoticeState()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('首次进入：返回未读提醒，存储键是账号摘要而不是明文', async () => {
    // Arrange：安全上下文（HTTPS / localhost）才有 crypto.subtle
    vi.stubGlobal('crypto', webcrypto)
    const expectedDigest = createHash('sha256').update('admin').digest('hex')

    // Act
    const notice = await getUnreadReleaseNotice('admin')

    // Assert
    expect(notice).not.toBeNull()
    expect(notice.storageKey).toBe(`${STORAGE_PREFIX}:${currentRelease.version}:${expectedDigest}`)
    expect(notice.storageKey).not.toContain('admin')
    expect(localStorage.getItem(notice.storageKey)).toBeNull()
  })

  it('确认后同一账号同一版本不再提醒（含页面重载后的持久化）', async () => {
    // Arrange
    vi.stubGlobal('crypto', webcrypto)
    const notice = await getUnreadReleaseNotice('admin')
    releaseNotice.value = notice

    // Act
    acknowledgeReleaseNotice()

    // Assert：弹窗关闭 + 标记落盘；清掉内存状态（模拟重载）后仍判为已读
    expect(releaseNotice.value).toBeNull()
    expect(localStorage.getItem(notice.storageKey)).toBe('1')
    resetReleaseNoticeState()
    expect(await getUnreadReleaseNotice('admin')).toBeNull()
  })

  it('换一个账号仍然提醒（已读按账号隔离）', async () => {
    // Arrange
    vi.stubGlobal('crypto', webcrypto)
    releaseNotice.value = await getUnreadReleaseNotice('admin')
    acknowledgeReleaseNotice()

    // Act
    const other = await getUnreadReleaseNotice('operator')

    // Assert
    expect(other).not.toBeNull()
  })

  it('http 部署（没有 crypto.subtle）时已读状态同样能持久化', async () => {
    // Arrange：非安全上下文的形状 —— 只有 getRandomValues，没有 subtle
    vi.stubGlobal('crypto', { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) })
    const notice = await getUnreadReleaseNotice('admin')

    // Assert：退回确定性散列（8 位十六进制），依旧不写明文账号
    expect(notice.storageKey).toMatch(
      new RegExp(`^${STORAGE_PREFIX}:${currentRelease.version.replace(/\./g, '\\.')}:[0-9a-f]{8}$`)
    )
    expect(notice.storageKey).not.toContain('admin')

    // Act：确认后模拟重载
    releaseNotice.value = notice
    acknowledgeReleaseNotice()
    resetReleaseNoticeState()

    // Assert
    expect(await getUnreadReleaseNotice('admin')).toBeNull()
  })

  it('无账号（none/gateway 模式）不产生提醒', async () => {
    // Act & Assert
    expect(await getUnreadReleaseNotice('')).toBeNull()
    expect(await getUnreadReleaseNotice(null)).toBeNull()
  })

  it('存储不可用时退化为内存判重：本次页面内不重复提醒', async () => {
    // Arrange
    vi.stubGlobal('crypto', webcrypto)
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage denied')
    })
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage denied')
    })

    try {
      // Act
      const notice = await getUnreadReleaseNotice('admin')
      expect(notice).not.toBeNull()
      releaseNotice.value = notice
      acknowledgeReleaseNotice()

      // Assert：没有落盘，但内存里已确认
      expect(notice.storageKey).toBeNull()
      expect(await getUnreadReleaseNotice('admin')).toBeNull()
    } finally {
      getItem.mockRestore()
      setItem.mockRestore()
    }
  })

  it('没有待确认提醒时 acknowledge 是空操作（不抛错、不清别的状态）', () => {
    // Act & Assert
    expect(() => acknowledgeReleaseNotice()).not.toThrow()
    expect(releaseNotice.value).toBeNull()
  })
})

describe('版本更新页', () => {
  it('渲染全部记录，当前版本带标记、构建时间与真实文案', async () => {
    // Act
    const wrapper = await mountWithPlugins(ReleasePage, { route: '/release' })
    await flush()

    // Assert
    const items = wrapper.findAll('.release-timeline > li')
    expect(items).toHaveLength(releases.length)

    const current = wrapper.find('.release-timeline > li.is-current')
    expect(current.find('.release-version').text()).toBe(`v${currentRelease.version}`)
    expect(current.find('.el-tag').exists()).toBe(true)
    expect(current.find('.release-entry-title').text()).toContain('开源发布')
    expect(current.find('.entity-sub').text()).toContain('(UTC+8)')
    expect(wrapper.text()).toContain('新增功能')
    expect(wrapper.text()).toContain('修复与改进')
    expectNoI18nMisses(wrapper)
  })

  it('英文界面渲染英文标题与分组名', async () => {
    // Act
    const wrapper = await mountWithPlugins(ReleasePage, { route: '/release', locale: 'en' })
    await flush()

    // Assert
    expect(wrapper.find('.release-timeline > li.is-current .release-entry-title').text()).toContain('Open-source release')
    expect(wrapper.text()).toContain('New features')
    expect(wrapper.text()).toContain('Fixes & improvements')
    expectNoI18nMisses(wrapper)
  })
})
