import type { JobSummary, ResumeEntry } from '../api.ts'
import StatusActions from '../components/StatusActions.tsx'
import StatusBadge from '../components/StatusBadge.tsx'
import { ApplyLink, Chips } from './JobParts.tsx'
import DocsActions from './DocsActions.tsx'
import { canMakeDocs, formatPay, matchText } from './jobFormat.ts'
import type { DocsRunner } from './docsTypes.ts'

export default function ReadyCard({
  job,
  resumes,
  defaultId,
  busyId,
  runDocs,
  skipReasons,
  onChanged,
}: {
  job: JobSummary
  resumes: ResumeEntry[]
  defaultId: string | null
  busyId: number | null
  runDocs: DocsRunner
  skipReasons: string[]
  onChanged: () => void | Promise<void>
}) {
  const makeable = canMakeDocs(job.status)
  const score = matchText(job.match_score)

  return (
    <div className="card match-card">
      <h3>
        {job.employer} — {job.title}
      </h3>
      <p>
        <StatusBadge status={job.status} />
        {score && (
          <>
            {' '}
            <strong>{score}</strong>
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
      <DocsActions
        job={job}
        resumes={resumes}
        defaultId={defaultId}
        busyId={busyId}
        runDocs={runDocs}
        makeable={makeable}
      >
        <StatusActions job={job} skipReasons={skipReasons} onChanged={onChanged} />
      </DocsActions>
    </div>
  )
}
