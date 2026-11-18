import { useEffect, useState } from 'react'
import { fitJob, getFitChoices, saveDescription, type FitChoice, type FitResult } from '../api.ts'
import { errorText } from '../pages/jobFormat.ts'
import FitCard from './FitCard.tsx'

type Phase = 'idle' | 'saving' | 'judging'

// For a job whose page could not be read (no fit yet), or any job you want judged again: paste the job description
// if you have it, pick an AI, and press Re-evaluate. The description is kept as soon as it is saved, so a failed
// judgment never loses it.
export default function ReEvaluate({
  job,
  onChanged,
}: {
  job: { id: number; description: string | null }
  onChanged: () => void | Promise<void>
}) {
  const [choices, setChoices] = useState<FitChoice[]>([])
  const [step, setStep] = useState('')
  const [text, setText] = useState('')
  const [replacing, setReplacing] = useState(false)
  const [kept, setKept] = useState(false) // a pasted description is saved on the job, even before the page reloads
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [fit, setFit] = useState<FitResult | null>(null)

  const hasDescription = !!job.description || kept
  const showBox = !hasDescription || replacing

  useEffect(() => {
    getFitChoices()
      .then((c) => {
        setChoices(c)
        setStep((cur) => cur || (c.find((x) => x.default) ?? c[0])?.id || '')
      })
      .catch((e) => setError(errorText(e)))
  }, [])

  async function run() {
    setError('')
    setNote('')
    setFit(null)
    try {
      if (text.trim()) {
        setPhase('saving')
        const saved = await saveDescription(job.id, text)
        setKept(true)
        setText('')
        setReplacing(false)
        if (!saved.details_read && saved.message) setNote(`Your description was saved, but its details could not be read: ${saved.message}`)
      }
    } catch (e) {
      setError(errorText(e))
      setPhase('idle')
      return
    }
    try {
      setPhase('judging')
      const res = await fitJob(job.id, step)
      setFit(res.fit)
      await onChanged()
    } catch (e) {
      setError(`${errorText(e)} Your description is saved: press Re-evaluate to try again.`)
    } finally {
      setPhase('idle')
    }
  }

  const busy = phase !== 'idle'
  const canRun = !busy && !!step && (hasDescription || text.trim() !== '')
  return (
    <div className="re-evaluate">
      {!hasDescription && (
        <p className="help">
          JobMeCloud could not read this job&apos;s page, so there is no fit yet. Paste the job description below and press
          Re-evaluate.
        </p>
      )}
      {showBox && (
        <label>
          {hasDescription ? 'New job description' : 'Job description'}
          <textarea rows={8} value={text} disabled={busy} onChange={(e) => setText(e.target.value)} placeholder="Paste the whole posting" />
        </label>
      )}
      <div className="row">
        <label>
          AI for the fit{' '}
          <select aria-label="AI for the fit" value={step} disabled={busy || choices.length === 0} onChange={(e) => setStep(e.target.value)}>
            {choices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="primary" disabled={!canRun} onClick={() => void run()}>
          Re-evaluate
        </button>
        {hasDescription && !replacing && (
          <button type="button" className="link" disabled={busy} onClick={() => setReplacing(true)}>
            Paste a different description
          </button>
        )}
      </div>
      {phase === 'saving' && <p className="muted">Saving the description…</p>}
      {phase === 'judging' && <p className="muted">Judging the fit…</p>}
      {note && <p className="help">{note}</p>}
      {error && <div className="result bad">{error}</div>}
      {fit && <FitCard fit={fit} />}
    </div>
  )
}
