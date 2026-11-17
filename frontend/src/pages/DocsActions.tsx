import { useState, type ReactNode } from 'react'
import { makeDocs, openDoc, useAsIs as applyAsIs, type ResumeEntry } from '../api.ts'
import { authEnabled } from '../auth.ts'
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
  const [source, setSource] = useState('') // the resume to start from when regenerating; empty means the default
  const [done, setDone] = useState('') // what just happened, in plain words

  const mine = busyId === job.id
  const locked = busyId !== null
  const shown = error || job.docs_error || ''
  const fallback = resumes.find((r) => r.id === defaultId)?.id ?? resumes.find((r) => r.is_default)?.id ?? resumes[0]?.id ?? ''
  const chosen = resumes.some((r) => r.id === picked) ? picked : fallback
  const startLabel = hasDocs ? 'Regenerate' : 'Make docs'
  const startFrom = resumes.some((r) => r.id === source) ? source : fallback

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
    setDone('')
    setWriting(true)
    setStale(false)
    const updating = hasDocs // by the time the work finishes the page will say the files exist
    const resumeId = startFrom && startFrom !== fallback ? startFrom : null
    const out = await runDocs(job.id, () => makeDocs(job.id, feedback.trim() || null, resumeId))
    setWriting(false)
    setStale(out.stale)
    if (out.error) setError(out.error)
    else {
      setAsking(false)
      setFeedback('')
      setDone(updating ? 'Resume and cover letter updated.' : 'New resume and cover letter created.')
    }
  }

  async function asIs() {
    setError('')
    setDone('')
    setStale(false)
    const out = await runDocs(job.id, () => applyAsIs(job.id, chosen))
    setStale(out.stale)
    if (out.error) setError(out.error)
    else setDone(`Now using ${resumes.find((r) => r.id === chosen)?.name ?? 'that resume'} as-is.`)
  }

  return (
    <>
      {hasDocs && (
        <div className="row">
          <button type="button" onClick={() => void open('resume')}>
            {authEnabled() ? 'Download resume' : 'Open resume'}
          </button>
          <button type="button" onClick={() => void open('cover_letter')}>
            {authEnabled() ? 'Download cover letter' : 'Open cover letter'}
          </button>
          {!authEnabled() && (
            <button type="button" onClick={() => void open('folder')}>
              Open folder
            </button>
          )}
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
          {resumes.length > 1 && (
            <label>
              Start from{' '}
              <select aria-label="Start from" value={startFrom} disabled={mine} onChange={(e) => setSource(e.target.value)}>
                {resumes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                    {r.id === defaultId || r.is_default ? ' (default)' : ''}
                  </option>
                ))}
              </select>
            </label>
          )}
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
      {done && !error && <p className="result ok" role="status">{done}</p>}
      {stale && !error && <p className="help">{STALE_NOTE}</p>}
      {shown && <div className="result bad">{shown}</div>}
    </>
  )
}
