import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { askSimilar, getSimilar, listJobs } from '../api.ts'
import DuplicatePicker from './DuplicatePicker.tsx'

vi.mock('../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api.ts')>()),
  getSimilar: vi.fn(),
  askSimilar: vi.fn(),
  listJobs: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const OLD = {
  id: 5,
  employer: 'Northwind Labs',
  title: 'Director, Engineering',
  status: 'Skipped',
  decided: 'Skipped: Pay too low',
  decided_date: '2026-10-30',
}
const MATCH = { ...OLD, strength: 'strong' as const, reasons: ['Same requisition (R-1)'] }

let container: HTMLDivElement
let root: Root
let picked: Mock<(id: number) => void>
let cancelled: Mock<() => void>

async function mount() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  picked = vi.fn<(id: number) => void>()
  cancelled = vi.fn<() => void>()
  await act(async () => root.render(<DuplicatePicker jobId={9} onPick={picked} onCancel={cancelled} />))
}
const button = (name: string) =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.includes(name)) as HTMLButtonElement | undefined
async function click(b: HTMLButtonElement | undefined) {
  await act(async () => void b!.click())
}

beforeEach(() => {
  vi.mocked(getSimilar).mockReset().mockResolvedValue({ matches: [MATCH] })
  vi.mocked(askSimilar).mockReset().mockResolvedValue({ verdicts: [], message: null, model: 'm', cost_usd: 0.01 })
  vi.mocked(listJobs).mockReset().mockResolvedValue({ total: 0, rows: [] })
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('DuplicatePicker', () => {
  it('lists the likely matches with why, and what you decided about them', async () => {
    await mount()
    expect(container.textContent).toContain('Northwind Labs')
    expect(container.textContent).toContain('Same requisition (R-1)')
    expect(container.textContent).toContain('Skipped: Pay too low')
  })

  it('marks the chosen job as the original', async () => {
    await mount()
    await click(button('This is the one'))
    expect(picked).toHaveBeenCalledWith(5)
  })

  it('says so when nothing looks like it, and still offers a search', async () => {
    vi.mocked(getSimilar).mockResolvedValue({ matches: [] })
    await mount()
    expect(container.textContent).toContain('Nothing in your tracker looks like this job')
    expect(button('Search')).toBeTruthy()
  })

  it('searches the tracker and lets you pick a result, never the job itself', async () => {
    vi.mocked(listJobs).mockResolvedValue({
      total: 2,
      rows: [
        { id: 9, employer: 'Self', title: 'Me', status: 'New' },
        { id: 12, employer: 'Globex', title: 'Chef', status: 'New' },
      ],
    } as never)
    await mount()
    const input = container.querySelector('input[type="search"]') as HTMLInputElement
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'globex')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click(button('Search'))
    expect(listJobs).toHaveBeenCalledWith(expect.objectContaining({ q: 'globex' }))
    expect(container.textContent).toContain('Globex')
    expect(container.textContent).not.toContain('Self')
  })

  it('asks the AI and shows what it thinks, with a way to pick the one it calls the same', async () => {
    vi.mocked(askSimilar).mockResolvedValue({
      verdicts: [{ ...OLD, same: 'same', reason: 'Same responsibilities and wording.' }],
      message: null,
      model: 'claude',
      cost_usd: 0.012,
    })
    await mount()
    await click(button('Ask the AI'))
    expect(askSimilar).toHaveBeenCalledWith(9)
    expect(container.textContent).toContain('Same responsibilities and wording.')
    expect(container.textContent).toContain('about $0.01')
    const picks = Array.from(container.querySelectorAll('button')).filter((b) => b.textContent?.includes('This is the one'))
    await click(picks[picks.length - 1])
    expect(picked).toHaveBeenCalledWith(5)
  })

  it('shows a message when the AI has nothing to compare, and its errors in plain words', async () => {
    vi.mocked(askSimilar).mockResolvedValueOnce({
      verdicts: [],
      message: 'Nothing in your tracker looks like this job.',
      model: null,
      cost_usd: 0,
    })
    await mount()
    await click(button('Ask the AI'))
    expect(container.textContent).toContain('Nothing in your tracker looks like this job.')
    vi.mocked(askSimilar).mockRejectedValueOnce(new Error('The API key was rejected.'))
    await click(button('Ask the AI'))
    expect(container.textContent).toContain('The API key was rejected.')
  })

  it('can be cancelled', async () => {
    await mount()
    await click(button('Cancel'))
    expect(cancelled).toHaveBeenCalled()
  })
})
