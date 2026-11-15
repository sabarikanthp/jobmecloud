import { useState, type FormEvent } from 'react'
import { addInterview, deleteInterview, saveInterview, type InterviewRow } from '../api.ts'
import { fmtInstant, toLocalInput } from '../dates.ts'
import { errorText } from './jobFormat.ts'

const STAGES = ['Recruiter screen', 'Hiring manager', 'Panel', 'Final', 'Other']

function InterviewForm({
  jobId,
  interview,
  onSaved,
  onCancel,
}: {
  jobId: number
  interview: InterviewRow | null
  onSaved: (statusChanged: boolean) => void | Promise<void>
  onCancel: () => void
}) {
  const id = `interview-${interview?.id ?? 'new'}`
  const [when, setWhen] = useState(toLocalInput(interview?.date ?? null))
  const [stage, setStage] = useState(interview?.stage ?? '')
  const [notes, setNotes] = useState(interview?.notes ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = { date: when || null, stage: stage.trim() || null, notes: notes.trim() || null }
      const res = interview ? await saveInterview(interview.id, body) : await addInterview(jobId, body)
      await onSaved(res.status_changed)
      onCancel()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="inline-form" onSubmit={(e) => void submit(e)}>
      <div className="field">
        <label htmlFor={`${id}-when`}>Date and time</label>
        <input id={`${id}-when`} type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-stage`}>Stage</label>
        <input id={`${id}-stage`} type="text" list={`${id}-stages`} value={stage} onChange={(e) => setStage(e.target.value)} />
        <datalist id={`${id}-stages`}>
          {STAGES.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </div>
      <div className="field">
        <label htmlFor={`${id}-notes`}>Notes</label>
        <textarea id={`${id}-notes`} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      {error && <div className="result bad">{error}</div>}
      <div className="row">
        <button type="submit" className={interview ? 'primary' : 'add'} disabled={busy}>
          {interview ? 'Save interview' : 'Add an interview'}
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function InterviewItem({ jobId, row, onChanged }: { jobId: number; row: InterviewRow; onChanged: () => void | Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function remove() {
    setBusy(true)
    setError('')
    try {
      await deleteInterview(row.id)
      await onChanged()
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
      setConfirming(false)
    }
  }

  return (
    <li className="job-item">
      <div>
        <strong>{fmtInstant(row.date) || 'No date set'}</strong>
        {row.stage ? ` · ${row.stage}` : ''}
      </div>
      {row.notes && <div className="help">{row.notes}</div>}
      <div className="row">
        <button type="button" disabled={busy} onClick={() => setEditing((v) => !v)}>
          Edit
        </button>
        {!confirming && (
          <button type="button" className="danger" disabled={busy} onClick={() => setConfirming(true)}>
            Delete
          </button>
        )}
        {confirming && (
          <>
            <span>Delete?</span>
            <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>
              Yes
            </button>
            <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
              No
            </button>
          </>
        )}
      </div>
      {editing && (
        <InterviewForm jobId={jobId} interview={row} onSaved={onChanged} onCancel={() => setEditing(false)} />
      )}
      {error && <div className="result bad">{error}</div>}
    </li>
  )
}

export default function JobInterviews({
  jobId,
  rows,
  onChanged,
}: {
  jobId: number
  rows: InterviewRow[]
  onChanged: () => void | Promise<void>
}) {
  const [adding, setAdding] = useState(false)
  const [info, setInfo] = useState('')

  return (
    <section className="card" aria-labelledby="job-interviews">
      <h2 id="job-interviews">Interviews</h2>
      {rows.length === 0 && <p className="muted">No interviews yet.</p>}
      {rows.length > 0 && (
        <ul className="job-items">
          {rows.map((r) => (
            <InterviewItem key={r.id} jobId={jobId} row={r} onChanged={onChanged} />
          ))}
        </ul>
      )}
      {info && <p className="help">{info}</p>}
      {!adding && (
        <div className="row">
          <button type="button" className="add" onClick={() => setAdding(true)}>
            Add an interview
          </button>
        </div>
      )}
      {adding && (
        <InterviewForm
          jobId={jobId}
          interview={null}
          onSaved={async (changed) => {
            setInfo(changed ? 'This job is now Interviewing.' : '')
            await onChanged()
          }}
          onCancel={() => setAdding(false)}
        />
      )}
    </section>
  )
}
