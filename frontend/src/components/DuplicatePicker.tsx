import { useEffect, useState } from 'react'
import {
  askSimilar,
  getSimilar,
  listJobs,
  type RelatedJob,
  type SimilarMatch,
  type SimilarVerdict,
} from '../api.ts'
import { errorText } from '../pages/jobFormat.ts'
import JobLink from './JobLink.tsx'
import StatusBadge from './StatusBadge.tsx'

const VERDICT_TEXT = {
  same: 'The AI thinks it is the same job',
  different: 'The AI thinks it is a different job',
  unsure: 'The AI is not sure',
}

function Candidate({
  job,
  why,
  onPick,
  busy,
}: {
  job: RelatedJob
  why?: string
  onPick: (id: number) => void
  busy: boolean
}) {
  return (
    <li className="duplicate-candidate">
      <div>
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
      </div>
      {why && <div className="help">{why}</div>}
      <button
        type="button"
        disabled={busy}
        aria-label={`Mark as a duplicate of ${job.employer} – ${job.title}`}
        onClick={() => onPick(job.id)}
      >
        This is the one
      </button>
    </li>
  )
}

// Choose which job in the tracker this one repeats: the likely matches first, then a search, or ask the AI.
export default function DuplicatePicker({
  jobId,
  onPick,
  onCancel,
  busy = false,
}: {
  jobId: number
  onPick: (id: number) => void | Promise<void>
  onCancel: () => void
  busy?: boolean
}) {
  const [matches, setMatches] = useState<SimilarMatch[] | null>(null)
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<RelatedJob[] | null>(null)
  const [asking, setAsking] = useState(false)
  const [verdicts, setVerdicts] = useState<SimilarVerdict[] | null>(null)
  const [aiNote, setAiNote] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    getSimilar(jobId)
      .then((r) => setMatches(r.matches))
      .catch((e) => {
        setMatches([])
        setError(errorText(e))
      })
  }, [jobId])

  async function search() {
    if (!query.trim()) return
    setError('')
    try {
      const res = await listJobs({ q: query.trim(), sort: 'first_seen', dir: 'desc' })
      setFound(
        res.rows
          .filter((r) => r.id !== jobId)
          .slice(0, 8)
          .map((r) => ({ id: r.id, employer: r.employer, title: r.title, status: r.status, decided: null, decided_date: null })),
      )
    } catch (e) {
      setError(errorText(e))
    }
  }

  async function ask() {
    setError('')
    setAsking(true)
    try {
      const res = await askSimilar(jobId)
      setVerdicts(res.verdicts)
      setAiNote(res.message ?? (res.model ? `Compared by ${res.model}, about $${res.cost_usd.toFixed(2)}.` : ''))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="duplicate-picker inline-form">
      <h4>Which job is this a duplicate of?</h4>
      {matches === null && <p className="muted">Looking through your tracker…</p>}
      {matches !== null && matches.length === 0 && (
        <p className="help">Nothing in your tracker looks like this job. Search for it below.</p>
      )}
      {matches !== null && matches.length > 0 && (
        <ul className="duplicate-list">
          {matches.map((m) => (
            <Candidate key={m.id} job={m} why={m.reasons.join('. ')} onPick={onPick} busy={busy} />
          ))}
        </ul>
      )}
      <div className="row">
        <input
          type="search"
          aria-label="Search your jobs"
          placeholder="Search employer or title"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="button" onClick={() => void search()}>
          Search
        </button>
        <button type="button" disabled={asking} onClick={() => void ask()}>
          Ask the AI if I have seen this before
        </button>
      </div>
      {found !== null &&
        (found.length === 0 ? (
          <p className="help">No jobs found.</p>
        ) : (
          <ul className="duplicate-list">
            {found.map((j) => (
              <Candidate key={j.id} job={j} onPick={onPick} busy={busy} />
            ))}
          </ul>
        ))}
      {asking && <p className="muted">Comparing…</p>}
      {verdicts !== null && (
        <>
          {aiNote && <p className="help">{aiNote}</p>}
          <ul className="duplicate-list">
            {verdicts.map((v) => (
              <Candidate key={`ai-${v.id}`} job={v} why={`${VERDICT_TEXT[v.same]}: ${v.reason}`} onPick={onPick} busy={busy} />
            ))}
          </ul>
        </>
      )}
      {error && <div className="result bad">{error}</div>}
      <div className="row">
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}
