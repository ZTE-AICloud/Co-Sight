import { test, expect, resourceName } from '../../support/fixtures/test'
import { env } from '../../support/env'
import { createZip } from '../../support/fixtures/files'
import type { ApiClient } from '../../support/api/api-client'

const XSS_IMG = '<img src=x onerror="window.__xss=1">'
const XSS_SCRIPT = '<script>window.__xss=2</script>'

async function findOperator (api: ApiClient, nameEn: string): Promise<unknown> {
  const rows = await api.operator.findAll()
  return rows.find(row => row.nameEn === nameEn)
}

test.describe('安全', () => {
  test('@p0 SEC-01 知识库名称 XSS 被拒绝', async ({ api }) => {
    test.setTimeout(180_000)
    // 名称走白名单校验，HTML 必须被拒绝
    const xssName = `${resourceName('SEC-01-X')}<img src=x onerror="window.__xss=1">`
    await expect(api.createKb(xssName, (await api.listEmbeddingModels())[0]))
      .rejects.toThrow(/validation_failed|422|between 2 and 30|only supports|名称/i)
  })

  test('@p0 SEC-02 文件名/切片正文 XSS 安全渲染', async ({ page, api }) => {
    test.setTimeout(180_000)
    const name = resourceName('SEC-02')
    const fileName = `${XSS_IMG}.md`
    const kb = await api.createKb(name, (await api.listEmbeddingModels())[0])
    try {
      const directoryId = await api.defaultDirectoryId(kb.id)
      const content = [
        `# ${XSS_SCRIPT}`,
        '',
        `${XSS_IMG}`,
        '',
        '唯一标记：E2E-SEC-02。'
      ].join('\n')
      await api.uploadMarkdown(kb.id, directoryId, fileName, content)

      const dialogs: string[] = []
      const external: string[] = []
      page.on('dialog', async dialog => {
        dialogs.push(dialog.message())
        await dialog.dismiss()
      })
      page.on('request', request => {
        if (request.url().includes('evil.invalid')) external.push(request.url())
      })

      await page.goto(`${env.baseURL}/#/knowledge/detail/${kb.id}/documents`)
      await expect(page.getByText(fileName).first()).toBeVisible({ timeout: 60_000 })

      expect(await page.locator('img[src="x"]').count()).toBe(0)
      expect(await page.locator('script:has-text("window.__xss")').count()).toBe(0)
      expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss))
        .toBeUndefined()
      expect(dialogs).toEqual([])
      expect(external).toEqual([])
    } finally {
      await api.cleanupKb(kb.id)
    }
  })

  test('@p0 SEC-03 危险算子被 code-check 拒绝', async ({ api }) => {
    test.setTimeout(180_000)
    const snippets: Array<[string, string]> = [
      ['e2e_sec03_os', "import os\n\ndef file_split(file_path: str, **args):\n    os.system('id')\n    return []\n"],
      ['e2e_sec03_subprocess', "import subprocess\n\ndef file_split(file_path: str, **args):\n    subprocess.run(['id'])\n    return []\n"]
    ]
    for (const [nameEn, code] of snippets) {
      const zip = await createZip({
        'config.json': JSON.stringify({
          display_name: { zh: `E2E安全算子_${nameEn}`, en: nameEn },
          desc: { zh: 'SEC-03', en: 'SEC-03' },
          module: 'text_split',
          version: '1.0.0',
          supportedFormat: ['md'],
          is_published: 1,
          visibleRange: 'private',
          defaultArgs: []
        }),
        'split.py': code
      })
      let error: unknown
      try {
        await api.operator.import({
          name: `${nameEn}.zip`,
          mimeType: 'application/zip',
          buffer: zip
        })
      } catch (caught) {
        error = caught
      }
      expect(error, `${nameEn} 应被拒绝`).toBeTruthy()
      expect(await findOperator(api, nameEn)).toBeUndefined()
    }
  })

  test('@p0 SEC-03b 网络调用算子被 code-check 拒绝', async ({ api }) => {
    test.setTimeout(180_000)
    const nameEn = 'e2e_sec03_network'
    const zip = await createZip({
      'config.json': JSON.stringify({
        display_name: { zh: `E2E安全算子_${nameEn}`, en: nameEn },
        desc: { zh: 'SEC-03', en: 'SEC-03' },
        module: 'text_split',
        version: '1.0.0',
        supportedFormat: ['md'],
        is_published: 1,
        visibleRange: 'private',
        defaultArgs: []
      }),
      'split.py': "import urllib.request\n\ndef file_split(file_path: str, **args):\n    urllib.request.urlopen('http://evil.invalid/')\n    return []\n"
    })
    let error: unknown
    try {
      await api.operator.import({
        name: 'sec03-network.zip',
        mimeType: 'application/zip',
        buffer: zip
      })
    } catch (caught) {
      error = caught
    }
    const leaked = await findOperator(api, nameEn) as { id?: string | number } | undefined
    if (leaked?.id) {
      try { await api.operator.delete(leaked.id) } catch { /* best effort */ }
    }
    expect(error, '网络调用算子应被拒绝').toBeTruthy()
    expect(leaked).toBeUndefined()
  })

  test('@p1 SEC-04 路径穿越文件名不落盘', async ({ api }) => {
    test.setTimeout(180_000)
    const kb = await api.createKb(resourceName('SEC-04'), (await api.listEmbeddingModels())[0])
    try {
      const directoryId = await api.defaultDirectoryId(kb.id)
      let uploadError: unknown
      try {
        await api.uploadMarkdown(
          kb.id, directoryId, '../../etc/passwd.md', '# E2E path traversal\n'
        )
      } catch (caught) {
        uploadError = caught
      }
      const files = await api.listAllFiles(kb.id)
      const titles = files.map(file => String(file.title || file.name || ''))
      expect(titles.some(title => title.includes('..') || title.includes('/'))).toBe(false)
      if (uploadError) {
        expect(String(uploadError)).not.toMatch(/Traceback|FileNotFound|\/app\//)
      }
    } finally {
      await api.cleanupKb(kb.id)
    }
  })

  test('@p1 SEC-05 gateway 鉴权模式', async ({ request }) => {
    test.skip(process.env.E2E_AUTH !== '1', '设置 E2E_AUTH=1 且栈以 AUTH_MODE=gateway 启动时运行')
    test.setTimeout(120_000)
    const base = `${env.baseURL}/api/co-knowledge/v1/knowledge-bases`

    const anonymous = await request.get(base)
    expect([401, 403]).toContain(anonymous.status())

    const token = process.env.E2E_AUTH_TOKEN || ''
    expect(token, '缺少 E2E_AUTH_TOKEN').toBeTruthy()
    const authorized = await request.get(base, {
      headers: { 'X-Auth-Value': token }
    })
    expect(authorized.ok()).toBe(true)
    const body = await authorized.json()
    expect(Array.isArray(body.items)).toBe(true)
  })

  test('@p1 SEC-06 错误响应不泄漏内部信息', async ({ api }) => {
    test.setTimeout(180_000)
    const bodies: string[] = []

    const missing = await api.fetchRaw('/definitely-not-exist')
    bodies.push(await missing.text())

    const malformed = await api.fetchRaw('/knowledge-bases?type=graph', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      data: '{not-json'
    })
    bodies.push(await malformed.text())

    const operator = await api.fetchRaw('/operators/999999/export')
    bodies.push(await operator.text())

    const combined = bodies.join('\n')
    expect(combined).not.toMatch(/Traceback \(most recent call last\)/)
    expect(combined).not.toMatch(/psycopg|sqlalchemy|SELECT .* FROM/i)
    expect(combined).not.toMatch(/\/app\/src|\/site-packages\//)
    expect(combined).not.toMatch(/C:\\/)
  })

  test('@p2 SEC-07 未知 API 前缀不得伪装成业务成功', async ({ request }) => {
    const response = await request.get(`${env.baseURL}/api/unknown/v1/models`)
    const body = await response.text()
    // 当前会落 SPA（HTML）。登记该行为：只要不是业务成功信封即可。
    expect(body).not.toMatch(/"code"\s*:\s*"0000"/)
    expect(body).not.toMatch(/"items"\s*:\s*\[/)
  })
})
