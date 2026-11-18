import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { fitJob, getFitChoices, saveDescription, type FitResult } from '../api.ts'
import ReEvaluate from './ReEvaluate.tsx'

vi.mock('../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api.ts')>()),
  fitJob: vi.fn(),
  getFitChoices: vi.fn(),
  saveDescription: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const CHOICES = [
  { id: 'score', label: 'haiku (Anthropic)', default: true },
  { id: 'tailor', label: 'sonnet (Anthropic)', default: false },
]
const FIT: FitResult = {
  score: 77, cutoff: 75, above_cutoff: true, reasons: 'Solid platform background.', gaps: '', warnings: [], rules: [],
  model: 'haiku', cost_usd: 0.01,
}
const fitReply = () => ({ fit: FIT, job: { id: 4, status: 'New', allowed_next: [], match_score: 77 } })

let container: HTMLDivElement
let root: Root
let changed: Mock<() => void>

async function mount(description: string | null) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  changed = vi.fn<() => void>()
  await act(async () => root.render(<ReEvaluate job={{ id: 4, description }} onChanged={changed} />))
}
const box = () => container.querySelector('textarea') as HTMLTextAreaElement | null
const button = (name: string) => Array.from(container.querySelectorAll('button')).find((b) => b.textContent === name) as HTMLButtonElement | undefined
async function type(el: HTMLTextAreaElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function click(b: HTMLButtonElement | undefined) {
  await act(async () => void b!.click())
}

beforeEach(() => {
  vi.mocked(getFitChoices).mockReset().mockResolvedValue(CHOICES)
  vi.mocked(saveDescription).mockReset().mockResolvedValue({ details_read: true, message: null, truncated: false })
  vi.mocked(fitJob).mockReset().mockResolvedValue(fitReply())
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('ReEvaluate', () => {
  it('explains there is no fit and asks for the description when the page could not be read', async () => {
    await mount(null)
    expect(container.textContent).toContain('could not read')
    expect(box()).toBeTruthy()
    expect(button('Re-evaluate')!.disabled).toBe(true)
    await type(box()!, 'Director of Engineering. '.repeat(20))
    expect(button('Re-evaluate')!.disabled).toBe(false)
  })

  it('saves the description, then judges the fit with the chosen AI, then refreshes', async () => {
    await mount(null)
    await type(box()!, 'The whole posting. '.repeat(20))
    await click(button('Re-evaluate'))
    expect(saveDescription).toHaveBeenCalledWith(4, 'The whole posting. '.repeat(20))
    expect(fitJob).toHaveBeenCalledWith(4, 'score')
    expect(vi.mocked(saveDescription).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(fitJob).mock.invocationCallOrder[0])
    expect(container.textContent).toContain('Solid platform background.')
    expect(changed).toHaveBeenCalled()
  })

  it('stops with the reason when the description cannot be saved, and does not judge', async () => {
    vi.mocked(saveDescription).mockRejectedValue(new Error('That is too short to be a job posting.'))
    await mount(null)
    await type(box()!, 'short')
    await click(button('Re-evaluate'))
    expect(container.textContent).toContain('too short')
    expect(fitJob).not.toHaveBeenCalled()
  })

  it('keeps the saved description when judging fails, and retries without pasting again', async () => {
    vi.mocked(fitJob).mockRejectedValueOnce(new Error('The API key was rejected.'))
    await mount(null)
    await type(box()!, 'The whole posting. '.repeat(20))
    await click(button('Re-evaluate'))
    expect(container.textContent).toContain('The API key was rejected.')
    expect(container.textContent).toContain('Your description is saved')
    await click(button('Re-evaluate'))
    expect(saveDescription).toHaveBeenCalledTimes(1)
    expect(fitJob).toHaveBeenCalledTimes(2)
    expect(container.textContent).toContain('Solid platform background.')
  })

  it('tells you when the description was kept but its details could not be read, and still judges', async () => {
    vi.mocked(saveDescription).mockResolvedValue({ details_read: false, message: 'That took too long.', truncated: false })
    await mount(null)
    await type(box()!, 'The whole posting. '.repeat(20))
    await click(button('Re-evaluate'))
    expect(container.textContent).toContain('details could not be read')
    expect(fitJob).toHaveBeenCalled()
  })

  it('re-evaluates a job that already has a description without asking for one', async () => {
    await mount('Existing description text.')
    expect(box()).toBeNull()
    await click(button('Re-evaluate'))
    expect(saveDescription).not.toHaveBeenCalled()
    expect(fitJob).toHaveBeenCalledWith(4, 'score')
  })

  it('lets you replace the description of a job that has one', async () => {
    await mount('Existing description text.')
    await click(button('Paste a different description'))
    await type(box()!, 'A better posting. '.repeat(20))
    await click(button('Re-evaluate'))
    expect(saveDescription).toHaveBeenCalledWith(4, 'A better posting. '.repeat(20))
  })
})
