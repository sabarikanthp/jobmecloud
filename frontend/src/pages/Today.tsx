import { useCallback, useEffect, useState } from 'react'
import {
  getInbound,
  getLatestRun,
  getRunJobs,
  getSettings,
  listFollowUps,
  listResumes,
  startRun,
  type FollowUpRow,
  type InboundEmailInfo,
  type ResumeList,
  type RunInfo,
  type RunJobRow,
} from '../api.ts'
import { fmtInstant, localISO, todayISO } from '../dates.ts'
import { inboundNoticeText, lastRunText, staleRunText } from './runLabels.ts'
import FollowUpList from '../components/FollowUpList.tsx'
import RepeatBanner from '../components/RepeatBanner.tsx'
import StatusActions from '../components/StatusActions.tsx'
import StatusBadge from '../components/StatusBadge.tsx'
import Tip from '../components/Tip.tsx'
import { ApplyLink, Chips } from './JobParts.tsx'
import MakeDocsButton from './MakeDocsButton.tsx'
import ReadyCard from './ReadyCard.tsx'
import { canMakeDocs, errorText, formatPay, matchText } from './jobFormat.ts'
import type { DocsRunner } from './docsTypes.ts'

function outcomeLabel(row: RunJobRow): string {
  switch (row.outcome) {
    case 'new':
      return 'New'
    case 'duplicate':
      return 'Seen before'
    case 'repeat':
      return 'Repeat of an earlier job'
    case 'excluded': {
      const rules = Array.isArray(row.job.hard_rules) ? row.job.hard_rules : []
      return `Excluded: ${rules
        .filter((r) => !r.passed)
        .map((r) => r.rule)
        .join(', ')}`
    }
    case 'matched':
      return 'Match'
    case 'prepared':
      return 'Documents ready'
    case 'closed':
      return 'Closed'
    default:
      return row.outcome
  }
}

// Why a row landed where it did, shown under it in "Everything this run".
function outcomeReason(row: RunJobRow): string {
  const { job } = row
  if (row.outcome === 'closed') return 'The posting is no longer open.'
  if (row.outcome === 'duplicate') return 'JobMe already had this job from an earlier run.'
  if (row.outcome === 'repeat') return 'The same job as one already in your tracker, so it was not scored. Reopen it if that is wrong.'
  if (job.reasons) return job.reasons
  if (job.match_score == null && job.flags.length > 0) return `Not scored: ${job.flags.join('; ')}.`
  return ''
}

// A timestamp from the API as a Date, treating one without a zone as UTC.
function utc(iso: string): Date {
  return new Date(/(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`)
}

// The run's start as a local calendar date, so "Today" can say which day its results are from.
function runDay(iso: string): { text: string; isToday: boolean } | null {
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(iso)
  const d = new Date(hasZone ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return null
  return { text: fmtInstant(d.toISOString()), isToday: localISO(d) === todayISO() }
}

export default function Today() {
  const [run, setRun] = useState<RunInfo | null>(null)
  const [rows, setRows] = useState<RunJobRow[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [resumes, setResumes] = useState<ResumeList | null>(null)
  const [skipReasons, setSkipReasons] = useState<string[]>([])
  const [due, setDue] = useState<FollowUpRow[]>([])
  const [cutoff, setCutoff] = useState<number | null>(null)
  const [inbound, setInbound] = useState<InboundEmailInfo | null>(null)

  const running = run?.running ?? false

  const refresh = useCallback(() => {
    return getLatestRun().then((r) => {
      setRun(r)
      if (r && !r.running) {
        getRunJobs(r.id)
          .then(setRows)
          .catch((e: Error) => setError(e.message))
      }
    })
  }, [])

  useEffect(() => {
    refresh()
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoaded(true))
  }, [refresh])

  const refreshDue = useCallback(
    () =>
      Promise.all([listFollowUps({ bucket: 'overdue' }), listFollowUps({ bucket: 'today' })])
        .then(([overdue, today]) => setDue([...overdue, ...today]))
        .catch((e: Error) => setError(e.message)),
    [],
  )

  useEffect(() => {
    void refreshDue()
  }, [refreshDue])

  useEffect(() => {
    getInbound()
      .then((r) => setInbound(r.emails[0] ?? null))
      .catch(() => setInbound(null)) // optional feature: no emails, or not set up
  }, [])

  useEffect(() => {
    getSettings()
      .then((s) => {
        setSkipReasons(Array.isArray(s.skip_reasons) ? s.skip_reasons.map(String) : [])
        setCutoff(typeof s.match_cutoff === 'number' ? s.match_cutoff : null)
      })
      .catch(() => setSkipReasons([]))
  }, [])

  // After a status change: reload this run's jobs and the follow-ups panel.
  const changed = useCallback(async () => {
    await Promise.all([
      run ? getRunJobs(run.id).then(setRows).catch((e: Error) => setError(e.message)) : Promise.resolve(),
      refreshDue(),
    ])
  }, [run, refreshDue])

  useEffect(() => {
    listResumes()
      .then(setResumes)
      .catch(() => setResumes(null))
  }, [])

  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => {
      refresh().catch((e: Error) => setError(e.message))
    }, 3000)
    return () => clearInterval(timer)
  }, [running, refresh])

  async function runNow() {
    setStarting(true)
    setError('')
    try {
      await startRun()
      setRows([])
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setStarting(false)
    }
  }

  const runDocs: DocsRunner = async (jobId, action) => {
    setBusyId(jobId)
    try {
      try {
        await action()
      } catch (e) {
        return { error: errorText(e), stale: false }
      }
      try {
        if (run) setRows(await getRunJobs(run.id))
      } catch {
        return { error: null, stale: true }
      }
      return { error: null, stale: false }
    } finally {
      setBusyId(null)
    }
  }

  const notEligible = ['excluded', 'closed', 'duplicate', 'repeat']
  const ready = rows.filter((r) => r.job.docs_folder && !notEligible.includes(r.outcome))
  const noDocs = rows.filter((r) => !r.job.docs_folder && (r.outcome === 'matched' || r.outcome === 'prepared'))
  const matches = [...ready, ...noDocs]
  const resumeList = resumes?.resumes ?? []
  // Jobs you already decided on (skipped, rejected, applied...) stay out of the to-do sections; they remain in "Everything this run".
  const open = (r: RunJobRow) => r.job.status === 'New' || r.job.status === 'Ready'
  const below = rows.filter((r) => r.outcome === 'new' && r.job.match_score != null && !r.job.docs_folder && open(r))
  const unread = rows.filter((r) => r.outcome === 'new' && r.job.match_score == null && !r.job.docs_folder && open(r))

  return (
    <div>
      <h1>Today</h1>
      <p className="muted">
        {new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
      </p>
      {(() => {
        // Only an email newer than the last run can explain why that run is not today's.
        if (!inbound || (run && utc(inbound.received_at) < utc(run.started_at))) return null
        const notice = inboundNoticeText(inbound.status, inbound.note)
        return notice ? <div className="result bad">{notice}</div> : null
      })()}
      {run && !running && (() => {
        const day = runDay(run.started_at)
        if (!day) return null
        return day.isToday ? (
          <p className="muted">{lastRunText(run.trigger, day.text)}</p>
        ) : (
          <div className="result bad">{staleRunText(run.trigger, day.text)}</div>
        )
      })()}
      <div className="row">
        <button className="primary" disabled={running || starting || busyId !== null} onClick={() => void runNow()}>
          Run now
        </button>
        <Tip text="Searches the web for jobs that fit what you're looking for. A run takes a few minutes. It stops early if it reaches the spending limit in Settings." />
      </div>
      {error && <div className="result bad">{error}</div>}
      {due.length > 0 && (
        <div className="card due-panel">
          <h2>Follow-ups due today</h2>
          <FollowUpList rows={due} onChanged={changed} compact />
        </div>
      )}
      {!loaded && <p className="loading">Loading…</p>}
      {loaded && !run && <p className="muted">No searches yet. Press Run now to look for jobs.</p>}
      {run && running && <p>Running: {run.stage ?? 'starting'}…</p>}
      {run && !running && (
        <>
          <p>
            {run.found} found, {run.new} new, {run.matched} matched, {run.prepared} prepared · about ${run.est_cost.toFixed(2)}
          </p>
          {run.errors.length > 0 && (
            <div className="result bad">
              <p>Some things went wrong:</p>
              <ul>
                {run.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          {matches.length === 0 && (
            <p className="muted">
              No matches {cutoff != null ? `at or above your ${cutoff}% cutoff` : 'at or above your cutoff'} this run.
            </p>
          )}
          {ready.length > 0 && <h2>Ready to apply</h2>}
          {ready.map(({ job }) => (
            <ReadyCard
              key={job.id}
              job={job}
              resumes={resumeList}
              defaultId={resumes?.default_id ?? null}
              busyId={busyId}
              runDocs={runDocs}
              skipReasons={skipReasons}
              onChanged={changed}
            />
          ))}
          {noDocs.length > 0 && (
            <>
              <h2>Matches without documents</h2>
              {resumes && resumeList.length === 0 && (
                <p className="help">Add your resume in Settings &gt; Your resume to get tailored documents.</p>
              )}
              {noDocs.map(({ job }) => (
                <div className="card match-card" key={job.id}>
                  <h3>
                    {job.employer} — {job.title}
                  </h3>
                  <p>
                    <StatusBadge status={job.status} />
                    {matchText(job.match_score) && (
                      <>
                        {' '}
                        <strong>{matchText(job.match_score)}</strong>
                      </>
                    )}
                  </p>
                  {job.flags.length > 0 && (
                    <p>
                      <Chips flags={job.flags} />
                    </p>
                  )}
                  <p>{formatPay(job.pay_min, job.pay_max)}</p>
                  <p>{[job.location, job.work_mode].filter(Boolean).join(' · ')}</p>
                  <p>
                    <ApplyLink job={job} />
                  </p>
                  {job.reasons && (
                    <p>
                      <strong>Why it fits:</strong> {job.reasons}
                    </p>
                  )}
                  {job.gaps && (
                    <p>
                      <strong>Gaps:</strong> {job.gaps}
                    </p>
                  )}
                  <RepeatBanner job={job} onChanged={changed} />
                  {canMakeDocs(job.status) && <MakeDocsButton job={job} busyId={busyId} runDocs={runDocs} />}
                  <StatusActions job={job} skipReasons={skipReasons} onChanged={changed} />
                </div>
              ))}
            </>
          )}
          {below.length > 0 && (
            <details className="result-list" open={matches.length === 0 || undefined}>
              <summary>Below your cutoff ({below.length})</summary>
              <div className="table-wrap">
                <table className="jobs-table below-table stack">
                  <thead>
                    <tr>
                      <th>Match</th>
                      <th>Job</th>
                      <th>Pay</th>
                      <th>Location</th>
                      <th>Why it scored this way</th>
                      <th>Gaps</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {below.map(({ job }) => (
                      <tr key={job.id}>
                        <td className="nowrap" data-label="Match">
                          <strong>{job.match_score}%</strong>
                        </td>
                        <td className="job-cell">
                          {job.employer} — {job.title} <StatusBadge status={job.status} /> <ApplyLink job={job} />
                          <RepeatBanner job={job} onChanged={changed} />
                          {job.flags.length > 0 && (
                            <div className="flag-list">
                              <Chips flags={job.flags} />
                            </div>
                          )}
                        </td>
                        <td className="nowrap" data-label="Pay">{formatPay(job.pay_min, job.pay_max)}</td>
                        <td data-label="Location">{[job.location, job.work_mode].filter(Boolean).join(' · ') || '—'}</td>
                        <td className="why-cell" data-label="Why">{job.reasons || '—'}</td>
                        <td className="why-cell" data-label="Gaps">{job.gaps || '—'}</td>
                        <td className="actions-cell">
                          {canMakeDocs(job.status) && <MakeDocsButton job={job} busyId={busyId} runDocs={runDocs} />}
                          <StatusActions job={job} skipReasons={skipReasons} onChanged={changed} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          {unread.length > 0 && (
            <details className="result-list" open>
              <summary>Couldn't judge the fit ({unread.length})</summary>
              <p className="help">
                JobMe couldn't open or read these postings, so they weren't scored. Open them yourself to check.
              </p>
              <div className="table-wrap">
                <table className="jobs-table below-table stack">
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Pay</th>
                      <th>Location</th>
                      <th>Why not scored</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unread.map(({ job }) => (
                      <tr key={job.id}>
                        <td className="job-cell">
                          {job.employer} — {job.title} <StatusBadge status={job.status} />{' '}
                          <ApplyLink job={job} label="Open posting" />
                        </td>
                        <td className="nowrap" data-label="Pay">{formatPay(job.pay_min, job.pay_max)}</td>
                        <td data-label="Location">{[job.location, job.work_mode].filter(Boolean).join(' · ') || '—'}</td>
                        <td className="why-cell" data-label="Why not">
                          {job.flags.length > 0 ? <Chips flags={job.flags} /> : '—'}
                          <RepeatBanner job={job} onChanged={changed} />
                        </td>
                        <td className="actions-cell">
                          {canMakeDocs(job.status) && <MakeDocsButton job={job} busyId={busyId} runDocs={runDocs} />}
                          <StatusActions job={job} skipReasons={skipReasons} onChanged={changed} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          {rows.length > 0 && (
            <details className="result-list">
              <summary>Everything this run ({rows.length})</summary>
              <ul>
                {rows.map((row) => (
                  <li key={`${row.outcome}-${row.job.id}`}>
                    {row.job.employer} — {row.job.title}: {outcomeLabel(row)} <StatusBadge status={row.job.status} />
                    {matchText(row.job.match_score) && <> · {matchText(row.job.match_score)}</>}
                    {outcomeReason(row) && <div className="help">{outcomeReason(row)}</div>}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  )
}
