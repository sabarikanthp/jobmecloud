import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import StatusBadge, { STATUS_ORDER } from './StatusBadge.tsx'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root

async function badge(status: string): Promise<HTMLElement> {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<StatusBadge status={status} />))
  return container.querySelector('.status-badge') as HTMLElement
}

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('StatusBadge', () => {
  it('gives every status its own colour class, named after the status', async () => {
    const classes = new Set<string>()
    for (const status of STATUS_ORDER) {
      const el = await badge(status)
      expect(el.textContent).toBe(status)
      classes.add(el.className)
      await act(async () => root.unmount())
      container.remove()
    }
    expect(classes.size).toBe(STATUS_ORDER.length)
    // put back something to unmount in afterEach
    await badge('New')
  })

  it('still shows a status it has never heard of, in a neutral colour', async () => {
    const el = await badge('Something new')
    expect(el.textContent).toBe('Something new')
    expect(el.className).toContain('status-other')
  })
})
