import { test, expect, resourceName } from '../../support/fixtures/test'
import { KbListPage } from '../../support/pages/kb-list.page'
import { deleteConfirmDialog } from '../../support/pages/delete-confirm.page'
import type { ApiClient } from '../../support/api/api-client'

async function embeddingModel (api: ApiClient): Promise<string> {
  const models = await api.listEmbeddingModels()
  if (!models.length) throw new Error('没有可用的 embedding 模型')
  return models[0]
}

async function createKb (
  api: ApiClient,
  caseId: string,
  withFile = false
): Promise<{ name: string; kbId: string; fileName?: string }> {
  const name = resourceName(caseId)
  const model = await embeddingModel(api)
  if (!withFile) {
    const kb = await api.kb.create({
      name,
      description: 'E2E',
      props: { embeddingModel: model }
    })
    return { name, kbId: kb.id }
  }
  const fileName = `${name}.md`
  const seeded = await api.kb.createWithFile({
    name,
    embeddingModel: model,
    fileName,
    content: `# ${name}\n\nE2E 知识库生命周期测试。\n`,
    format: 'md'
  })
  return { name, kbId: seeded.kbId, fileName }
}

async function cleanup (api: ApiClient, kbId?: string): Promise<void> {
  if (kbId) await api.kb.cleanup(kbId)
}

test.describe('文档知识库生命周期', () => {
  test('@p0 KB-01 列表加载与基础控件', async ({ page }) => {
    const kb = new KbListPage(page)
    await kb.goto()
    await expect(kb.root).toBeVisible()
    await expect(kb.searchInput).toBeVisible()
    await expect(kb.pagination).toBeVisible()
  })

  test('@p1 KB-02 按名称搜索与清空', async ({ page, api }) => {
    test.setTimeout(120_000)
    const first = await createKb(api, 'KB-02-A')
    const second = await createKb(api, 'KB-02-B')
    try {
      const kb = new KbListPage(page)
      await kb.goto()
      await kb.search(first.name)
      await kb.expectRow(first.name)
      await expect(kb.rowByName(second.name)).toHaveCount(0)

      await kb.searchInput.fill('')
      await kb.expectRow(first.name)
      await kb.expectRow(second.name)
    } finally {
      await cleanup(api, first.kbId)
      await cleanup(api, second.kbId)
    }
  })

  test('@p0 KB-05 建库后置资源（默认目录/表名/索引名）', async ({ api }) => {
    const seeded = await createKb(api, 'KB-05')
    try {
      const detail = await api.kb.get(seeded.kbId)
      expect(String(detail.tableName || '')).toContain('doc_')
      expect(String(detail.tableName || '')).toContain('_vector')
      // es_index_name 列与运行时 ES 索引名一致：doc_<id>
      expect(String(detail.esIndexName || '')).toContain('doc_')
      expect(String(detail.esIndexName || '')).not.toContain('kb_index_')
      const directoryId = await api.kb.defaultDirectoryId(seeded.kbId)
      expect(directoryId).toBeTruthy()
    } finally {
      await cleanup(api, seeded.kbId)
    }
  })

  test('@p1 KB-06 详情页两个页签与「管理文档」入口', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await createKb(api, 'KB-06', true)
    try {
      const kb = new KbListPage(page)
      await kb.goto()
      await kb.openDetail(seeded.name)
      await expect(page.getByRole('tab', { name: '数据集' })).toBeVisible()
      await expect(page.getByRole('tab', { name: '基本信息' })).toBeVisible()
      await page.getByRole('button', { name: '文档管理' }).click()
      await expect(page).toHaveURL(/#\/knowledge\/detail\/[^/]+\/documents$/)
    } finally {
      await cleanup(api, seeded.kbId)
    }
  })

  // 已知产品缺陷：前端 `updatedKnowledgeBaseInfo` 打 `POST /kbase/{id}`，
  // 后端只注册了 `POST /kbase/{id}`，返回 0005；因此这条从 fixme 转为正式用例。
  test('@p1 KB-07 编辑基本信息', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await createKb(api, 'KB-07')
    try {
      const kb = new KbListPage(page)
      await kb.goto()
      await kb.clickMoreAction(seeded.name, '重命名')
      const dialog = page.locator('.el-dialog').filter({ hasText: '修改' })
      const newName = `${seeded.name}-X`
      await dialog.locator('input').first().fill(newName)
      await dialog.getByRole('button', { name: '确定', exact: true }).click()
      await expect(kb.rowByName(newName)).toBeVisible()
    } finally {
      await cleanup(api, seeded.kbId)
    }
  })

  test('@p0 KB-08 删除空知识库（验证码）', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await createKb(api, 'KB-08')
    const kb = new KbListPage(page)
    await kb.goto()
    await expect(kb.rowByName(seeded.name)).toBeVisible()

    await kb.deleteByName(seeded.name)
    await expect(kb.rowByName(seeded.name)).toHaveCount(0, { timeout: 20_000 })

    await expect.poll(async () => {
      const rows = await api.kb.list()
      return rows.some(row => row.id === seeded.kbId)
    }, { timeout: 15_000 }).toBe(false)
  })

  test('@p1 KB-09 删除非空知识库被拒绝', async ({ page, api, consoleErrors }) => {
    test.setTimeout(120_000)
    const seeded = await createKb(api, 'KB-09', true)
    try {
      const kb = new KbListPage(page)
      await kb.goto()
      await kb.clickMoreAction(seeded.name, '删除')

      // 列表行的 currentFileCount > 0 → 前端直接提示，不弹删除确认框。
      await expect(page.locator('.el-message--warning').first()).toBeVisible({ timeout: 20_000 })
      await expect(kb.rowByName(seeded.name)).toBeVisible()

      const rows = await api.kb.list()
      expect(rows.some(row => row.id === seeded.kbId)).toBe(true)
    } finally {
      await cleanup(api, seeded.kbId)
    }
  })

  test('@p1 KB-10 错误验证码不能提交删除', async ({ page, api }) => {
    const seeded = await createKb(api, 'KB-10')
    try {
      const kb = new KbListPage(page)
      await kb.goto()
      await kb.clickMoreAction(seeded.name, '删除')

      const dialog = deleteConfirmDialog(page)
      const code = (await dialog.locator('.delete-confirm-challenge code').innerText()).trim()
      const wrong = code === '0000' ? '1111' : '0000'
      await dialog.locator('.delete-confirm-code-row input').fill(wrong)
      await expect(dialog.getByRole('button', { name: '删除', exact: true })).toBeDisabled()
      await dialog.getByRole('button', { name: '取消', exact: true }).click()
    } finally {
      await cleanup(api, seeded.kbId)
    }
  })

  test('@p1 KB-11 列表静止后停止自动轮询', async ({ page, api }) => {
    test.setTimeout(120_000)
    const seeded = await createKb(api, 'KB-11', true)
    try {
      let requests = 0
      page.on('request', request => {
        if (request.method() === 'GET' && request.url().includes('/knowledge-bases')) {
          requests += 1
        }
      })
      const kb = new KbListPage(page)
      await kb.goto()
      await expect(kb.rowByName(seeded.name)).toBeVisible()
      await page.waitForTimeout(1_200)
      requests = 0
      await page.waitForTimeout(3_000)
      expect(requests, '无进行中任务时不应持续轮询').toBeLessThanOrEqual(1)
    } finally {
      await cleanup(api, seeded.kbId)
    }
  })

  test('@p2 KB-12 列表排序参数（API）', async ({ api }) => {
    const result = await api.kb.search({
      categories: [1],
      currentPage: 1,
      pageSize: 10,
      keyword: '',
      orderList: [{ key: 'name', ascending: true }]
    })
    expect(result).toBeTruthy()
  })

  // 列表改用原生表格且不再提供表头排序按钮；排序参数仍可通过 API 生效（KB-12）。
  test.fixme('@p2 KB-12-UI 列表排序按钮', async ({ page }) => {
    const kb = new KbListPage(page)
    await kb.goto()
    await page.getByRole('button', { name: '按 名称 排序' }).click()
  })

  test('@p2 KB-13 空态与超长名称', async ({ page, api }) => {
    test.setTimeout(120_000)
    const kb = new KbListPage(page)
    await kb.goto()
    await kb.search(`NOT-EXIST-${Date.now()}`)
    await kb.expectNoRows()

    const model = await embeddingModel(api)
    const longName = `E2E-长名称-${'A'.repeat(18)}`
    const created = await api.kb.create({
      name: longName,
      description: 'long name',
      props: { embeddingModel: model }
    })
    try {
      await kb.searchInput.fill('')
      await kb.search(longName)
      await kb.expectRow(longName)
    } finally {
      await cleanup(api, created.id)
    }
  })

  test('@p2 KB-14 特殊字符名称校验', async ({ api }) => {
    const model = await embeddingModel(api)
    const invalid = `${resourceName('KB-14')}!`
    let invalidError: unknown
    try {
      await api.kb.create({
        name: invalid,
        description: 'invalid',
        props: { embeddingModel: model }
      })
    } catch (error) {
      invalidError = error
    }
    expect(invalidError, '非法名称应被拒绝').toBeTruthy()
    expect(String(invalidError)).toMatch(/validation_failed|422|invalid|不合法|名称/i)

    // KB 名称上限 30；resourceName 本身已接近上限，这里用短名 + 时间片保唯一。
    const valid = `KB14 中文-ok ${Date.now().toString(36).slice(-5)}`
    const created = await api.kb.create({
      name: valid,
      description: 'valid',
      props: { embeddingModel: model }
    })
    try {
      const rows = await api.kb.list()
      expect(rows.some(row => row.id === created.id && row.name === valid)).toBe(true)
    } finally {
      await cleanup(api, created.id)
    }
  })
})
