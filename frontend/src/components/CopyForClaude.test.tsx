import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CopyForClaude from './CopyForClaude.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root

async function mount(text: string) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<CopyForClaude text={text} />))
}

describe('CopyForClaude', () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => {
    act(() => root.unmount())
    container.remove()
  })

  it('copies the reference text and says Copied', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    await mount('JobMe job 123: Acme – Staff Engineer')
    await act(async () => container.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true })))
    expect(writeText).toHaveBeenCalledWith('JobMe job 123: Acme – Staff Engineer')
    expect(container.textContent).toContain('Copied')
  })

  it('shows the text to copy by hand when the clipboard is unavailable', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    await mount('JobMe job 7: A – B')
    await act(async () => container.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true })))
    expect((container.querySelector('input') as HTMLInputElement).value).toBe('JobMe job 7: A – B')
  })
})
