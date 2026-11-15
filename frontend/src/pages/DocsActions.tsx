import { useState, type ReactNode } from 'react'
import { makeDocs, openDoc, useAsIs as applyAsIs, type ResumeEntry } from '../api.ts'
import { errorText } from './jobFormat.ts'
import { STALE_NOTE, type DocsRunner } from './docsTypes.ts'

export interface DocsJob {
  id: number
  docs_note: string | null
  docs_error: string | null
}

// The document actions shared by the Today cards and the Job page:
// open the files, use a resume as-is, and make or regenerate with optional feedback.
// `children` is shown between the open buttons and the make/regenerate controls.
export default function DocsActions({
  job,
  resumes,
  defaultId,
  busyId,
  runDocs,
  makeable,
  hasDocs = true,
  children,
}: {
  job: DocsJob
  resumes: ResumeEntry[]
  defaultId: string | null
  busyId: number | null
  runDocs: DocsRunner
  makeable: boolean
  hasDocs?: boolean
  children?: ReactNode
}) {
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)
  const [writing, setWriting] = useState(false)
  const [asking, setAsking] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [picked, setPicked] = useState('')

  const mine = busyId === job.id
  const locked = busyId !== null
  const shown = error || job.docs_error || ''
  const fallback = resumes.find((r) => r.id === defaultId)?.id ?? resumes.find((r) => r.is_default)?.id ?? resumes[0]?.id ?? ''
  const chosen = resumes.some((r) => r.id === picked) ? picked : fallback
  const startLabel = hasDocs ? 'Regenerate' : 'Make docs'

  async function open(what: 'resume' | 'cover_letter' | 'folder') {
    setError('')
    try {
      await openDoc(job.id, what)
    } catch (e) {
      setError(errorText(e))
    }
  }

  async function regenerate() {
    setError('')
    setWriting(true)
    setStale(false)
    const out = await runDocs(job.id, () => makeDocs(job.id, feedback.trim() || null))
    setWriting(false)
    setStale(out.stale)
    if (out.error) setError(out.error)
    else {
      setAsking(false)
      setFeedback('')
    }
  }

  async function asIs() {
    setError('')
    setStale(false)
    const out = await runDocs(job.id, () => applyAsIs(job.id, chosen))
    setStale(out.stale)
    if (out.error) setError(out.error)
  }

  return (
    <>
      {hasDocs && (
        <div className="row">
          <button type="button" onClick={() => void open('resume')}>
            Open resume
          </button>
          <button type="button" onClick={() => void open('cover_letter')}>
            Open cover letter
          </button>
          <button type="button" onClick={() => void open('folder')}>
            Open folder
          </button>
        </div>
      )}
      {job.docs_note && <p className="help">{job.docs_note}</p>}
      {children}
      {makeable && resumes.length > 0 && (
        <div className="row">
          <label>
            Use my resume as-is{' '}
            <select value={chosen} disabled={mine} onChange={(e) => setPicked(e.target.value)}>
              {resumes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                  {r.id === defaultId || r.is_default ? ' (default)' : ''}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="add" disabled={mine || !chosen} onClick={() => void asIs()}>
            Use
          </button>
        </div>
      )}
      {makeable && !asking && (
        <div className="row">
          <button type="button" className="add" disabled={locked} onClick={() => setAsking(true)}>
            {startLabel}
          </button>
        </div>
      )}
      {makeable && asking && (
        <div className="field">
          <div className="field-label">
            <label htmlFor={`feedback-${job.id}`}>What should change? (optional)</label>
          </div>
          <textarea
            id={`feedback-${job.id}`}
            rows={3}
            placeholder="For example: lean into healthcare work"
            value={feedback}
            disabled={mine}
            onChange={(e) => setFeedback(e.target.value)}
          />
          <div className="row">
            <button type="button" className="primary" disabled={locked} onClick={() => void regenerate()}>
              {startLabel}
            </button>
            <button
              type="button"
              disabled={mine}
              onClick={() => {
                setAsking(false)
                setFeedback('')
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {mine && writing && (
        <p className="help" role="status">Writing documents… this can take a minute.</p>
      )}
      {stale && !error && <p className="help">{STALE_NOTE}</p>}
      {shown && <div className="result bad">{shown}</div>}
    </>
  )
}
