import { useEffect, useRef, useState } from 'react'
import { getSettings, saveSettings, type Settings } from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'

interface Snapshot {
  days: string
  reasons: string[]
}

const NUMBER_ERROR = 'Enter a number of 0 or more.'
const NAME_ERROR = 'Each reason needs a name.'
const DUPLICATE_ERROR = 'Each reason can appear only once.'

function validWhole(text: string): boolean {
  const t = text.trim()
  return t !== '' && Number.isFinite(Number(t)) && Number(t) >= 0 && Number.isInteger(Number(t))
}

interface Row {
  id: number
  text: string
  locked: boolean
}

function isOther(reason: string): boolean {
  return reason.trim().toLowerCase() === 'other'
}

export default function TrackingSection({ mode }: { mode: SectionMode }) {
  const [days, setDays] = useState('7')
  const [rows, setRows] = useState<Row[]>([])
  const nextId = useRef(0)
  const focusId = useRef<number | null>(null)
  const [saved, setSaved] = useState<Snapshot>({ days: '7', reasons: [] })
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')

  function apply(s: Snapshot) {
    setDays(s.days)
    // The first "Other" in the saved list is the canonical one and stays locked.
    const lockAt = s.reasons.findIndex(isOther)
    setRows(s.reasons.map((text, i) => ({ id: nextId.current++, text, locked: i === lockAt })))
  }

  useEffect(() => {
    getSettings()
      .then((s) => {
        const raw = s.followup_default_days
        const list = Array.isArray(s.skip_reasons) ? s.skip_reasons.map(String) : []
        const snap: Snapshot = {
          days: typeof raw === 'number' ? String(raw) : '0',
          reasons: list.some(isOther) ? list : [...list, 'Other'],
        }
        apply(snap)
        setSaved(snap)
        setLoaded(true)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  const reasons = rows.map((r) => r.text)
  const trimmed = reasons.map((r) => r.trim())
  const lowered = trimmed.filter((r) => r).map((r) => r.toLowerCase())
  const duplicates = new Set(lowered.filter((r, i) => lowered.indexOf(r) !== i))
  const daysOk = validWhole(days)
  const namesOk = trimmed.every((r) => r)
  const valid = daysOk && namesOk && duplicates.size === 0

  function rename(i: number, value: string) {
    setRows(rows.map((r, j) => (j === i ? { ...r, text: value } : r)))
  }

  function move(i: number, by: -1 | 1) {
    const next = [...rows]
    ;[next[i], next[i + by]] = [next[i + by], next[i]]
    setRows(next)
  }

  async function save() {
    if (!daysOk) throw new Error(NUMBER_ERROR)
    if (!namesOk) throw new Error(NAME_ERROR)
    if (duplicates.size > 0) throw new Error(DUPLICATE_ERROR)
    const current = await getSettings()
    const next: Settings = {
      ...current,
      followup_default_days: Number(days.trim()),
      skip_reasons: trimmed,
    }
    await saveSettings(next)
    const snap: Snapshot = { days: String(Number(days.trim())), reasons: trimmed }
    apply(snap)
    setSaved(snap)
  }

  const n = Number(saved.days)
  const k = saved.reasons.length
  const reasonWord = k === 1 ? 'skip reason' : 'skip reasons'
  const summary =
    n === 0
      ? `Check-in turned off · ${k} ${reasonWord}`
      : `Check-in after ${n} ${n === 1 ? 'day' : 'days'} · ${k} ${reasonWord}`

  return (
    <SectionCard
      title="Tracking"
      summary={summary}
      mode={mode}
      onSave={save}
      canSave={loaded && !loadError && valid}
      onCancel={() => apply(saved)}
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      {loaded && (
        <>
          <div className="field">
            <div className="field-label">
              <label htmlFor="followup-days">Check in after (days)</label>
            </div>
            <input
              id="followup-days"
              inputMode="numeric"
              value={days}
              onChange={(e) => setDays(e.target.value)}
            />
            {!daysOk && <span className="result bad">{NUMBER_ERROR}</span>}
            <span className="help">
              When you mark a job applied, JobMe adds a follow-up this many days later. Set 0 to turn it off.
            </span>
          </div>
          <div className="field" role="group" aria-labelledby="skip-reasons-label">
            <div className="field-label" id="skip-reasons-label">
              Reasons for skipping a job
            </div>
            {rows.map((row, i) => {
              const name = row.text.trim()
              const label = name || `reason ${i + 1}`
              const other = row.locked
              return (
                <div key={row.id}>
                  <input
                    aria-label={`Skip reason: ${label}`}
                    maxLength={40}
                    value={row.text}
                    readOnly={other}
                    ref={(el) => {
                      if (el && focusId.current === row.id) {
                        focusId.current = null
                        el.focus()
                      }
                    }}
                    onChange={(e) => rename(i, e.target.value)}
                  />{' '}
                  <button aria-label={`Move ${label} up`} disabled={i === 0} onClick={() => move(i, -1)}>
                    Up
                  </button>{' '}
                  <button
                    aria-label={`Move ${label} down`}
                    disabled={i === rows.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    Down
                  </button>{' '}
                  <button
                    className="danger"
                    aria-label={`Remove ${label}`}
                    disabled={other}
                    onClick={() => setRows(rows.filter((_, j) => j !== i))}
                  >
                    Remove
                  </button>
                  {!name && <div className="result bad">{NAME_ERROR}</div>}
                  {name && duplicates.has(name.toLowerCase()) && <div className="result bad">{DUPLICATE_ERROR}</div>}
                </div>
              )
            })}
            <div>
              <button className="add" onClick={() => {
                  const id = nextId.current++
                  focusId.current = id
                  setRows([...rows, { id, text: '', locked: false }])
                }}>
                Add a reason
              </button>
            </div>
            <span className="help">These are the choices when you skip a job. 'Other' is always available.</span>
          </div>
        </>
      )}
    </SectionCard>
  )
}
