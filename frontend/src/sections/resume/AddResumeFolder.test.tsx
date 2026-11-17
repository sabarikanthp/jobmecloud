import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { draftResume, saveNewResume } from '../../api.ts'
import AddResumeFolder from './AddResumeFolder.tsx'

vi.mock('../../api.ts', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api.ts')>()),
  draftResume: vi.fn(),
  saveNewResume: vi.fn(),
}))

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const file = (name: string, relative = '') => {
  const f = new File(['x'], name)
  if (relative) Object.defineProperty(f, 'webkitRelativePath', { value: relative })
  return f
}
const draft = (name: string, kind: 'docx' | 'pdf' = 'docx') => ({
  upload_id: `up-${name}`, kind, filename: name, reading: { summary: name, roles: [], skills: [], education: [], certifications: [] },
  mapping: kind === 'docx' ? { paragraphs: [] } : null, map_error: null,
})

let container: HTMLDivElement
let root: Root
let done: Mock<() => void>

async function mount(existing: string[] = []) {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  done = vi.fn<() => void>()
  await act(async () => root.render(<AddResumeFolder existingNames={existing} onDone={done} />))
}
async function pick(files: File[]) {
  const input = container.querySelector('input[type="file"][webkitdirectory]') as HTMLInputElement
  Object.defineProperty(input, 'files', { value: files, configurable: true })
  await act(async () => void input.dispatchEvent(new Event('change', { bubbles: true })))
}
const button = (name: string) => Array.from(container.querySelectorAll('button')).find((b) => b.textContent === name) as HTMLButtonElement | undefined

beforeEach(() => {
  vi.mocked(draftResume).mockReset().mockImplementation(async (f: File) => draft(f.name, f.name.endsWith('.pdf') ? 'pdf' : 'docx') as never)
  vi.mocked(saveNewResume).mockReset().mockResolvedValue({} as never)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

describe('AddResumeFolder', () => {
  it('lists what it will read, skipping other file types, Word temp files and resumes already in the library', async () => {
    await mount(['Old one'])
    await pick([file('Initech.docx'), file('Hooli.pdf'), file('notes.xlsx'), file('~$Initech.docx'), file('Old one.docx')])
    expect(container.textContent).toContain('2 resumes')
    expect(container.textContent).toContain('Initech')
    expect(container.textContent).toContain('Hooli')
    expect(container.textContent).not.toContain('notes')
    expect(container.textContent).toMatch(/already in your library|skipped/i)
    expect(draftResume).not.toHaveBeenCalled() // nothing is read until Start is pressed
  })

  it('reads and saves each file, named after the file, never as the default', async () => {
    await mount()
    await pick([file('Initech_Lead.docx'), file('Hooli.pdf')])
    await act(async () => void button('Add these resumes')!.click())
    expect(draftResume).toHaveBeenCalledTimes(2)
    expect(saveNewResume).toHaveBeenCalledWith(expect.objectContaining({ upload_id: 'up-Initech_Lead.docx', name: 'Initech_Lead', make_default: false }))
    expect(saveNewResume).toHaveBeenCalledWith(expect.objectContaining({ upload_id: 'up-Hooli.pdf', name: 'Hooli', mapping: null, make_default: false }))
    expect(container.textContent).toContain('Added 2 of 2')
    expect(done).toHaveBeenCalled()
  })

  it('keeps going when one file cannot be read, and says which one', async () => {
    vi.mocked(draftResume).mockImplementation(async (f: File) => {
      if (f.name === 'Bad.docx') throw new Error('Could not read that file.')
      return draft(f.name) as never
    })
    await mount()
    await pick([file('Bad.docx'), file('Good.docx')])
    await act(async () => void button('Add these resumes')!.click())
    expect(saveNewResume).toHaveBeenCalledTimes(1)
    expect(container.textContent).toContain('Added 1 of 2')
    expect(container.textContent).toContain('Bad.docx')
    expect(container.textContent).toContain('Could not read that file.')
  })

  it('does nothing when the folder has no resumes', async () => {
    await mount()
    await pick([file('notes.xlsx')])
    expect(container.textContent).toContain('No new resumes')
    expect(button('Add these resumes')).toBeUndefined()
  })
})
