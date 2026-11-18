import { useState } from 'react'
import { reopenJob, setStatus } from '../api.ts'
import { todayISO } from '../dates.ts'
import { errorText } from '../pages/jobFormat.ts'
import DuplicatePicker from './DuplicatePicker.tsx'
import StatusBadge from './StatusBadge.tsx'
import { LABELS, type StatusJob } from './StatusActions.tsx'

// The status of a job in a list, with a dropdown to change it without opening the job. A move that needs nothing
// else is made as soon as it is chosen, dated today; skipping asks for a reason first. The job's own page still has
// the full form for a different date or a note.
export default function RowStatus({
  job,
  skipReasons,
  onChanged,
}: {
  job: StatusJob
  skipReasons: string[]
  onChanged: () => void | Promise<void>
}) {
  const [asking, setAsking] = useState(false) // waiting for a reason to skip
  const [picking, setPicking] = useState(false) // waiting for the job this one repeats
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const moves = job.allowed_next ?? [] // an older server may not send it: then there is simply no dropdown

  async function apply(action: string, reason?: string, duplicateOf?: number) {
    setBusy(true)
    setError('')
    try {
      if (action === 'Reopen') {
        await reopenJob(job.id, null)
      } else {
        await setStatus(job.id, {
          status: action,
          date: todayISO(),
          note: null,
          skip_reason: action === 'Skipped' ? (reason ?? null) : null,
          skip_note: null,
          ...(duplicateOf !== undefined ? { duplicate_of: duplicateOf } : {}),
        })
      }
      setAsking(false)
      setPicking(false)
      await onChanged()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  function chosen(value: string) {
    if (!value) return
    setError('')
    if (value === 'Skipped') setAsking(true)
    else if (value === 'Duplicate') setPicking(true)
    else void apply(value)
  }

  return (
    <div className="row-status">
      <StatusBadge status={job.status} />
      {moves.length > 0 && (
        <select aria-label="Change status" value="" disabled={busy || asking || picking} onChange={(e) => chosen(e.target.value)}>
          <option value="">Change…</option>
          {moves.map((a) => (
            <option key={a} value={a}>
              {LABELS[a] ?? a}
            </option>
          ))}
        </select>
      )}
      {asking && (
        <span className="row-reason">
          <select
            aria-label="Reason for skipping"
            value=""
            disabled={busy}
            onChange={(e) => e.target.value && void apply('Skipped', e.target.value)}
          >
            <option value="" disabled>
              Why skip?
            </option>
            {skipReasons.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button type="button" className="link" disabled={busy} onClick={() => setAsking(false)}>
            Cancel
          </button>
        </span>
      )}
      {picking && (
        <DuplicatePicker
          jobId={job.id}
          busy={busy}
          onPick={(id) => apply('Duplicate', undefined, id)}
          onCancel={() => setPicking(false)}
        />
      )}
      {error && <span className="row-error">{error}</span>}
    </div>
  )
}
