import { useState } from 'react'
import { setStatus, type RelatedJob } from '../api.ts'
import { errorText } from '../pages/jobFormat.ts'
import JobLink from './JobLink.tsx'
import StatusBadge from './StatusBadge.tsx'

export interface RepeatJob {
  id: number
  status: string
  allowed_next: string[]
  duplicate_of?: RelatedJob | null
  looks_like?: RelatedJob | null
  also_seen_as?: { id: number; employer: string; title: string; status: string }[]
}

function Earlier({ job }: { job: RelatedJob }) {
  return (
    <>
      <JobLink id={job.id}>
        {job.employer} – {job.title}
      </JobLink>{' '}
      <StatusBadge status={job.status} />
      {job.decided && (
        <span className="help">
          {' '}
          {job.decided}
          {job.decided_date ? ` (${job.decided_date})` : ''}
        </span>
      )}
    </>
  )
}

// What this job has to do with others in the tracker: a duplicate of one, possibly a repeat of one you decided on
// before (with a one-click way to say so), or the original of some duplicates.
export default function RepeatBanner({ job, onChanged }: { job: RepeatJob; onChanged: () => void | Promise<void> }) {
  const [dismissed, setDismissed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const earlier = job.looks_like
  const showLooksLike = !!earlier && !dismissed && (job.status === 'New' || job.status === 'Ready')

  async function markDuplicate() {
    if (!earlier) return
    setBusy(true)
    setError('')
    try {
      await setStatus(job.id, { status: 'Duplicate', duplicate_of: earlier.id, date: null, note: null, skip_reason: null, skip_note: null })
      await onChanged()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const also = job.also_seen_as ?? []
  if (!job.duplicate_of && !showLooksLike && also.length === 0) return null
  return (
    <div className="repeat-banner">
      {job.duplicate_of && (
        <p>
          Duplicate of <Earlier job={job.duplicate_of} />
        </p>
      )}
      {showLooksLike && earlier && (
        <p>
          Looks like <Earlier job={earlier} />{' '}
          {job.allowed_next.includes('Duplicate') && (
            <button type="button" disabled={busy} onClick={() => void markDuplicate()}>
              Mark as duplicate
            </button>
          )}{' '}
          <button type="button" className="link" onClick={() => setDismissed(true)}>
            Not a duplicate
          </button>
        </p>
      )}
      {also.length > 0 && (
        <p>
          Also seen as:{' '}
          {also.map((a, i) => (
            <span key={a.id}>
              {i > 0 && ', '}
              <JobLink id={a.id}>
                {a.employer} – {a.title}
              </JobLink>{' '}
              <StatusBadge status={a.status} />
            </span>
          ))}
        </p>
      )}
      {error && <div className="result bad">{error}</div>}
    </div>
  )
}
