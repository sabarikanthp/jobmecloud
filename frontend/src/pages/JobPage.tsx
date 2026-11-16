import { useCallback, useEffect, useState } from 'react'
import { getJob, getSettings, listResumes, type JobDetail, type ResumeList } from '../api.ts'
import StatusActions from '../components/StatusActions.tsx'
import StatusBadge from '../components/StatusBadge.tsx'
import { useNav } from '../nav.tsx'
import DocsActions from './DocsActions.tsx'
import JobContacts from './JobContacts.tsx'
import JobDetails from './JobDetails.tsx'
import JobFollowUps from './JobFollowUps.tsx'
import JobInterviews from './JobInterviews.tsx'
import { KeyDates, Notes, Timeline } from './JobSections.tsx'
import { Chips } from './JobParts.tsx'
import { errorText, formatPay, matchText } from './jobFormat.ts'
import { useDocsRunner } from './useDocsRunner.ts'

export default function JobPage({ id }: { id: number }) {
  const { go } = useNav()
  const [job, setJob] = useState<JobDetail | null>(null)
  const [error, setError] = useState('')
  const [resumes, setResumes] = useState<ResumeList | null>(null)
  const [skipReasons, setSkipReasons] = useState<string[]>([])

  const reload = useCallback(async () => {
    try {
      setJob(await getJob(id))
      setError('')
    } catch (e) {
      setError(errorText(e))
    }
  }, [id])

  useEffect(() => {
    getJob(id)
      .then(setJob)
      .catch((e: unknown) => setError(errorText(e)))
  }, [id])

  useEffect(() => {
    listResumes()
      .then(setResumes)
      .catch(() => setResumes(null))
    getSettings()
      .then((s) => setSkipReasons(Array.isArray(s.skip_reasons) ? s.skip_reasons.map(String) : []))
      .catch(() => setSkipReasons([]))
  }, [])

  const { busyId, runDocs } = useDocsRunner(async () => {
    setJob(await getJob(id))
  })

  const back = (
    <p>
      <button type="button" onClick={() => go('Jobs')}>
        Back to jobs
      </button>
    </p>
  )

  if (!job) {
    return (
      <div>
        {back}
        {error ? <div className="result bad">{error}</div> : <p className="loading">Loading…</p>}
      </div>
    )
  }

  const score = matchText(job.match_score)
  const rules = Array.isArray(job.hard_rules) ? job.hard_rules : []
  const failed = rules.filter((r) => !r.passed)
  const passed = rules.filter((r) => r.passed)
  const where = [job.location, job.work_mode].filter(Boolean).join(' · ')

  return (
    <div>
      {back}
      {error && <div className="result bad">{error}</div>}
      <section className="card" aria-labelledby="job-heading">
        <h1 id="job-heading">
          {job.employer} — {job.title}
        </h1>
        <p>
          <StatusBadge status={job.status} />
          {score && (
            <>
              {' '}
              <strong>{score}</strong>
            </>
          )}
        </p>
        <p>{[formatPay(job.pay_min, job.pay_max), where].filter(Boolean).join(' · ')}</p>
        {(job.apply_url || job.linkedin) && (
          <p>
            {job.apply_url && (
              <a href={job.apply_url} target="_blank" rel="noreferrer">
                Apply
              </a>
            )}
            {job.linkedin && <span className="chip">LinkedIn</span>}
          </p>
        )}
        {job.flags.length > 0 && (
          <p>
            <Chips flags={job.flags} />
          </p>
        )}
      </section>

      <section className="card" aria-labelledby="job-status">
        <h2 id="job-status">Status</h2>
        <StatusActions job={job} skipReasons={skipReasons} onChanged={reload} />
        {job.status === 'Skipped' && (
          <p>
            Skipped: {job.skip_reason || 'no reason given'}
            {job.skip_note && <span className="help">{job.skip_note}</span>}
          </p>
        )}
        <KeyDates job={job} onChanged={reload} />
      </section>

      <JobDetails job={job} onChanged={reload} />

      <section className="card" aria-labelledby="job-docs">
        <h2 id="job-docs">Documents</h2>
        <DocsActions
          job={job}
          resumes={resumes?.resumes ?? []}
          defaultId={resumes?.default_id ?? null}
          busyId={busyId}
          runDocs={runDocs}
          makeable
          hasDocs={job.docs_folder !== null}
        />
      </section>

      {(job.reasons || job.gaps || rules.length > 0) && (
        <section className="card" aria-labelledby="job-why">
          <h2 id="job-why">Why it matched</h2>
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
          {failed.length > 0 && (
            <>
              <h3>Rules not met</h3>
              <ul>
                {failed.map((r) => (
                  <li key={r.rule}>
                    {r.rule}
                    {r.note ? `: ${r.note}` : ''}
                  </li>
                ))}
              </ul>
            </>
          )}
          {passed.length > 0 && (
            <>
              <h3>Rules passed</h3>
              <ul>
                {passed.map((r) => (
                  <li key={r.rule}>
                    {r.rule}
                    {r.note ? `: ${r.note}` : ''}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {job.description && (
        <section className="card">
          <details>
            <summary>Job posting</summary>
            <p className="posting">{job.description}</p>
          </details>
        </section>
      )}

      <JobContacts jobId={job.id} contacts={job.contacts} onChanged={reload} />
      <JobFollowUps jobId={job.id} rows={job.followups} onChanged={reload} />
      <JobInterviews jobId={job.id} rows={job.interviews} onChanged={reload} />
      <Notes key={job.id} job={job} onChanged={reload} />
      <Timeline job={job} />
    </div>
  )
}
