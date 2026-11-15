import { useEffect, useState } from 'react'
import {
  getSchedule,
  getSettings,
  saveSettings,
  scheduleOff,
  scheduleOn,
  type ScheduleStatus,
  type Settings,
} from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'
import Tip from '../components/Tip.tsx'

const UNSUPPORTED = 'Scheduling from JobMe works on Windows. See docs/scheduling-mac-linux.md.'

const DAYS: [string, string][] = [
  ['mon', 'Monday'],
  ['tue', 'Tuesday'],
  ['wed', 'Wednesday'],
  ['thu', 'Thursday'],
  ['fri', 'Friday'],
  ['sat', 'Saturday'],
  ['sun', 'Sunday'],
]

interface Snapshot {
  days: string[]
  times: string[]
  cutoff: string
  wake: boolean
}

function localTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function summarize(s: Snapshot): string {
  const names = DAYS.filter(([k]) => s.days.includes(k)).map(([, n]) => n.slice(0, 3))
  return `Cutoff ${s.cutoff}% · ${names.length ? names.join(', ') : 'No days chosen'}`
}

export default function ScheduleSection({ mode, onSaved }: { mode: SectionMode; onSaved?: () => void | Promise<void> }) {
  const [days, setDays] = useState<string[]>([])
  const [times, setTimes] = useState<string[]>([])
  const [cutoff, setCutoff] = useState('75')
  const [wake, setWake] = useState(false)
  const [status, setStatus] = useState<ScheduleStatus | null>(null)
  const [autoBusy, setAutoBusy] = useState(false)
  const [autoError, setAutoError] = useState('')
  const [saved, setSaved] = useState<Snapshot>({ days: [], times: [], cutoff: '75', wake: false })
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')

  function apply(s: Snapshot) {
    setDays(s.days)
    setTimes(s.times)
    setCutoff(s.cutoff)
    setWake(s.wake)
  }

  useEffect(() => {
    getSettings()
      .then((s) => {
        const sched = (s.schedule ?? {}) as { days?: string[]; times?: string[]; wake?: boolean }
        const snap = {
          days: sched.days ?? [],
          times: sched.times ?? [],
          cutoff: String(s.match_cutoff ?? 75),
          wake: sched.wake === true,
        }
        apply(snap)
        setSaved(snap)
        setLoaded(true)
      })
      .catch((e: Error) => setLoadError(e.message))
    if (mode === 'settings') {
      getSchedule()
        .then(setStatus)
        .catch(() => setStatus(null))
    }
  }, [mode])

  const cleanTimes = [...new Set(times.filter((t) => t))].sort()
  const canTurnOn = days.length > 0 && cleanTimes.length > 0

  async function autoAction(work: () => Promise<unknown>) {
    setAutoBusy(true)
    setAutoError('')
    try {
      await work()
      setStatus(await getSchedule())
    } catch (e) {
      setAutoError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setAutoBusy(false)
    }
  }

  const turnOn = () =>
    autoAction(async () => {
      const orderedDays = DAYS.map(([k]) => k).filter((k) => days.includes(k))
      await scheduleOn({ days: orderedDays, times: cleanTimes, wake })
      setSaved((prev) => ({ ...prev, days: orderedDays, times: cleanTimes, wake }))
    })

  const turnOff = () => autoAction(() => scheduleOff())

  async function save() {
    const text = cutoff.trim()
    const n = Number(text)
    if (!/^\d+$/.test(text) || n < 0 || n > 100) {
      throw new Error('Please enter a whole number from 0 to 100.')
    }
    const cleanTimes = [...new Set(times.filter((t) => t))].sort()
    const orderedDays = DAYS.map(([k]) => k).filter((k) => days.includes(k))
    const current = await getSettings()
    const next: Settings = {
      ...current,
      schedule: { ...(current.schedule as object), days: orderedDays, times: cleanTimes, wake },
      match_cutoff: n,
    }
    await saveSettings(next)
    const snap = { days: orderedDays, times: cleanTimes, cutoff: String(n), wake }
    apply(snap)
    setSaved(snap)
    await onSaved?.()
  }

  return (
    <SectionCard
      title="Schedule and match cutoff"
      summary={summarize(saved)}
      mode={mode}
      onSave={save}
      canSave={loaded && !loadError}
      saveLabel="Continue"
      onCancel={() => apply(saved)}
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      {loaded && (
        <>
          {mode === 'wizard' && (
            <p className="muted">
              You can turn on automatic searches later in Settings. For now your choices are saved, and you can start a
              search yourself.
            </p>
          )}
          <fieldset className="field">
            <legend>Days to search</legend>
            {DAYS.map(([k, name]) => (
              <label key={k}>
                <input
                  type="checkbox"
                  checked={days.includes(k)}
                  onChange={(e) => setDays(e.target.checked ? [...days, k] : days.filter((d) => d !== k))}
                />{' '}
                {name}
              </label>
            ))}
            <span className="help">JobMe will search on the days you tick.</span>
          </fieldset>
          <div className="field">
            <div className="field-label">Times of day</div>
            {times.map((t, i) => (
              <div className="row" key={i}>
                <input
                  type="time"
                  aria-label={`Time ${i + 1}`}
                  value={t}
                  onChange={(e) => setTimes(times.map((x, j) => (j === i ? e.target.value : x)))}
                />
                <button className="danger" onClick={() => setTimes(times.filter((_, j) => j !== i))}>Remove</button>
              </div>
            ))}
            <div>
              <button className="add" onClick={() => setTimes([...times, ''])}>Add a time</button>
            </div>
            <span className="help">The times of day JobMe should search on those days.</span>
          </div>
          {mode === 'settings' && (
            <div className="field" role="group" aria-labelledby="auto-heading">
              <div className="field-label" id="auto-heading">
                Automatic search
              </div>
              {status && !status.supported && <p className="muted">{UNSUPPORTED}</p>}
              {(status === null || status.supported) && (
                <>
                  <label className="check">
                    <input type="checkbox" checked={wake} onChange={(e) => setWake(e.target.checked)} /> Wake the PC from
                    sleep to run
                  </label>
                  <span className="help">
                    Works from sleep, not from a full shutdown. Off by default so a sleeping laptop is not woken without
                    you asking.
                  </span>
                  {status && (
                    <p>
                      {status.enabled
                        ? `Automatic search is on.${status.next_run ? ` Next run: ${status.next_run}.` : ''}`
                        : 'Automatic search is off.'}
                    </p>
                  )}
                  <p className="help">
                    JobMe runs while you are logged in to Windows (a locked screen is fine) and the PC is on. A run
                    missed while the PC was asleep or off happens as soon as it is back on.
                  </p>
                  {autoError && <div className="result bad">{autoError}</div>}
                  <div className="row">
                    <button
                      className="primary"
                      disabled={autoBusy || !canTurnOn}
                      onClick={() => void turnOn()}
                    >
                      {status?.enabled ? 'Update schedule' : 'Turn on'}
                    </button>
                    <button disabled={autoBusy || !status?.enabled} onClick={() => void turnOff()}>
                      Turn off
                    </button>
                  </div>
                  {status?.enabled && (
                    <span className="help">Changed the days, times or wake setting? Press Update schedule to apply it.</span>
                  )}
                </>
              )}
              {status?.last_run && (
                <p className={status.last_run.errors.length > 0 ? 'result bad' : undefined}>
                  Last scheduled run: {localTime(status.last_run.started_at)}.{' '}
                  {status.last_run.errors.length > 0
                    ? status.last_run.errors[0]
                    : `${status.last_run.found} found, ${status.last_run.new} new, ${status.last_run.matched} matched.`}
                </p>
              )}
            </div>
          )}
          <div className="field">
            <div className="field-label">
              <label htmlFor="match-cutoff">Match cutoff (%)</label>
              <Tip text="If you switch the AI used for scoring, you may need to adjust this." />
            </div>
            <input
              id="match-cutoff"
              inputMode="numeric"
              value={cutoff}
              onChange={(e) => setCutoff(e.target.value)}
            />
            <span className="help">Jobs that score at or above this get a tailored resume and cover letter. If you change the scoring model, you may need to adjust this.</span>
          </div>
        </>
      )}
    </SectionCard>
  )
}
