import { useEffect, useRef, useState } from 'react'
import { fmtDate, getDashboard, type DashboardData } from '../api.ts'
import { Bars, Columns } from '../components/Bars.tsx'
import FollowUpList from '../components/FollowUpList.tsx'
import { useNav } from '../nav.tsx'
import { errorText } from './jobFormat.ts'

const WEEKS = [4, 8, 12, 26, 52]
const STAGES = [
  ['found', 'Found'],
  ['matched', 'Matched'],
  ['applied', 'Applied'],
  ['interviewing', 'Interviewing'],
  ['offer', 'Offer'],
] as const

// The funnel is not guaranteed monotonic (a job marked applied by hand was never matched),
// so a conversion is shown only when the previous stage is above zero and the value does not exceed it.
function conversion(prev: number, value: number, prevLabel: string): string | undefined {
  if (prev > 0 && value <= prev) return `(${Math.round((value / prev) * 100)}% of ${prevLabel})`
  return undefined
}

export default function Dashboard() {
  const { go } = useNav()
  const [weeks, setWeeks] = useState(12)
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const latest = useRef(0)

  useEffect(() => {
    const id = ++latest.current
    getDashboard(weeks)
      .then((d) => {
        if (id !== latest.current) return
        setData(d)
        setError('')
      })
      .catch((e: unknown) => {
        if (id !== latest.current) return
        setError(errorText(e))
      })
  }, [weeks, tick])

  const refresh = () => setTick((t) => t + 1)
  const empty = data !== null && data.funnel.found === 0 && data.funnel.applied === 0

  return (
    <div>
      <h1>Dashboard</h1>
      <div className="row">
        <label htmlFor="dash-weeks">Weeks</label>
        <select id="dash-weeks" value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
          {WEEKS.map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
      </div>
      {error && <div className="result bad">{error}</div>}
      {data === null && !error && <p className="loading">Loading…</p>}
      {data !== null && empty && <p className="muted">Run a search or add a job to see numbers here.</p>}
      {data !== null && !empty && (
        <div className="dash-grid">
          <section className="card" aria-labelledby="dash-funnel">
            <h2 id="dash-funnel">Funnel</h2>
            <Bars
              items={STAGES.map(([key, label], n) => ({
                label,
                value: data.funnel[key],
                caption:
                  n === 0
                    ? undefined
                    : conversion(data.funnel[STAGES[n - 1][0]], data.funnel[key], STAGES[n - 1][1].toLowerCase()),
              }))}
            />
          </section>
          <section className="card" aria-labelledby="dash-weekly">
            <h2 id="dash-weekly">Applications per week</h2>
            <Columns items={data.weekly.map((w) => ({ label: fmtDate(w.week_start), value: w.applied }))} />
          </section>
          <section className="card" aria-labelledby="dash-rate">
            <h2 id="dash-rate">Response rate</h2>
            {data.response.rate === null ? (
              <p className="muted">Nothing applied yet.</p>
            ) : (
              <>
                <p className="big-number">{Math.round(data.response.rate * 100)}%</p>
                <p className="muted">
                  {data.response.responded} of {data.response.applied} applications heard back
                </p>
              </>
            )}
          </section>
          <section className="card" aria-labelledby="dash-skips">
            <h2 id="dash-skips">Why jobs were skipped</h2>
            {data.skip_reasons.length === 0 ? (
              <p className="muted">No skipped jobs yet.</p>
            ) : (
              <Bars items={data.skip_reasons.map((r) => ({ label: r.reason, value: r.count }))} colour="var(--bad)" />
            )}
          </section>
          <section className="card" aria-labelledby="dash-sources">
            <h2 id="dash-sources">Where matches come from</h2>
            {data.sources.length === 0 ? (
              <p className="muted">No matches yet.</p>
            ) : (
              <Bars items={data.sources.map((s) => ({ label: s.source, value: s.count }))} />
            )}
          </section>
          <section className="card" aria-labelledby="dash-followups">
            <h2 id="dash-followups">Follow-ups</h2>
            {data.followups.overdue.length === 0 && data.followups.this_week.length === 0 ? (
              <p className="muted">Nothing overdue or due this week.</p>
            ) : (
              <>
                {data.followups.overdue.length > 0 && (
                  <>
                    <h3>
                      Overdue (<span className="overdue">{data.followups.overdue.length}</span>)
                    </h3>
                    <FollowUpList rows={data.followups.overdue} onChanged={refresh} compact />
                  </>
                )}
                {data.followups.this_week.length > 0 && (
                  <>
                    <h3>Due this week ({data.followups.this_week.length})</h3>
                    <FollowUpList rows={data.followups.this_week} onChanged={refresh} compact />
                  </>
                )}
              </>
            )}
            <div className="row">
              <button type="button" className="link" onClick={() => go('Follow-ups')}>
                See all
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
