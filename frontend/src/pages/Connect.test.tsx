import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { approveOAuth, getOAuthClient } from '../api.ts'
import { nav } from '../auth.ts'
import Connect from './Connect.tsx'

vi.mock('../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api.ts')>()),
  getOAuthClient: vi.fn(),
  approveOAuth: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const HASH =
  '#/connect?client_id=jmc-abc&redirect_uri=' + encodeURIComponent('https://chatgpt.com/cb') + '&state=st%201&code_challenge=' + 'c'.repeat(43)

let container: HTMLDivElement
let root: Root

async function mount(hash: string) {
  window.location.hash = hash
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<Connect />))
}
const button = (name: string) =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent === name) as HTMLButtonElement | undefined
async function click(el: HTMLElement | undefined) {
  await act(async () => el!.dispatchEvent(new MouseEvent('click', { bubbles: true })))
}

describe('Connect', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getOAuthClient).mockResolvedValue({ name: 'ChatGPT', redirect_hosts: ['chatgpt.com'] })
    vi.mocked(approveOAuth).mockResolvedValue({ redirect_to: 'https://chatgpt.com/cb?code=abc&state=st%201' })
    vi.spyOn(nav, 'to').mockImplementation(() => {})
  })
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.restoreAllMocks()
  })

  it('shows the app name and where it will return to', async () => {
    await mount(HASH)
    expect(getOAuthClient).toHaveBeenCalledWith('jmc-abc')
    expect(container.textContent).toContain('ChatGPT')
    expect(container.textContent).toContain('chatgpt.com')
    expect(container.textContent).toContain('Only approve if you just started this')
  })

  it('defaults to read only', async () => {
    await mount(HASH)
    const radios = Array.from(container.querySelectorAll('input[type="radio"]')) as HTMLInputElement[]
    expect(radios.find((r) => r.checked)!.value).toBe('read')
  })

  it('approves with the chosen scope and sends the browser back', async () => {
    await mount(HASH)
    const radios = Array.from(container.querySelectorAll('input[type="radio"]')) as HTMLInputElement[]
    await click(radios.find((r) => r.value === 'readwrite'))
    await click(button('Approve'))
    expect(approveOAuth).toHaveBeenCalledWith({
      client_id: 'jmc-abc',
      redirect_uri: 'https://chatgpt.com/cb',
      state: 'st 1',
      code_challenge: 'c'.repeat(43),
      scope: 'readwrite',
      approve: true,
    })
    expect(nav.to).toHaveBeenCalledWith('https://chatgpt.com/cb?code=abc&state=st%201')
  })

  it('cancel sends approve false', async () => {
    await mount(HASH)
    vi.mocked(approveOAuth).mockResolvedValue({ redirect_to: 'https://chatgpt.com/cb?error=access_denied' })
    await click(button('Cancel'))
    expect(vi.mocked(approveOAuth).mock.calls[0][0].approve).toBe(false)
    expect(nav.to).toHaveBeenCalledWith('https://chatgpt.com/cb?error=access_denied')
  })

  it('an unknown app shows an error and no buttons', async () => {
    vi.mocked(getOAuthClient).mockRejectedValue(new Error('No such app.'))
    await mount(HASH)
    expect(container.textContent).toContain('No such app.')
    expect(button('Approve')).toBeUndefined()
  })

  it('a link without a client id is not valid', async () => {
    await mount('#/connect?state=x')
    expect(container.textContent).toContain('This link is not valid')
    expect(getOAuthClient).not.toHaveBeenCalled()
    expect(button('Approve')).toBeUndefined()
  })
})
