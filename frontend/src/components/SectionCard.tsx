import { useEffect, useState, type ReactNode } from 'react'
import Tip from './Tip.tsx'

export type SectionMode = 'wizard' | 'settings'

interface Props {
  title: string
  tip?: string
  summary: ReactNode
  mode: SectionMode
  onSave: () => Promise<void>
  onCancel?: () => void
  canSave?: boolean
  saveLabel?: string
  children: ReactNode
}

export default function SectionCard({ title, tip, summary, mode, onSave, onCancel, canSave = true, saveLabel, children }: Props) {
  const wizard = mode === 'wizard'
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (!saved) return
    const t = setTimeout(() => setSaved(false), 3000)
    return () => clearTimeout(t)
  }, [saved])

  async function save() {
    setBusy(true)
    setError('')
    try {
      await onSave()
      if (!wizard) {
        setOpen(false)
        setSaved(true)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const showForm = wizard || open
  return (
    <section className="card section-card">
      <div className="section-head">
        <h3>
          {title}
          {tip && <Tip text={tip} />}
        </h3>
        <span role="status" className="saved-note">
          {saved ? 'Saved' : ''}
        </span>
      </div>
      {showForm ? (
        <>
          {children}
          {error && <div className="result bad">{error}</div>}
          <div className="row section-actions">
            <button className="primary" disabled={busy || !canSave} onClick={save}>
              {wizard ? (saveLabel ?? 'Save and continue') : 'Save'}
            </button>
            {!wizard && (
              <button
                disabled={busy}
                onClick={() => {
                  setOpen(false)
                  setError('')
                  onCancel?.()
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </>
      ) : (
        <div className="row section-summary">
          <span className="muted">{summary}</span>
          <button onClick={() => setOpen(true)}>Edit</button>
        </div>
      )}
    </section>
  )
}
