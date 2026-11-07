import fs from 'node:fs'
import path from 'node:path'
import { test, expect, resourceName } from '../../support/fixtures/test'
import { createZip } from '../../support/fixtures/files'
import { confirmDeletion } from '../../support/pages/delete-confirm.page'
import type { ApiClient } from '../../support/api/api-client'
import type { OperatorRow } from '../../support/api/operator-api'

const SAMPLE_ZIP = path.resolve(__dirname, '../../fixtures/operators/sample_operator.zip')
const SAMPLE_NAME = '定长切分算子'
const SAMPLE_NAME_EN = 'sample_fixed_length_splitter'

async function findOperator (api: ApiClient, name: string): Promise<OperatorRow | undefined> {
  return (await api.operator.findAll()).find(row => row.name === name || row.nameEn === name)
}

async function cleanupOperator (api: ApiClient, operator?: OperatorRow): Promise<void> {
  if (operator) {
    try { await api.operator.delete(operator.id) } catch { /* best effort */ }
  }
}

/**
 * 样例算子的英文名是固定值，导入接口按名称判重。
 * 上一轮失败/中断留下的同名算子会让本轮导入 409，先清掉再导入（幂等夹具）。
 */
async function removeExistingSample (api: ApiClient): Promise<void> {
  await cleanupOperator(api, await findOperator(api, SAMPLE_NAME_EN))
}

async function importSample (api: ApiClient): Promise<OperatorRow> {
  await removeExistingSample(api)
  await api.operator.import({
    name: 'sample_operator.zip',
    mimeType: 'application/zip',
    buffer: fs.readFileSync(SAMPLE_ZIP)
  })
  let found: OperatorRow | undefined
  await expect.poll(async () => {
    found = await findOperator(api, SAMPLE_NAME_EN)
    return Boolean(found)
  }, { timeout: 20_000 }).toBe(true)
  return found!
}

async function embeddingModel (api: ApiClient): Promise<string> {
  const models = await api.listEmbeddingModels()
  if (!models.length) throw new Error('没有可用的 embedding 模型')
  return models[0]
}

async function importCustomZip (api: ApiClient, displayNameEn: string, code: string): Promise<void> {
  const zip = await createZip({
    'config.json': JSON.stringify({
      display_name: { zh: displayNameEn, en: displayNameEn },
      desc: { zh: 'E2E 自定义算子', en: 'E2E custom operator' },
      module: 'text_split',
      version: '1.0.0',
      supportedFormat: ['md', 'txt'],
      is_published: 1,
      visibleRange: 'private',
      defaultArgs: []
    }, null, 2),
    'custom_split.py': code
  })
  await api.operator.import({
    name: `${displayNameEn}.zip`,
    mimeType: 'application/zip',
    buffer: zip
  })
}

test.describe('自定义算子', () => {
  test('@p0 OP-01 算子列表与页签', async ({ page }) => {
    await page.goto('/#/operators')
    await expect(page.locator('.operators-page')).toBeVisible()
    await expect(page.getByRole('tab', { name: '我的算子' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '公开算子' })).toBeVisible()
    await expect(page.locator('.operators-page .operator-table').first()).toBeVisible()
  })

  test('@p0 OP-02 通过 UI 导入有效算子包', async ({ page, api }) => {
    test.setTimeout(120_000)
    let operator: OperatorRow | undefined
    try {
      await removeExistingSample(api)
      await page.goto('/#/operators')
      await page.getByRole('button', { name: '导入算子文件' }).click()
      const dialog = page.locator('.el-dialog').filter({ hasText: '导入算子文件' })
      await dialog.locator('input[type=file]').first().setInputFiles(SAMPLE_ZIP)
      await dialog.getByRole('button', { name: '确定', exact: true }).click()
      await expect(page.getByText(SAMPLE_NAME).first()).toBeVisible({ timeout: 20_000 })

      operator = await findOperator(api, SAMPLE_NAME_EN)
      expect(operator).toBeTruthy()
    } finally {
      if (!operator) operator = await findOperator(api, SAMPLE_NAME_EN)
      await cleanupOperator(api, operator)
    }
  })

  test('@p0 OP-03 危险算子被 code-check 拒绝', async ({ api }) => {
    const dangerous = await createZip({
      'config.json': JSON.stringify({
        display_name: { zh: 'E2E危险算子', en: 'e2e_dangerous_splitter' },
        desc: { zh: '危险', en: 'dangerous' },
        module: 'text_split',
        version: '1.0.0',
        supportedFormat: ['md', 'txt'],
        is_published: 1,
        visibleRange: 'private',
        defaultArgs: []
      }),
      'dangerous_split.py': "import os\n\ndef file_split(file_path: str, **args):\n    os.system('echo bad')\n    return []\n"
    })
    let error: unknown
    try {
      await api.operator.import({
        name: 'dangerous.zip',
        mimeType: 'application/zip',
        buffer: dangerous
      })
    } catch (caught) {
      error = caught
    }
    expect(error, '危险算子应被拒绝').toBeTruthy()
    expect(String(error)).toMatch(/unsupported_operator|validation_failed|422|拒绝|不合法/i)
    expect(await findOperator(api, 'e2e_dangerous_splitter')).toBeUndefined()
  })

  test('@p1 OP-04 畸形 zip 返回友好错误', async ({ api }) => {
    let error: unknown
    try {
      await api.operator.import({
        name: 'broken.zip',
        mimeType: 'application/zip',
        buffer: Buffer.from('not a zip')
      })
    } catch (caught) {
      error = caught
    }
    expect(error).toBeTruthy()
  })

  test('@p1 OP-05 导出算子包', async ({ api }) => {
    const operator = await importSample(api)
    try {
      const exported = await api.operator.exportStatus(operator.id)
      expect(exported.status).toBe(200)
      expect(exported.contentType).toMatch(/octet-stream|zip|application/i)
    } finally {
      await cleanupOperator(api, operator)
    }
  })

  test('@p1 OP-06 发布/公开状态切换', async ({ api }) => {
    const operator = await importSample(api)
    try {
      await api.operator.unpublish(operator.id)
      await expect.poll(async () => {
        const row = await findOperator(api, SAMPLE_NAME_EN)
        return Boolean(row?.isPublished)
      }, { timeout: 10_000 }).toBe(false)

      await api.operator.publish(operator.id)
      await expect.poll(async () => {
        const row = await findOperator(api, SAMPLE_NAME_EN)
        return Boolean(row?.isPublished)
      }, { timeout: 10_000 }).toBe(true)

      await api.operator.makePrivate(operator.id)
      await expect.poll(async () => {
        const row = await findOperator(api, SAMPLE_NAME_EN)
        return row?.visibleRange
      }, { timeout: 10_000 }).toBe('private')

      await api.operator.makePublic(operator.id)
      await expect.poll(async () => {
        const row = await findOperator(api, SAMPLE_NAME_EN)
        return row?.visibleRange
      }, { timeout: 10_000 }).toBe('public')
    } finally {
      await cleanupOperator(api, operator)
    }
  })

  test('@p1 OP-07 删除算子（UI 验证码）', async ({ page, api }) => {
    test.setTimeout(120_000)
    const operator = await importSample(api)
    try {
      await page.goto('/#/operators')
      // 「我的 / 公开」两个 tabpanel 同时留在 DOM 里；只取可见的那张表。
      const row = page.locator('.operators-page .operator-table tbody tr:visible')
        .filter({ hasText: SAMPLE_NAME })
      await expect(row).toBeVisible()
      // 删除在行尾「更多操作」下拉里，不是行内按钮。
      await row.getByRole('button', { name: /操作$/ }).click()
      await page.getByRole('menuitem', { name: '删除', exact: true }).click()
      await confirmDeletion(page)
      await expect(row).toHaveCount(0, { timeout: 20_000 })
      expect(await findOperator(api, SAMPLE_NAME_EN)).toBeUndefined()
    } finally {
      await cleanupOperator(api, await findOperator(api, SAMPLE_NAME_EN))
    }
  })

  test('@p1 OP-08 自定义算子用于导入（切片/检索）', async ({ api }) => {
    test.setTimeout(180_000)
    const operator = await importSample(api)
    const name = resourceName('OP-08')
    const kb = await api.kb.create({
      name,
      description: 'operator use',
      props: { embeddingModel: await embeddingModel(api) }
    })
    const dirId = await api.kb.defaultDirectoryId(kb.id)
    try {
      const fileName = `${name}.md`
      const marker = `E2E-OP-MARKER-${Date.now()}`
      const fileId = await api.kb.uploadWithCustomOperator(
        kb.id,
        dirId,
        {
          name: fileName,
          mimeType: 'text/markdown',
          buffer: Buffer.from(`# ${name}\n\n${marker}\n\n` + '内容。'.repeat(50))
        },
        'md',
        Number(operator.id),
        [{ argName: 'max_len', argType: 'int', defaultValue: 60 }]
      )
      await api.kb.waitForFile(kb.id, fileName, 180_000)
      expect((await api.kb.chunks(kb.id, undefined, 100)).total || 0).toBeGreaterThan(0)
      await expect.poll(async () => {
        const groups = await api.retrieve({ question: marker, kbId: kb.id, type: 0 })
        return groups.flatMap(group => group.docs || []).length
      }, { timeout: 15_000 }).toBeGreaterThan(0)
      void fileId
    } finally {
      await api.kb.cleanup(kb.id)
      await cleanupOperator(api, operator)
    }
  })

  test('@p2 OP-09 算子执行异常时任务给出失败原因', async ({ api }) => {
    test.setTimeout(180_000)
    const failingName = `e2e_failing_${Date.now()}`
    await importCustomZip(
      api,
      failingName,
      "def file_split(file_path: str, **args):\n    raise RuntimeError('E2E operator boom')\n"
    )
    const operator = await findOperator(api, failingName)
    expect(operator).toBeTruthy()
    const name = resourceName('OP-09')
    const kb = await api.kb.create({
      name,
      description: 'failing operator',
      props: { embeddingModel: await embeddingModel(api) }
    })
    const dirId = await api.kb.defaultDirectoryId(kb.id)
    try {
      const fileName = `${name}.md`
      await api.kb.uploadWithCustomOperator(
        kb.id,
        dirId,
        {
          name: fileName,
          mimeType: 'text/markdown',
          buffer: Buffer.from('# boom\n\n' + '内容。'.repeat(40))
        },
        'md',
        Number(operator!.id),
        [{ argName: 'max_len', argType: 'int', defaultValue: 60 }]
      )
      let failed = false
      try {
        await api.kb.waitForFile(kb.id, fileName, 180_000)
      } catch (error) {
        failed = true
        expect(String(error)).toMatch(/失败|fail|boom/i)
      }
      expect(failed, '抛异常的算子应让文件任务失败').toBe(true)
    } finally {
      await api.kb.cleanup(kb.id)
      await cleanupOperator(api, operator)
    }
  })

  test('@p2 OP-10 非法英文显示名被拒绝', async ({ api }) => {
    let error: unknown
    try {
      await importCustomZip(
        api,
        `bad-name-${Date.now()}`,
        "def file_split(file_path: str, **args):\n    return []\n"
      )
    } catch (caught) {
      error = caught
    }
    expect(error, '带连字符的英文显示名应被拒绝').toBeTruthy()
  })
})
