import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeDocs, useAsIs, type ResumeEntry } from '../api.ts'
import DocsActions from './DocsActions.tsx'
import type { DocsRunner } from './docsTypes.ts'

vi.mock('../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api.ts')>()),
  makeDocs: vi.fn(),
  useAsIs: vi.fn(),
  openDoc: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const RESUMES = [
  { id: 'main', name: 'Main resume', is_default: true },
  { id: 'cvs', name: 'CVS version', is_default: false },
] as unknown as ResumeEntry[]
const JOB = { id: 7, docs_note: null, docs_error: null }

const runDocs: DocsRunner = async (_id, action) => {
  await action()
  return { error: null, stale: false }
}

let container: HTMLDivElement
let root: Root

async function mount(props: { hasDocs: boolean; resumes?: ResumeEntry[] }) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () =>
    root.render(
      <DocsActions job={JOB} resumes={props.resumes ?? RESUMES} defaultId="main" busyId={null} runDocs={runDocs} makeable hasDocs={props.hasDocs} />,
    ),
  )
}

const button = (name: string) => Array.from(container.querySelectorAll('button')).find((b) => b.textContent === name) as HTMLButtonElement
const startFrom = () => container.querySelector('select[aria-label="Start from"]') as HTMLSelectElement | null
async function click(b: HTMLButtonElement) {
  await act(async () => void b.click())
}
async function choose(select: HTMLSelectElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(select, value)
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

beforeEach(() => {
  vi.mocked(makeDocs).mockReset().mockResolvedValue({ note: '1 page', folder: 'x' })
  vi.mocked(useAsIs).mockReset().mockResolvedValue({ note: 'ok', folder: 'x' })
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('DocsActions feedback and source', () => {
  it('says a new resume was created after the first Make docs', async () => {
    await mount({ hasDocs: false })
    await click(button('Make docs'))
    await click(button('Make docs')) // the confirm button inside the opened panel
    expect(container.textContent).toContain('New resume and cover letter created.')
  })

  it('says the resume was updated after a regenerate', async () => {
    await mount({ hasDocs: true })
    await click(button('Regenerate'))
    await click(button('Regenerate'))
    expect(container.textContent).toContain('Resume and cover letter updated.')
    expect(container.textContent).not.toContain('New resume')
  })

  it('offers a Start from list of the library and sends the chosen resume', async () => {
    await mount({ hasDocs: true })
    await click(button('Regenerate'))
    expect(Array.from(startFrom()!.options).map((o) => o.text)).toEqual(['Main resume (default)', 'CVS version'])
    await choose(startFrom()!, 'cvs')
    await click(button('Regenerate'))
    expect(makeDocs).toHaveBeenCalledWith(7, null, 'cvs')
  })

  it('does not send a resume when the default is kept', async () => {
    await mount({ hasDocs: true })
    await click(button('Regenerate'))
    await click(button('Regenerate'))
    expect(makeDocs).toHaveBeenCalledWith(7, null, null)
  })

  it('has no Start from list when there is only one resume', async () => {
    await mount({ hasDocs: true, resumes: [RESUMES[0]!] })
    await click(button('Regenerate'))
    expect(startFrom()).toBeNull()
  })

  it('says which resume is now in use after Use as-is', async () => {
    await mount({ hasDocs: true })
    await click(button('Use'))
    expect(container.textContent).toContain('Now using Main resume as-is.')
  })
})
