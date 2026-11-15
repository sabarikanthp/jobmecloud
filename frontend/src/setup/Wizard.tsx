import { useEffect, useState, type ReactNode } from 'react'
import { completeStep, getSetup, skipStep, type SetupState } from '../api.ts'
import AboutYouSection from '../sections/AboutYouSection.tsx'
import ImportSection from '../sections/ImportSection.tsx'
import AiSection from '../sections/AiSection.tsx'
import ResumeSection from '../sections/ResumeSection.tsx'
import SearchSection from '../sections/SearchSection.tsx'
import ScheduleSection from '../sections/ScheduleSection.tsx'
import StorageSection from '../sections/StorageSection.tsx'
import WatchlistSection from '../sections/WatchlistSection.tsx'
import DoneStep from './DoneStep.tsx'

const STEPS: Record<number, string> = {
  1: 'Welcome',
  2: 'Connect an AI',
  3: 'About you',
  4: 'Your resume',
  5: "What you're looking for",
  6: 'Employers to watch',
  7: 'Import past jobs',
  8: 'Schedule and match cutoff',
  9: 'Done',
}
const OPTIONAL = new Set([6, 7, 8])
const INTRO =
  'JobMe finds jobs that fit you, writes a tailored resume and cover letter for the best ones, and keeps track of everything you apply for. Your information stays on this computer, except what is sent to the AI you choose.'

export default function Wizard({ onFinished }: { onFinished: () => void }) {
  const [state, setState] = useState<SetupState | null>(null)
  const [step, setStep] = useState(1)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getSetup()
      .then((s) => {
        setState(s)
        setStep(s.next_step)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  if (!state) return error ? <div className="result bad">{error}</div> : <p>Loading…</p>

  async function advance(action: (n: number) => Promise<SetupState>) {
    setError('')
    setBusy(true)
    try {
      const next = await action(step)
      setState(next)
      if (next.finished) onFinished()
      else setStep(next.next_step)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const onSaved = () => advance(completeStep)

  let body: ReactNode
  if (step === 1) {
    body = (
      <>
        <p>{INTRO}</p>
        <StorageSection mode="wizard" onSaved={onSaved} />
      </>
    )
  } else if (step === 2) {
    body = <AiSection mode="wizard" onSaved={onSaved} />
  } else if (step === 3) {
    body = <AboutYouSection mode="wizard" onSaved={onSaved} />
  } else if (step === 4) {
    body = <ResumeSection mode="wizard" onSaved={onSaved} />
  } else if (step === 5) {
    body = <SearchSection mode="wizard" onSaved={onSaved} />
  } else if (step === 6) {
    body = <WatchlistSection mode="wizard" onSaved={onSaved} />
  } else if (step === 7) {
    body = <ImportSection mode="wizard" onSaved={onSaved} />
  } else if (step === 8) {
    body = <ScheduleSection mode="wizard" onSaved={onSaved} />
  } else {
    body = <DoneStep state={state} onFinished={onFinished} />
  }

  return (
    <div className="shell">
      <nav className="nav wizard-nav" aria-label="Setup steps">
        <div className="brand">JobMe</div>
        {Object.entries(STEPS).map(([k, name]) => {
          const n = Number(k)
          const done = state.completed.includes(n)
          const skipped = state.skipped.includes(n)
          const status = done ? 'Done' : skipped ? 'Skipped' : OPTIONAL.has(n) ? 'Optional' : ''
          return (
            <button
              key={n}
              className={n === step ? 'nav-item active' : 'nav-item'}
              aria-current={n === step ? 'step' : undefined}
              disabled={!(done || skipped || n === step)}
              onClick={() => {
                setError('')
                setStep(n)
              }}
            >
              <span>
                {n}. {name}
              </span>
              {status && <span className="step-status">{status}</span>}
            </button>
          )
        })}
      </nav>
      <main className="content">
        <h1>{STEPS[step]}</h1>
        {body}
        {error && <div className="result bad">{error}</div>}
        <div className="row wizard-buttons">
          <button
            disabled={step === 1 || busy}
            onClick={() => {
              setError('')
              setStep(step - 1)
            }}
          >
            Back
          </button>
          {OPTIONAL.has(step) && (
            <button className="link" disabled={busy} onClick={() => void advance(skipStep)}>
              Skip for now
            </button>
          )}
        </div>
      </main>
    </div>
  )
}
