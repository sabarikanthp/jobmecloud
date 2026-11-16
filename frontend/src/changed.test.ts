import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { configure } from './auth.ts'
import { CHANGED_EVENT, getProviders, reopenJob } from './api.ts'

let heard: number

beforeEach(() => {
  configure(null)
  heard = 0
  window.addEventListener(CHANGED_EVENT, onChanged)
})
afterEach(() => {
  window.removeEventListener(CHANGED_EVENT, onChanged)
  vi.unstubAllGlobals()
})

function onChanged() {
  heard += 1
}

const reply = (body: unknown, status = 200) => vi.fn(async () => new Response(JSON.stringify(body), { status }))

describe('announcing changes', () => {
  it('a successful write announces that something changed', async () => {
    vi.stubGlobal('fetch', reply({ id: 1 }))
    await reopenJob(1)
    expect(heard).toBe(1)
  })

  it('a read does not', async () => {
    vi.stubGlobal('fetch', reply([]))
    await getProviders()
    expect(heard).toBe(0)
  })

  it('a failed write does not', async () => {
    vi.stubGlobal('fetch', reply({ detail: 'No' }, 400))
    await expect(reopenJob(1)).rejects.toThrow('No')
    expect(heard).toBe(0)
  })
})
