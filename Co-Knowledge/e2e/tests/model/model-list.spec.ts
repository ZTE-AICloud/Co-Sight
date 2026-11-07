import { test, expect } from '../../support/fixtures/test'
import { ModelPage } from '../../support/pages/model.page'

test.describe('模型管理', () => {
  test('@fast @p0 MODEL-01 列表加载与三类模型页签', async ({ page, api }) => {
    const modelPage = new ModelPage(page)
    await modelPage.goto()

    await expect(modelPage.tabs.filter({ hasText: '大语言模型' })).toBeVisible()
    await expect(modelPage.tabs.filter({ hasText: '向量模型' })).toBeVisible()
    await expect(modelPage.tabs.filter({ hasText: '重排模型' })).toBeVisible()

    // 种子模型至少包含一个 LLM；不要写死数量，避免不同环境种子差异。
    const llmRows = await modelPage.rows.count()
    expect(llmRows).toBeGreaterThan(0)

    const llms = await api.listModels('llm')
    expect(llms.length).toBeGreaterThan(0)
    await modelPage.expectRow(llms[0].modelName)
  })
})
