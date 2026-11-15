import { useEffect, useRef, useState } from 'react'
import { fmtDate, listFollowUps, type FollowUpRow } from '../api.ts'
import FollowUpList from '../components/FollowUpList.tsx'
import { useNav } from '../nav.tsx'
import { AddFollowUpForm } from './JobFollowUps.tsx'
import { errorText } from './jobFormat.ts'

function Section({
  title,
  rows,
  onChanged,
  bad = false,
}: {
  title: string
  rows: FollowUpRow[]
  onChanged: () => void | Promise<void>
  bad?: boolean
}) {
  const id = `fu-sec-${title.toLowerCase().replace(/\s+/g, '-')}`
  return (
    <section className="card" aria-labelledby={id}>
      <h2 id={id}>
        {title} (<span className={bad && rows.length > 0 ? 'overdue' : undefined}>{rows.length}</span>)
      </h2>
      {rows.length === 0 ? <p className="muted">None.</p> : <FollowUpList rows={rows} onChanged={onChanged} />}
    </section>
  )
}

function DoneItem({ row }: { row: FollowUpRow }) {
  const { openJob } = useNav()
  const jobId = row.job_id
  return (
    <li>
      {row.type} · {row.status}
      {row.completed_date ? ` ${fmtDate(row.completed_date)}` : ''}
      {jobId !== null ? (
        <>
          {' · '}
          <button type="button" className="link" onClick={() => openJob(jobId)}>
            {row.employer ?? 'Job'} — {row.job_title ?? ''}
          </button>
        </>
      ) : (
        row.contact_name && ` · ${row.contact_name}`
      )}
      {row.outcome_note ? ` · ${row.outcome_note}` : ''}
    </li>
  )
}

export default function FollowUps() {
  const [rows, setRows] = useState<FollowUpRow[] | null>(null)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const [tick, setTick] = useState(0)
  const latest = useRef(0)

  useEffect(() => {
    const id = ++latest.current
    listFollowUps()
      .then((r) => {
        if (id !== latest.current) return
        setRows(r)
        setError('')
      })
      .catch((e: unknown) => {
        if (id !== latest.current) return
        setError(errorText(e))
      })
  }, [tick])

  const refresh = () => setTick((t) => t + 1)
  const of = (b: FollowUpRow['bucket']) => (rows ?? []).filter((r) => r.bucket === b)
  const done = of('done')

  return (
    <div>
      <h1>Follow-ups</h1>
      {error && <div className="result bad">{error}</div>}
      {rows === null && !error && <p className="loading">Loading…</p>}
      {!adding && (
        <div className="row">
          <button type="button" className="add" onClick={() => setAdding(true)}>
            Add a follow-up
          </button>
        </div>
      )}
      {adding && (
        <section className="card">
          <AddFollowUpForm jobId={null} pickTarget idPrefix="fu-page" onAdded={refresh} onCancel={() => setAdding(false)} />
        </section>
      )}
      {rows !== null && rows.length === 0 && (
        <p className="muted">
          Nothing to follow up on. Follow-ups appear here when you mark a job applied or add one yourself.
        </p>
      )}
      {rows !== null && rows.length > 0 && (
        <>
          <Section title="Overdue" rows={of('overdue')} onChanged={refresh} bad />
          <Section title="Due today" rows={of('today')} onChanged={refresh} />
          <Section title="Upcoming" rows={of('upcoming')} onChanged={refresh} />
          <section className="card" aria-labelledby="fu-sec-done">
            <details className="result-list">
              <summary id="fu-sec-done">Done ({done.length})</summary>
              {done.length === 0 ? (
                <p className="muted">None.</p>
              ) : (
                <ul>
                  {done.map((r) => (
                    <DoneItem key={r.id} row={r} />
                  ))}
                </ul>
              )}
            </details>
          </section>
        </>
      )}
    </div>
  )
}
