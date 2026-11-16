import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CHANGED_EVENT, getFollowUpCounts } from './api.ts'
import { followUpBadge, useFollowUpCounts } from './followUps.ts'

vi.mock('./api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api.ts')>()),
  getFollowUpCounts: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('followUpBadge', () => {
  it('is hidden at zero and while the count is unknown', () => {
    expect(followUpBadge(null)).toBeNull()
    expect(followUpBadge({ overdue: 0, due_today: 0 })).toBeNull()
  })

  it('shows the total of overdue and due today', () => {
    expect(followUpBadge({ overdue: 2, due_today: 1 })?.text).toBe('3')
    expect(followUpBadge({ overdue: 0, due_today: 4 })?.text).toBe('4')
  })

  it('is marked overdue when anything is overdue', () => {
    expect(followUpBadge({ overdue: 1, due_today: 0 })?.overdue).toBe(true)
    expect(followUpBadge({ overdue: 0, due_today: 3 })?.overdue).toBe(false)
  })

  it('has a label that says what the number is', () => {
    expect(followUpBadge({ overdue: 1, due_today: 2 })?.label).toBe('Follow-ups, 3 due (1 overdue)')
    expect(followUpBadge({ overdue: 0, due_today: 2 })?.label).toBe('Follow-ups, 2 due')
  })

  it('does not let a huge number break the menu', () => {
    expect(followUpBadge({ overdue: 150, due_today: 0 })?.text).toBe('99+')
  })
})

function Probe() {
  const counts = useFollowUpCounts()
  return <div id="probe" data-total={counts ? counts.overdue + counts.due_today : 'unknown'} />
}

let container: HTMLDivElement
let root: Root
const total = () => (container.querySelector('#probe') as HTMLElement).dataset.total
const fetches = () => vi.mocked(getFollowUpCounts).mock.calls.length

async function mount() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => root.render(<Probe />))
}

async function settle(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('useFollowUpCounts', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(getFollowUpCounts).mockReset().mockResolvedValue({ overdue: 1, due_today: 2 })
  })
  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
    vi.useRealTimers()
  })

  it('fetches on mount', async () => {
    await mount()
    await settle()
    expect(fetches()).toBe(1)
    expect(total()).toBe('3')
  })

  it('fetches again when the window regains focus and when the page changes', async () => {
    await mount()
    await settle()
    await act(async () => void window.dispatchEvent(new Event('focus')))
    await act(async () => void window.dispatchEvent(new HashChangeEvent('hashchange')))
    expect(fetches()).toBe(3)
  })

  it('fetches again every five minutes', async () => {
    await mount()
    await settle()
    await settle(5 * 60_000)
    expect(fetches()).toBe(2)
    await settle(5 * 60_000)
    expect(fetches()).toBe(3)
  })

  it('refetches after a change signal, and a burst of signals makes one fetch', async () => {
    await mount()
    await settle()
    await act(async () => {
      for (let i = 0; i < 3; i++) window.dispatchEvent(new Event(CHANGED_EVENT))
    })
    expect(fetches()).toBe(1) // not yet: waiting for the burst to end
    await settle(500)
    expect(fetches()).toBe(2)
  })

  it('keeps the last count when a fetch fails', async () => {
    await mount()
    await settle()
    vi.mocked(getFollowUpCounts).mockRejectedValue(new Error('offline'))
    await act(async () => void window.dispatchEvent(new Event('focus')))
    expect(total()).toBe('3')
  })

  it('stops listening when it is removed', async () => {
    await mount()
    await settle()
    await act(async () => root.unmount())
    const before = fetches()
    window.dispatchEvent(new Event('focus'))
    await settle(10 * 60_000)
    expect(fetches()).toBe(before)
    root = createRoot(container) // so afterEach can unmount cleanly
  })
})
