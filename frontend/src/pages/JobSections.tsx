import { useState, type FormEvent } from 'react'
import { fmtDate, patchJob, type JobDetail } from '../api.ts'
import { fmtLogged, todayISO } from '../dates.ts'
import { errorText } from './jobFormat.ts'
import { describe, noteFor } from './jobTimeline.ts'

export function KeyDates({ job, onChanged }: { job: JobDetail; onChanged: () => void | Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [applied, setApplied] = useState('')
  const [response, setResponse] = useState('')
  const [outcome, setOutcome] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function begin() {
    setApplied(job.applied_date ?? '')
    setResponse(job.first_response_date ?? '')
    setOutcome(job.outcome_date ?? '')
    setError('')
    setEditing(true)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      // Only the dates that changed are sent; an emptied box clears that date.
      const body: Parameters<typeof patchJob>[1] = {}
      if (applied !== (job.applied_date ?? '')) body.applied_date = applied || null
      if (response !== (job.first_response_date ?? '')) body.first_response_date = response || null
      if (outcome !== (job.outcome_date ?? '')) body.outcome_date = outcome || null
      if (Object.keys(body).length > 0) {
        await patchJob(job.id, body)
        await onChanged()
      }
      setEditing(false)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const none = 'Not yet'
  return (
    <div>
      <dl className="key-dates">
        <div>
          <dt>Found</dt>
          <dd>{fmtDate(job.first_seen_date) || none}</dd>
        </div>
        <div>
          <dt>Applied</dt>
          <dd>{fmtDate(job.applied_date) || none}</dd>
        </div>
        <div>
          <dt>First response</dt>
          <dd>{fmtDate(job.first_response_date) || none}</dd>
        </div>
        <div>
          <dt>Outcome</dt>
          <dd>{fmtDate(job.outcome_date) || none}</dd>
        </div>
      </dl>
      {!editing && (
        <div className="row">
          <button type="button" onClick={begin}>
            Edit dates
          </button>
        </div>
      )}
      {editing && (
        <form className="inline-form" onSubmit={(e) => void submit(e)}>
          <div className="field">
            <label htmlFor="date-applied">Applied</label>
            <input id="date-applied" type="date" value={applied} max={todayISO()} onChange={(e) => setApplied(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="date-response">First response</label>
            <input id="date-response" type="date" value={response} max={todayISO()} onChange={(e) => setResponse(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="date-outcome">Outcome</label>
            <input id="date-outcome" type="date" value={outcome} max={todayISO()} onChange={(e) => setOutcome(e.target.value)} />
          </div>
          <p className="help">Clear a box to remove that date.</p>
          <div className="row">
            <button type="submit" className="primary" disabled={busy}>
              Save dates
            </button>
            <button type="button" disabled={busy} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && <div className="result bad">{error}</div>}
    </div>
  )
}

export function Notes({ job, onChanged }: { job: JobDetail; onChanged: () => void | Promise<void> }) {
  const [text, setText] = useState(job.notes ?? '')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function save() {
    setBusy(true)
    setError('')
    try {
      await patchJob(job.id, { notes: text.trim() || null })
      await onChanged()
      setSaved(true)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" aria-labelledby="job-notes">
      <h2 id="job-notes">Notes</h2>
      <label htmlFor="job-notes-text" className="visually-hidden">
        Notes
      </label>
      <textarea
        id="job-notes-text"
        rows={5}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setSaved(false)
        }}
      />
      <div className="row">
        <button type="button" className="primary" disabled={busy} onClick={() => void save()}>
          Save notes
        </button>
        {saved && <span className="help" role="status">Saved</span>}
      </div>
      {error && <div className="result bad">{error}</div>}
    </section>
  )
}

export function Timeline({ job }: { job: JobDetail }) {
  const rows = [...job.timeline].sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
  return (
    <section className="card" aria-labelledby="job-timeline">
      <h2 id="job-timeline">Timeline</h2>
      {rows.length === 0 && <p className="muted">Nothing has happened with this job yet.</p>}
      {rows.length > 0 && (
        <ul className="timeline">
          {rows.map((e, i) => (
            <li key={`${e.at}-${i}`}>
              <span className="timeline-date">{fmtLogged(e.at, fmtDate)}</span> {describe(e)}
              {noteFor(e) && <span className="help">{noteFor(e)}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
