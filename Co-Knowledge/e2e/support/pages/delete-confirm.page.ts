import { expect, type Page } from '@playwright/test'

/**
 * 全站统一删除确认弹窗（`frontend/src/shared/ui/DeleteConfirmDialog.vue`）。
 *
 * 弹窗由 `requestDeletion()` 全局挂载，类名是 `.el-dialog.delete-confirm-dialog`；
 * 四位确认码在 `.delete-confirm-challenge code`，输入框是 `.delete-confirm-code-row input`，
 * 填对之前 `.delete-confirm-submit` 一直禁用。
 */
export function deleteConfirmDialog (page: Page) {
  return page.locator('.el-dialog.delete-confirm-dialog')
}

export async function confirmDeletion (page: Page): Promise<void> {
  const dialog = deleteConfirmDialog(page)
  await expect(dialog).toBeVisible()
  const code = (await dialog.locator('.delete-confirm-challenge code').innerText()).trim()
  await dialog.locator('.delete-confirm-code-row input').fill(code)
  await dialog.locator('button.delete-confirm-submit').click()
  await expect(dialog).toBeHidden()
}
