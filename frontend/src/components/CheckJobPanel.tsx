import { useEffect, useState } from 'react'
import { checkJob, fitJob, getFitChoices, getJob, listResumes, type CheckedJob, type FitChoice, type FitResult, type JobDetail, type ResumeList } from '../api.ts'
import DocsActions from '../pages/DocsActions.tsx'
import { errorText } from '../pages/jobFormat.ts'
import { useDocsRunner } from '../pages/useDocsRunner.ts'
import FitCard from './FitCard.tsx'
import JobLink from './JobLink.tsx'
import StatusActions from './StatusActions.tsx'

type Phase = 'idle' | 'reading' | 'judging'

// Paste a job's text or link, have an AI read it and say how well it fits, and keep it in the tracker.
// The job is saved as soon as it is read, so a failure while judging never loses it.
export default function CheckJobPanel({
  skipReasons,
  onChanged,
  onClose,
}: {
  skipReasons: string[]
  onChanged: () => void | Promise<void>
  onClose: () => void
}) {
  const [input, setInput] = useState('')
  const [choices, setChoices] = useState<FitChoice[]>([])
  const [step, setStep] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [saved, setSaved] = useState<CheckedJob | null>(null)
  const [duplicate, setDuplicate] = useState(false)
  const [truncated, setTruncated] = useState(false)
  const [fit, setFit] = useState<FitResult | null>(null)
  const [current, setCurrent] = useState<JobDetail | null>(null) // the saved job as it is now, after any decision
  const [resumes, setResumes] = useState<ResumeList | null>(null)
  const { busyId, runDocs } = useDocsRunner(async () => {
    if (saved) setCurrent(await getJob(saved.id))
  })

  useEffect(() => {
    getFitChoices()
      .then((c) => {
        setChoices(c)
        setStep((cur) => cur || (c.find((x) => x.default) ?? c[0])?.id || '')
      })
      .catch((e) => setError(errorText(e)))
  }, [])

  async function refresh(id: number) {
    try {
      setCurrent(await getJob(id))
    } catch {
      setCurrent(null) // the decision controls simply do not appear; the fit above is still shown
    }
  }

  // Decisions change the job, so show what it is now. Documents are offered once it is applied, never made for you.
  async function decided() {
    if (saved) await refresh(saved.id)
    await onChanged()
  }

  const applied = current?.status === 'Applied'
  useEffect(() => {
    if (applied && !resumes) listResumes().then(setResumes).catch(() => setResumes({ resumes: [], default_id: null } as ResumeList))
  }, [applied, resumes])

  async function judge(id: number) {
    setPhase('judging')
    setError('')
    try {
      const res = await fitJob(id, step)
      setFit(res.fit)
      await refresh(id)
      await onChanged()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setPhase('idle')
    }
  }

  async function run() {
    setError('')
    setFit(null)
    setCurrent(null)
    setSaved(null)
    setDuplicate(false)
    setTruncated(false)
    setPhase('reading')
    let job: CheckedJob
    try {
      const res = await checkJob(input)
      job = res.job
      setSaved(job)
      setDuplicate(res.status === 'duplicate')
      setTruncated(res.truncated)
      await onChanged()
      if (res.status === 'duplicate') {
        setPhase('idle')
        return
      }
    } catch (e) {
      setError(errorText(e))
      setPhase('idle')
      return
    }
    await judge(job.id) // a failure here keeps the saved job, and offers a retry
  }

  const busy = phase !== 'idle'
  return (
    <div className="card check-panel">
      <h3>Check a job</h3>
      <label>
        Paste the job's text or its link
        <textarea
          rows={6}
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Paste the posting, or a link to it. LinkedIn links can't be opened: paste the text instead."
        />
      </label>
      <label>
        AI for the fit
        <select aria-label="AI for the fit" value={step} disabled={busy || choices.length === 0} onChange={(e) => setStep(e.target.value)}>
          {choices.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <p>
        <button type="button" disabled={busy || !input.trim() || !step} onClick={() => void run()}>
          Check fit
        </button>{' '}
        <button type="button" className="link" onClick={onClose}>
          Close
        </button>
      </p>
      {phase === 'reading' && <p className="muted">Reading the job…</p>}
      {phase === 'judging' && <p className="muted">Judging the fit…</p>}
      {error && <div className="result bad">{error}</div>}
      {truncated && <p className="help">The text was very long, so only the first part was read.</p>}
      {saved && (
        <div className="check-saved">
          <p>
            {duplicate ? 'This job is already in your tracker: ' : 'The job is saved in your tracker: '}
            <JobLink id={saved.id}>
              {saved.employer} – {saved.title}
            </JobLink>
          </p>
          {!busy && (duplicate || (error && !fit)) && (
            <button type="button" onClick={() => void judge(saved.id)}>
              {duplicate ? 'Re-check fit' : 'Retry fit'}
            </button>
          )}
        </div>
      )}
      {fit && <FitCard fit={fit} />}
      {fit && current && (
        <div className="check-decision">
          <h4>What do you want to do with it?</h4>
          <StatusActions job={current} skipReasons={skipReasons} onChanged={decided} />
          <p>
            <button type="button" onClick={onClose}>
              Leave it for now
            </button>
          </p>
        </div>
      )}
      {fit && current && applied && (
        <div className="check-docs">
          <h4>Documents (optional)</h4>
          {resumes && resumes.resumes.length === 0 ? (
            <p className="help">To make a resume and cover letter, add a resume in Settings first.</p>
          ) : (
            resumes && (
              <DocsActions
                job={current}
                resumes={resumes.resumes}
                defaultId={resumes.default_id}
                busyId={busyId}
                runDocs={runDocs}
                makeable
                hasDocs={current.docs_folder !== null}
                onResumeAdded={() => listResumes().then(setResumes)}
              />
            )
          )}
        </div>
      )}
    </div>
  )
}
