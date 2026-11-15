import { useEffect, useRef, useState, type FormEvent } from 'react'
import { addFollowUp, fmtDate, listContacts, listJobs, type FollowUpRow } from '../api.ts'
import FollowUpList from '../components/FollowUpList.tsx'
import { daysFromTodayISO, todayISO } from '../dates.ts'
import { errorText } from './jobFormat.ts'

const FOLLOWUP_TYPES = ['Application check-in', 'Recruiter outreach', 'Thank-you note', 'Referral request', 'Other']

interface Target {
  kind: 'job' | 'contact'
  id: number
  label: string
}

function TargetPicker({ idPrefix, target, onPick }: { idPrefix: string; target: Target | null; onPick: (t: Target | null) => void }) {
  const [q, setQ] = useState('')
  const [options, setOptions] = useState<Target[]>([])
  const [error, setError] = useState('')
  const latest = useRef(0)

  useEffect(() => {
    const id = ++latest.current
    const text = q.trim()
    if (!text) return
    Promise.all([listJobs({ q: text, limit: 8 }), listContacts({ q: text })])
      .then(([jobs, contacts]) => {
        if (id !== latest.current) return
        setOptions([
          ...jobs.rows.map((j) => ({ kind: 'job' as const, id: j.id, label: `${j.employer} — ${j.title}` })),
          ...contacts.slice(0, 8).map((c) => ({ kind: 'contact' as const, id: c.id, label: c.name || 'Unnamed contact' })),
        ])
        setError('')
      })
      .catch((e: unknown) => {
        if (id !== latest.current) return
        setError(errorText(e))
      })
  }, [q])

  const searching = q.trim() !== ''
  if (target) {
    return (
      <div className="field">
        <span>For</span>
        <div className="row">
          <span>
            {target.kind === 'job' ? 'Job' : 'Contact'}: {target.label}
          </span>
          <button type="button" onClick={() => onPick(null)}>
            Change
          </button>
        </div>
      </div>
    )
  }
  return (
    <div className="field">
      <label htmlFor={`${idPrefix}-for`}>For (search jobs and contacts)</label>
      <input id={`${idPrefix}-for`} type="search" value={q} onChange={(e) => {
          setQ(e.target.value)
          if (!e.target.value.trim()) {
            setOptions([])
            setError('')
          }
        }}
      />
      {searching && error && <div className="result bad">{error}</div>}
      {searching && !error && options.length === 0 && <p className="muted">No matching jobs or contacts.</p>}
      {searching && options.length > 0 && (
        <ul className="followups">
          {options.map((o) => (
            <li key={`${o.kind}-${o.id}`} className="followup compact">
              <button type="button" className="link" onClick={() => onPick(o)}>
                {o.kind === 'job' ? 'Job' : 'Contact'}: {o.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function AddFollowUpForm({
  jobId,
  contactId = null,
  pickTarget = false,
  idPrefix,
  onAdded,
  onCancel,
}: {
  jobId: number | null
  contactId?: number | null
  pickTarget?: boolean
  idPrefix: string
  onAdded: () => void | Promise<void>
  onCancel: () => void
}) {
  const [type, setType] = useState(FOLLOWUP_TYPES[0])
  const [due, setDue] = useState(daysFromTodayISO(7))
  const [note, setNote] = useState('')
  const [target, setTarget] = useState<Target | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const forJob = pickTarget ? (target?.kind === 'job' ? target.id : null) : jobId
  const forContact = pickTarget ? (target?.kind === 'contact' ? target.id : null) : contactId

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await addFollowUp({ type, due_date: due, job_id: forJob, contact_id: forContact, note: note.trim() || null })
      await onAdded()
      onCancel()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="inline-form" onSubmit={(e) => void submit(e)}>
      {pickTarget && <TargetPicker idPrefix={idPrefix} target={target} onPick={setTarget} />}
      <div className="field">
        <label htmlFor={`${idPrefix}-type`}>Type</label>
        <select id={`${idPrefix}-type`} value={type} onChange={(e) => setType(e.target.value)}>
          {FOLLOWUP_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-due`}>Due date</label>
        <input id={`${idPrefix}-due`} type="date" value={due} min={todayISO()} onChange={(e) => setDue(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-note`}>Note (optional)</label>
        <input id={`${idPrefix}-note`} type="text" value={note} onChange={(e) => setNote(e.target.value)} />
      </div>
      {error && <div className="result bad">{error}</div>}
      <div className="row">
        <button type="submit" className="add" disabled={busy || !due || (pickTarget && !target)}>
          Add a follow-up
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

export default function JobFollowUps({
  jobId,
  rows,
  onChanged,
}: {
  jobId: number
  rows: FollowUpRow[]
  onChanged: () => void | Promise<void>
}) {
  const [adding, setAdding] = useState(false)
  const active = rows.filter((r) => r.status === 'Open' || r.status === 'Snoozed')
  const past = rows.filter((r) => r.status !== 'Open' && r.status !== 'Snoozed')

  return (
    <section className="card" aria-labelledby="job-followups">
      <h2 id="job-followups">Follow-ups</h2>
      {active.length === 0 && <p className="muted">No open follow-ups.</p>}
      {active.length > 0 && <FollowUpList rows={active} onChanged={onChanged} />}
      {past.length > 0 && (
        <details className="result-list">
          <summary>Finished follow-ups ({past.length})</summary>
          <ul>
            {past.map((r) => (
              <li key={r.id}>
                {r.type} · {r.status}
                {r.completed_date ? ` ${fmtDate(r.completed_date)}` : ''}
                {r.outcome_note ? ` · ${r.outcome_note}` : ''}
              </li>
            ))}
          </ul>
        </details>
      )}
      {!adding && (
        <div className="row">
          <button type="button" className="add" onClick={() => setAdding(true)}>
            Add a follow-up
          </button>
        </div>
      )}
      {adding && (
        <AddFollowUpForm jobId={jobId} idPrefix="job-fu" onAdded={onChanged} onCancel={() => setAdding(false)} />
      )}
    </section>
  )
}
