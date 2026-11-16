import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { reopenJob, setStatus } from '../api.ts'
import { todayISO } from '../dates.ts'
import RowStatus from './RowStatus.tsx'

vi.mock('../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api.ts')>()),
  setStatus: vi.fn(),
  reopenJob: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const REASONS = ['Pay too low', 'Location', 'Other']
const NEW_JOB = { id: 7, status: 'New', allowed_next: ['Applied', 'Skipped', 'Rejected', 'Withdrawn'] }

let container: HTMLDivElement
let root: Root
let changed: Mock<() => void>

async function mount(job = NEW_JOB) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  changed = vi.fn<() => void>()
  await act(async () => root.render(<RowStatus job={job} skipReasons={REASONS} onChanged={changed} />))
}

const status = () => container.querySelector('select[aria-label="Change status"]') as HTMLSelectElement | null
const reason = () => container.querySelector('select[aria-label="Reason for skipping"]') as HTMLSelectElement | null
const optionTexts = (select: HTMLSelectElement) => Array.from(select.options).map((o) => o.text)

async function choose(select: HTMLSelectElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    setter.call(select, value)
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

beforeEach(() => {
  vi.mocked(setStatus).mockReset().mockResolvedValue({ follow_up_id: null } as never)
  vi.mocked(reopenJob).mockReset().mockResolvedValue({} as never)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('RowStatus', () => {
  it('shows the current status and offers only the moves that are allowed', async () => {
    await mount()
    expect(container.textContent).toContain('New')
    expect(optionTexts(status()!)).toEqual(['Change…', 'Mark applied', 'Skip', 'Rejected', 'I withdrew'])
  })

  it('shows just the status, and does not break, when the server did not say which moves are allowed', async () => {
    await mount({ id: 7, status: 'New' } as never) // an older server without the field
    expect(container.textContent).toContain('New')
    expect(status()).toBeNull()
  })

  it('offers no control when nothing can change', async () => {
    await mount({ id: 7, status: 'Accepted', allowed_next: [] })
    expect(container.textContent).toContain('Accepted')
    expect(status()).toBeNull()
  })

  it('applies a status that needs no reason as soon as it is chosen, dated today', async () => {
    await mount()
    await choose(status()!, 'Applied')
    expect(setStatus).toHaveBeenCalledWith(7, { status: 'Applied', date: todayISO(), note: null, skip_reason: null, skip_note: null })
    expect(changed).toHaveBeenCalledTimes(1)
    expect(status()!.value).toBe('') // back to "Change…"
  })

  it('asks for a reason before skipping, and skips with it', async () => {
    await mount()
    await choose(status()!, 'Skipped')
    expect(setStatus).not.toHaveBeenCalled()
    expect(optionTexts(reason()!)).toEqual(['Why skip?', ...REASONS])
    await choose(reason()!, 'Location')
    expect(setStatus).toHaveBeenCalledWith(7, { status: 'Skipped', date: todayISO(), note: null, skip_reason: 'Location', skip_note: null })
    expect(changed).toHaveBeenCalledTimes(1)
    expect(reason()).toBeNull()
  })

  it('lets you back out of skipping without changing anything', async () => {
    await mount()
    await choose(status()!, 'Skipped')
    const cancel = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Cancel')!
    await act(async () => cancel.click())
    expect(reason()).toBeNull()
    expect(setStatus).not.toHaveBeenCalled()
    expect(changed).not.toHaveBeenCalled()
  })

  it('reopens a job through its own call', async () => {
    await mount({ id: 7, status: 'Skipped', allowed_next: ['Reopen'] })
    await choose(status()!, 'Reopen')
    expect(reopenJob).toHaveBeenCalledWith(7, null)
    expect(setStatus).not.toHaveBeenCalled()
    expect(changed).toHaveBeenCalledTimes(1)
  })

  it('shows what went wrong and changes nothing when the server refuses', async () => {
    vi.mocked(setStatus).mockRejectedValue(new Error('You cannot do that from here.'))
    await mount()
    await choose(status()!, 'Applied')
    expect(container.textContent).toContain('You cannot do that from here.')
    expect(changed).not.toHaveBeenCalled()
    expect(status()!.value).toBe('')
  })
})
