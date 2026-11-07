import { useTableRefresh } from '@/shared/composables/tableRefresh'

describe('useTableRefresh', () => {
  it('records the refresh time after a successful load', async () => {
    const { refreshing, refreshedAt, refreshError, refresh } = useTableRefresh(async () => {})

    const ok = await refresh()

    expect(ok).toBe(true)
    expect(refreshing.value).toBe(false)
    expect(refreshError.value).toBe(false)
    expect(refreshedAt.value).toBeInstanceOf(Date)
  })

  it('keeps the previous time and exposes a retry state when the load fails', async () => {
    let calls = 0
    const { refreshedAt, refreshError, refresh } = useTableRefresh(async () => {
      calls += 1
      if (calls === 2) {
        throw new Error('network down')
      }
    })

    await refresh()
    const first = refreshedAt.value
    const ok = await refresh()

    expect(ok).toBe(false)
    expect(refreshError.value).toBe(true)
    expect(refreshedAt.value).toBe(first)
  })

  it('ignores re-entrant refresh calls while one is in flight', async () => {
    let resolveLoad
    const load = () => new Promise(resolve => { resolveLoad = resolve })
    const { refresh } = useTableRefresh(load)

    const first = refresh()
    const second = await refresh()
    resolveLoad()
    await first

    expect(second).toBe(false)
  })
})
