import { useState, type FormEvent } from 'react'
import { fmtDate, listFollowUps, reopenJob, setStatus } from '../api.ts'
import { todayISO } from '../dates.ts'
import { errorText } from '../pages/jobFormat.ts'

export const LABELS: Record<string, string> = {
  Applied: 'Mark applied',
  Interviewing: 'Got an interview',
  Offer: 'Got an offer',
  Accepted: 'I accepted',
  Rejected: 'Rejected',
  Withdrawn: 'I withdrew',
  Unavailable: 'Unavailable',
  Skipped: 'Skip',
  Reopen: 'Reopen',
}

const PRIMARY = ['Applied', 'Offer']

export interface StatusJob {
  id: number
  status: string
  allowed_next: string[]
}

export default function StatusActions({
  job,
  skipReasons,
  onChanged,
}: {
  job: StatusJob
  skipReasons: string[]
  onChanged: () => void | Promise<void>
}) {
  const [action, setAction] = useState<string | null>(null)
  const [date, setDate] = useState(todayISO())
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  function begin(next: string) {
    setAction(next)
    setDate(todayISO())
    setNote('')
    setReason('')
    setError('')
    setInfo('')
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!action) return
    setBusy(true)
    setError('')
    try {
      const text = note.trim() || null
      let message = ''
      if (action === 'Reopen') {
        await reopenJob(job.id, text)
      } else {
        const skipping = action === 'Skipped'
        const result = await setStatus(job.id, {
          status: action,
          date: date || null,
          note: skipping ? null : text,
          skip_reason: skipping ? reason : null,
          skip_note: skipping ? text : null,
        })
        if (action === 'Applied' && result.follow_up_id !== null) {
          try {
            const due = (await listFollowUps({ job_id: job.id })).find((f) => f.id === result.follow_up_id)?.due_date
            if (due) message = `Marked applied. A check-in is set for ${fmtDate(due)}.`
          } catch {
            /* the note is a courtesy; the change itself worked */
          }
        }
      }
      setAction(null)
      setInfo(message)
      await onChanged()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const id = `status-${job.id}`
  const skipping = action === 'Skipped'
  const canSubmit = !busy && (!skipping || reason !== '')

  return (
    <div className="status-actions">
      {job.allowed_next.length > 0 && (
        <div className="row">
          {job.allowed_next.map((a) => (
            <button
              key={a}
              type="button"
              className={PRIMARY.includes(a) ? 'primary' : undefined}
              disabled={busy}
              aria-expanded={action === a}
              onClick={() => begin(a)}
            >
              {LABELS[a] ?? a}
            </button>
          ))}
        </div>
      )}
      {action && (
        <form className="inline-form" onSubmit={(e) => void submit(e)}>
          {skipping && (
            <div className="field">
              <label htmlFor={`${id}-reason`}>Why are you skipping this job?</label>
              <select id={`${id}-reason`} value={reason} onChange={(e) => setReason(e.target.value)}>
                <option value="" disabled>
                  Choose a reason
                </option>
                {skipReasons.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
          )}
          {action !== 'Reopen' && (
            <div className="field">
              <label htmlFor={`${id}-date`}>Date</label>
              <input id={`${id}-date`} type="date" value={date} max={todayISO()} onChange={(e) => setDate(e.target.value)} />
            </div>
          )}
          <div className="field">
            <label htmlFor={`${id}-note`}>Note (optional)</label>
            <input id={`${id}-note`} type="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="row">
            <button type="submit" className="primary" disabled={!canSubmit}>
              {LABELS[action] ?? action}
            </button>
            <button type="button" disabled={busy} onClick={() => setAction(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {info && <p className="help">{info}</p>}
      {error && <div className="result bad">{error}</div>}
    </div>
  )
}
