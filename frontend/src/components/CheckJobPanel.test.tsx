import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { checkJob, fitJob, getFitChoices, type CheckResult, type FitResult } from '../api.ts'
import CheckJobPanel from './CheckJobPanel.tsx'

vi.mock('../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api.ts')>()),
  checkJob: vi.fn(),
  fitJob: vi.fn(),
  getFitChoices: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const CHOICES = [
  { id: 'score', label: 'claude-haiku-5-5 (Anthropic)', default: true },
  { id: 'tailor', label: 'claude-sonnet-5-5 (Anthropic)', default: false },
]
const JOB = { id: 12, employer: 'Northwind Labs', title: 'Senior Data Engineer', status: 'New', match_score: null, apply_url: null, allowed_next: ['Applied', 'Skipped'] }
const FIT: FitResult = {
  score: 82, cutoff: 75, above_cutoff: true, reasons: 'Strong data platform background.', gaps: 'No Spark in production.',
  warnings: ['Travel 50%'], rules: [{ rule: 'Minimum pay', passed: false, note: 'Top of range $100,000 is below your minimum $150,000.' }, { rule: 'Work mode', passed: true, note: '' }],
  model: 'claude-haiku-5-5', cost_usd: 0.012,
}
const created = (): CheckResult => ({ status: 'created', truncated: false, job: JOB })
const fitReply = (fit: FitResult = FIT) => ({ fit, job: { id: 12, status: 'New', allowed_next: ['Applied', 'Skipped'], match_score: fit.score } })

let container: HTMLDivElement
let root: Root
let changed: Mock<() => void>

async function mount() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  changed = vi.fn<() => void>()
  await act(async () => root.render(<CheckJobPanel skipReasons={['Pay too low']} onChanged={changed} onClose={() => {}} />))
}

const box = () => container.querySelector('textarea') as HTMLTextAreaElement
const model = () => container.querySelector('select[aria-label="AI for the fit"]') as HTMLSelectElement
const button = (name: string) => Array.from(container.querySelectorAll('button')).find((b) => b.textContent === name) as HTMLButtonElement | undefined

async function type(el: HTMLTextAreaElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
    setter.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function choose(select: HTMLSelectElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    setter.call(select, value)
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}
async function click(b: HTMLButtonElement | undefined) {
  await act(async () => void b!.click())
}

beforeEach(() => {
  vi.mocked(getFitChoices).mockReset().mockResolvedValue(CHOICES)
  vi.mocked(checkJob).mockReset().mockResolvedValue(created())
  vi.mocked(fitJob).mockReset().mockResolvedValue(fitReply())
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('CheckJobPanel', () => {
  it('disables Check fit until something is pasted', async () => {
    await mount()
    expect(button('Check fit')!.disabled).toBe(true)
    await type(box(), '   ')
    expect(button('Check fit')!.disabled).toBe(true)
    await type(box(), 'https://jobs.example/1')
    expect(button('Check fit')!.disabled).toBe(false)
  })

  it('lists the choices with the default selected', async () => {
    await mount()
    expect(Array.from(model().options).map((o) => o.text)).toEqual(CHOICES.map((c) => c.label))
    expect(model().value).toBe('score')
  })

  it('sends the pasted input as typed with the chosen model', async () => {
    await mount()
    await type(box(), '  Senior Data Engineer at Northwind\nBuild things.  ')
    await choose(model(), 'tailor')
    await click(button('Check fit'))
    expect(checkJob).toHaveBeenCalledWith('  Senior Data Engineer at Northwind\nBuild things.  ')
    expect(fitJob).toHaveBeenCalledWith(12, 'tailor')
  })

  it('shows reading, then judging', async () => {
    let finishRead!: (r: CheckResult) => void
    let finishFit!: (r: ReturnType<typeof fitReply>) => void
    vi.mocked(checkJob).mockReturnValue(new Promise((r) => (finishRead = r)))
    vi.mocked(fitJob).mockReturnValue(new Promise((r) => (finishFit = r)))
    await mount()
    await type(box(), 'some job text')
    await click(button('Check fit'))
    expect(container.textContent).toContain('Reading the job…')
    await act(async () => finishRead(created()))
    expect(container.textContent).toContain('Judging the fit…')
    await act(async () => finishFit(fitReply()))
    expect(container.textContent).not.toContain('Judging the fit…')
  })

  it('shows the score beside the cutoff, the reasons, gaps, warnings and failed rules', async () => {
    await mount()
    await type(box(), 'some job text')
    await click(button('Check fit'))
    const text = container.textContent!
    expect(text).toContain('82')
    expect(text).toContain('cutoff 75')
    expect(text).toContain('Strong data platform background.')
    expect(text).toContain('No Spark in production.')
    expect(text).toContain('Travel 50%')
    expect(text).toContain('Minimum pay')
    expect(text).toContain('below your minimum')
    expect(text).not.toContain('Work mode') // only failed rules are listed
  })

  it('shows an existing job with a link and a Re-check fit button when the job is a duplicate', async () => {
    vi.mocked(checkJob).mockResolvedValue({ status: 'duplicate', truncated: false, job: { ...JOB, match_score: 70 } })
    await mount()
    await type(box(), 'some job text')
    await click(button('Check fit'))
    expect(container.textContent).toContain('already in your tracker')
    const link = container.querySelector('a.link') as HTMLAnchorElement
    expect(link.textContent).toContain('Northwind Labs')
    expect(link.getAttribute('href')).toContain('12')
    expect(fitJob).not.toHaveBeenCalled()
    expect(button('Re-check fit')).toBeTruthy()
  })

  it('re-checks the existing job when asked', async () => {
    vi.mocked(checkJob).mockResolvedValue({ status: 'duplicate', truncated: false, job: JOB })
    await mount()
    await type(box(), 'some job text')
    await click(button('Check fit'))
    await click(button('Re-check fit'))
    expect(fitJob).toHaveBeenCalledWith(12, 'score')
    expect(container.textContent).toContain('Strong data platform background.')
  })

  it('shows a read error and nothing else', async () => {
    vi.mocked(checkJob).mockRejectedValue(new Error('JobMeCloud couldn\'t read that page. Paste the text instead.'))
    await mount()
    await type(box(), 'https://jobs.example/1')
    await click(button('Check fit'))
    expect(container.textContent).toContain("couldn't read that page")
    expect(fitJob).not.toHaveBeenCalled()
    expect(changed).not.toHaveBeenCalled()
    expect(container.querySelector('.fit-card')).toBeNull()
    expect(button('Retry fit')).toBeUndefined()
  })

  it('keeps the saved job and offers a retry when the judgment fails', async () => {
    vi.mocked(fitJob).mockRejectedValueOnce(new Error('The API key was rejected.'))
    await mount()
    await type(box(), 'some job text')
    await click(button('Check fit'))
    expect(container.textContent).toContain('The API key was rejected.')
    expect(container.textContent).toContain('Northwind Labs')
    expect(container.textContent).toContain('saved')
    await click(button('Retry fit'))
    expect(fitJob).toHaveBeenCalledTimes(2)
    expect(container.textContent).toContain('Strong data platform background.')
  })

  it('tells the list to refresh once a job is saved, and again after the fit', async () => {
    await mount()
    await type(box(), 'some job text')
    await click(button('Check fit'))
    expect(changed.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})
