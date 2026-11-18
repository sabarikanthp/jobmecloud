import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { setStatus } from '../api.ts'
import RepeatBanner, { type RepeatJob } from './RepeatBanner.tsx'

vi.mock('../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api.ts')>()),
  setStatus: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const EARLIER = {
  id: 5,
  employer: 'Northwind Labs',
  title: 'Director',
  status: 'Skipped',
  decided: 'Skipped: Pay too low',
  decided_date: '2026-10-30',
}
const NEW_JOB: RepeatJob = { id: 9, status: 'New', allowed_next: ['Applied', 'Duplicate'], looks_like: EARLIER }

let container: HTMLDivElement
let root: Root
let changed: Mock<() => void>

async function mount(job: RepeatJob) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  changed = vi.fn<() => void>()
  await act(async () => root.render(<RepeatBanner job={job} onChanged={changed} />))
}
const button = (name: string) => Array.from(container.querySelectorAll('button')).find((b) => b.textContent === name) as HTMLButtonElement | undefined

beforeEach(() => {
  vi.mocked(setStatus).mockReset().mockResolvedValue({} as never)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('RepeatBanner', () => {
  it('says what it looks like and what you decided about it', async () => {
    await mount(NEW_JOB)
    expect(container.textContent).toContain('Looks like')
    expect(container.textContent).toContain('Northwind Labs')
    expect(container.textContent).toContain('Skipped: Pay too low (2026-10-30)')
  })

  it('marks the job a duplicate of it in one click', async () => {
    await mount(NEW_JOB)
    await act(async () => void button('Mark as duplicate')!.click())
    expect(setStatus).toHaveBeenCalledWith(9, expect.objectContaining({ status: 'Duplicate', duplicate_of: 5 }))
    expect(changed).toHaveBeenCalled()
  })

  it('goes away when you say it is not a duplicate, and changes nothing', async () => {
    await mount(NEW_JOB)
    await act(async () => void button('Not a duplicate')!.click())
    expect(container.textContent).toBe('')
    expect(setStatus).not.toHaveBeenCalled()
  })

  it('does not offer Mark as duplicate when the status cannot change that way', async () => {
    await mount({ ...NEW_JOB, allowed_next: ['Interviewing'] })
    expect(button('Mark as duplicate')).toBeUndefined()
  })

  it('shows what a duplicate repeats, and where the original has been seen again', async () => {
    await mount({ id: 9, status: 'Duplicate', allowed_next: ['Reopen'], duplicate_of: EARLIER })
    expect(container.textContent).toContain('Duplicate of')
    expect(button('Mark as duplicate')).toBeUndefined()
    await act(async () => root.unmount())
    container.remove()
    await mount({ id: 5, status: 'Skipped', allowed_next: ['Reopen'], also_seen_as: [{ id: 9, employer: 'Northwind Labs', title: 'Director', status: 'Duplicate' }] })
    expect(container.textContent).toContain('Also seen as')
  })

  it('says nothing for a job with no history', async () => {
    await mount({ id: 9, status: 'New', allowed_next: [] })
    expect(container.textContent).toBe('')
  })

  it('shows an error in plain words when marking fails', async () => {
    vi.mocked(setStatus).mockRejectedValue(new Error('That change is not available.'))
    await mount(NEW_JOB)
    await act(async () => void button('Mark as duplicate')!.click())
    expect(container.textContent).toContain('That change is not available.')
  })
})
