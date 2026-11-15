import { useState } from 'react'
import { completeStep, startRun, type SetupState } from '../api.ts'

const STEP_NAMES: [number, string][] = [
  [1, 'Welcome'],
  [2, 'Connect an AI'],
  [3, 'About you'],
  [4, 'Your resume'],
  [5, "What you're looking for"],
  [6, 'Employers to watch'],
  [7, 'Import past jobs'],
  [8, 'Schedule and match cutoff'],
]

export default function DoneStep({ state, onFinished }: { state: SetupState; onFinished: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function finish() {
    setBusy(true)
    setError('')
    try {
      await completeStep(9)
      onFinished()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  async function firstSearch() {
    setBusy(true)
    setError('')
    try {
      await startRun()
      await completeStep(9)
      onFinished()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <p>You're all set.</p>
      <ul>
        {STEP_NAMES.map(([n, name]) => (
          <li key={n}>
            {name}: {state.skipped.includes(n) ? 'Skipped — you can do this later in Settings.' : 'Done'}
          </li>
        ))}
      </ul>
      <div className="field">
        <div className="row">
          <button className="primary" disabled={busy} onClick={() => void firstSearch()}>
            Run my first search
          </button>
        </div>
        <span className="help">JobMe searches in the background. Your results appear on the Today page.</span>
      </div>
      {error && <div className="result bad">{error}</div>}
      <div className="row">
        <button className="primary" disabled={busy} onClick={() => void finish()}>
          Finish
        </button>
      </div>
    </div>
  )
}
