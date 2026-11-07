import { deletion, requestDeletion, settleDeletion } from '@/shared/composables/deletion'

describe('deletion confirmation', () => {
  afterEach(() => {
    settleDeletion(false)
  })

  it('opens the shared dialog and resolves true when confirmed', async () => {
    const pending = requestDeletion({
      resourceType: '知识库',
      items: [{ id: 'kb-1', name: 'demo' }]
    })

    expect(deletion.open).toBe(true)
    expect(deletion.options.items).toHaveLength(1)

    settleDeletion(true)
    await expect(pending).resolves.toBe(true)
    expect(deletion.open).toBe(false)
  })

  it('resolves false when the dialog is dismissed', async () => {
    const pending = requestDeletion({ items: [{ id: 'kb-1', name: 'demo' }] })

    settleDeletion(false)
    await expect(pending).resolves.toBe(false)
  })

  it('does not open the dialog for an empty selection', async () => {
    await expect(requestDeletion({ items: [] })).resolves.toBe(false)
    expect(deletion.open).toBe(false)
  })

  it('settles a previous request before starting a new one', async () => {
    const first = requestDeletion({ items: [{ id: 'kb-1', name: 'first' }] })
    const second = requestDeletion({ items: [{ id: 'kb-2', name: 'second' }] })

    await expect(first).resolves.toBe(false)
    expect(deletion.options.items[0].name).toBe('second')
    settleDeletion(true)
    await expect(second).resolves.toBe(true)
  })
})
