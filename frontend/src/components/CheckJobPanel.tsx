import { useEffect, useState } from 'react'
import { checkJob, fitJob, getFitChoices, type CheckedJob, type FitChoice, type FitResult } from '../api.ts'
import { errorText } from '../pages/jobFormat.ts'
import FitCard from './FitCard.tsx'
import JobLink from './JobLink.tsx'

type Phase = 'idle' | 'reading' | 'judging'

// Paste a job's text or link, have an AI read it and say how well it fits, and keep it in the tracker.
// The job is saved as soon as it is read, so a failure while judging never loses it.
export default function CheckJobPanel({
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

  useEffect(() => {
    getFitChoices()
      .then((c) => {
        setChoices(c)
        setStep((cur) => cur || (c.find((x) => x.default) ?? c[0])?.id || '')
      })
      .catch((e) => setError(errorText(e)))
  }, [])

  async function judge(id: number) {
    setPhase('judging')
    setError('')
    try {
      const res = await fitJob(id, step)
      setFit(res.fit)
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
    </div>
  )
}
