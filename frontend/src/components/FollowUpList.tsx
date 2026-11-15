import { useState, type FormEvent } from 'react'
import { fmtDate, followUpAction, type FollowUpAction, type FollowUpRow } from '../api.ts'
import { todayISO, tomorrowISO } from '../dates.ts'
import { useNav } from '../nav.tsx'
import { errorText } from '../pages/jobFormat.ts'

const FORMS: Record<string, string> = { done: 'Done', snooze: 'Snooze', reschedule: 'Reschedule' }

function Row({ row, onChanged, compact }: { row: FollowUpRow; onChanged: () => void | Promise<void>; compact: boolean }) {
  const { openJob } = useNav()
  const [form, setForm] = useState<FollowUpAction | null>(null)
  const [date, setDate] = useState('')
  const [outcome, setOutcome] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function begin(next: FollowUpAction) {
    setForm(next)
    setDate(next === 'snooze' ? tomorrowISO() : row.due_date >= todayISO() ? row.due_date : todayISO())
    setOutcome('')
    setError('')
  }

  async function run(action: FollowUpAction, body: Parameters<typeof followUpAction>[2] = {}) {
    setBusy(true)
    setError('')
    try {
      await followUpAction(row.id, action, body)
      setForm(null)
      await onChanged()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (form === 'done') void run('done', { outcome_note: outcome.trim() || null })
    else if (form === 'snooze') void run('snooze', { until: date })
    else if (form === 'reschedule') void run('reschedule', { due_date: date })
  }

  const jobId = row.job_id
  const what = jobId !== null ? `${row.employer ?? 'Job'} — ${row.job_title ?? ''}` : row.contact_name
  const id = `fu-${row.id}`

  return (
    <li className={compact ? 'followup compact' : 'followup'}>
      <div>
        <strong>{row.type}</strong> · due {fmtDate(row.due_date)}
        {row.bucket === 'overdue' && <span className="overdue"> (overdue)</span>}
        {what && (
          <>
            {' · '}
            {jobId !== null ? (
              <button type="button" className="link" onClick={() => openJob(jobId)}>
                {what}
              </button>
            ) : (
              what
            )}
          </>
        )}
      </div>
      {row.note && <div className="help">{row.note}</div>}
      <div className="row">
        <button type="button" className="add" disabled={busy} onClick={() => begin('done')}>
          Done
        </button>
        <button type="button" disabled={busy} onClick={() => begin('snooze')}>
          Snooze
        </button>
        <button type="button" disabled={busy} onClick={() => begin('reschedule')}>
          Reschedule
        </button>
        <button type="button" className="danger" disabled={busy} onClick={() => void run('cancel')}>
          Cancel
        </button>
      </div>
      {form && (
        <form className="inline-form" onSubmit={submit}>
          {form === 'done' ? (
            <div className="field">
              <label htmlFor={`${id}-outcome`}>What happened? (optional)</label>
              <input id={`${id}-outcome`} type="text" value={outcome} onChange={(e) => setOutcome(e.target.value)} />
            </div>
          ) : (
            <div className="field">
              <label htmlFor={`${id}-date`}>{form === 'snooze' ? 'Snooze until' : 'New date'}</label>
              <input id={`${id}-date`} type="date" value={date} min={todayISO()} onChange={(e) => setDate(e.target.value)} />
            </div>
          )}
          <div className="row">
            <button type="submit" className="primary" disabled={busy || (form !== 'done' && !date)}>
              {FORMS[form]}
            </button>
            <button type="button" disabled={busy} onClick={() => setForm(null)}>
              Close
            </button>
          </div>
        </form>
      )}
      {error && <div className="result bad">{error}</div>}
    </li>
  )
}

export default function FollowUpList({
  rows,
  onChanged,
  compact = false,
}: {
  rows: FollowUpRow[]
  onChanged: () => void | Promise<void>
  compact?: boolean
}) {
  return (
    <ul className="followups">
      {rows.map((r) => (
        <Row key={r.id} row={r} onChanged={onChanged} compact={compact} />
      ))}
    </ul>
  )
}
