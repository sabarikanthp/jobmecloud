import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApiKey, listApiKeys, revokeApiKey, type ApiKeyOut } from '../api.ts'
import ClaudeAccessSection, { desktopConfig } from './ClaudeAccessSection.tsx'

vi.mock('../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api.ts')>()),
  listApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const KEY: ApiKeyOut = {
  id: 1, name: 'Laptop', prefix: 'jmc_Ab12', scope: 'read', created_at: '2026-11-01T10:00:00Z',
  expires_at: null, last_used_at: null, revoked_at: null,
}

let container: HTMLDivElement
let root: Root

async function mount(keys: ApiKeyOut[]) {
  vi.mocked(listApiKeys).mockResolvedValue(keys)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<ClaudeAccessSection />))
}
const button = (name: string) =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent === name) as HTMLButtonElement | undefined
async function click(b: HTMLElement | undefined) {
  await act(async () => b!.dispatchEvent(new MouseEvent('click', { bubbles: true })))
}
async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('desktopConfig', () => {
  it('puts the key in an environment variable and the header uses /api/mcp', () => {
    const cfg = JSON.parse(desktopConfig('https://jobs.example.com', 'jmc_secret'))
    const server = cfg.mcpServers.jobme
    expect(server.command).toBe('npx')
    expect(server.args).toEqual(['-y', 'mcp-remote', 'https://jobs.example.com/api/mcp', '--header', 'Authorization:${AUTH_HEADER}'])
    expect(server.env.AUTH_HEADER).toBe('Bearer jmc_secret')
  })
})

describe('ClaudeAccessSection', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('lists keys with name, scope, prefix and last use', async () => {
    await mount([KEY, { ...KEY, id: 2, name: 'Old', scope: 'readwrite', revoked_at: '2026-11-02T10:00:00Z', last_used_at: '2026-11-03T10:00:00Z' }])
    const text = container.textContent ?? ''
    expect(text).toContain('Laptop')
    expect(text).toContain('jmc_Ab12')
    expect(text).toContain('Read only')
    expect(text).toContain('Never used')
    expect(text).toContain('Read and change')
    expect(text).toContain('Revoked')
  })

  it('creates a key, shows it once with the config, and hides it when done', async () => {
    await mount([])
    vi.mocked(createApiKey).mockResolvedValue({ ...KEY, id: 3, name: 'Desktop', key: 'jmc_FULLKEY' })
    await type(container.querySelector('input[type="text"]') as HTMLInputElement, 'Desktop')
    await click(button('Create key'))
    expect(createApiKey).toHaveBeenCalledWith('Desktop', 'read', null)
    expect(container.textContent).toContain('jmc_FULLKEY')
    expect(container.textContent).toContain('/api/mcp')
    expect(button('Copy key')).toBeTruthy()
    await click(button('Done'))
    expect(container.textContent).not.toContain('jmc_FULLKEY')
  })

  it('defaults to read only and warns when read and change is chosen', async () => {
    await mount([])
    const radios = Array.from(container.querySelectorAll('input[type="radio"]')) as HTMLInputElement[]
    expect(radios.find((r) => r.checked)!.value).toBe('read')
    expect(container.textContent).not.toContain('can change your jobs')
    await click(radios.find((r) => r.value === 'readwrite'))
    expect(container.textContent).toContain('can change your jobs')
  })

  it('revokes only after you confirm', async () => {
    await mount([KEY])
    vi.mocked(revokeApiKey).mockResolvedValue(undefined)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    await click(button('Revoke'))
    expect(revokeApiKey).not.toHaveBeenCalled()
    await click(button('Revoke'))
    expect(revokeApiKey).toHaveBeenCalledWith(1)
    confirm.mockRestore()
  })
})
