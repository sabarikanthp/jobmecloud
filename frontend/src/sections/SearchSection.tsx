import { useEffect, useRef, useState } from 'react'
import { getSearchProfile, importSearchNotes, saveSearchProfile, type SearchProfile } from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'
import Tip from '../components/Tip.tsx'
import { DAYS, MODES, applyDraft, fromForm, summaryOf, toForm, type SearchForm } from './search/form.ts'

const ACCEPT = '.docx,.txt,.md,.pdf'

type ListKey = 'roles' | 'locations' | 'dealBreakers' | 'warnings' | 'excluded' | 'doNotClaim'
type NumKey = 'radius' | 'pay' | 'commute' | 'postedDays'

export default function SearchSection({ mode, onSaved }: { mode: SectionMode; onSaved?: () => void | Promise<void> }) {
  const [saved, setSaved] = useState<SearchProfile | null>(null)
  const [form, setForm] = useState<SearchForm | null>(null)
  const [fromUpload, setFromUpload] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  function apply(p: SearchProfile) {
    setSaved(p)
    setForm(toForm(p))
    setFromUpload(false)
    setImportError('')
  }

  useEffect(() => {
    getSearchProfile()
      .then((p) => {
        apply(p)
        setLoaded(true)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // so the same file can be chosen again
    if (!file) return
    setImportError('')
    setImporting(true)
    try {
      // A draft only: it fills the form and nothing is saved until Save is pressed.
      const draft = await importSearchNotes(file)
      setForm((cur) => (cur ? applyDraft(draft, cur) : cur))
      setFromUpload(true)
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setImporting(false)
    }
  }

  async function save() {
    if (!form) return
    apply(await saveSearchProfile(fromForm(form)))
    await onSaved?.()
  }

  const set = (patch: Partial<SearchForm>) => setForm((cur) => (cur ? { ...cur, ...patch } : cur))

  const list = (id: string, label: string, key: ListKey, help: string, tip?: string) =>
    form && (
      <div className="field">
        <div className="field-label">
          <label htmlFor={id}>{label}</label>
          {tip && <Tip text={tip} />}
        </div>
        <textarea id={id} rows={3} value={form[key]} onChange={(e) => set({ [key]: e.target.value })} />
        <span className="help">{help}</span>
      </div>
    )

  const numberField = (id: string, label: string, key: NumKey, help: string) =>
    form && (
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <input id={id} inputMode="numeric" value={form[key]} onChange={(e) => set({ [key]: e.target.value })} />
        <span className="help">{help}</span>
      </div>
    )

  return (
    <SectionCard
      title="What you're looking for"
      summary={summaryOf(saved)}
      mode={mode}
      onSave={save}
      canSave={loaded && !loadError && !!form && !importing}
      onCancel={() => saved && apply(saved)}
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      <input ref={fileRef} type="file" accept={ACCEPT} hidden onChange={(e) => void onFile(e)} />
      {form && (
        <>
          <div className="row">
            <button className="add" disabled={importing} onClick={() => fileRef.current?.click()}>
              Draft from your notes (optional)
            </button>
          </div>
          <span className="help">Word, PDF, text or Markdown files work.</span>
          {importing && (
            <p role="status" className="muted">
              Reading your notes. This can take up to a minute.
            </p>
          )}
          {importError && <div className="result bad">{importError}</div>}
          {fromUpload && <p className="result ok">Check everything below. Nothing is saved until you press Save.</p>}
          {list('roles', 'Job titles you want', 'roles', 'One job title per line.')}
          <div className="field">
            <label htmlFor="positioning">Your strengths</label>
            <textarea
              id="positioning"
              rows={3}
              value={form.positioning}
              onChange={(e) => set({ positioning: e.target.value })}
            />
            <span className="help">A few sentences about what you do best.</span>
          </div>
          {list('locations', 'Locations', 'locations', 'One city or area per line.')}
          {numberField('radius', 'Distance in miles', 'radius', 'How far from those places you would look. Leave blank for no limit.')}
          <fieldset>
            <legend>Work type</legend>
            {MODES.map((m) => (
              <label key={m.key} className="radio">
                <input
                  type="checkbox"
                  checked={form.modes.includes(m.key)}
                  onChange={(e) =>
                    set({ modes: e.target.checked ? [...form.modes, m.key] : form.modes.filter((x) => x !== m.key) })
                  }
                />
                {m.label}
              </label>
            ))}
            <span className="help">Tick every kind of job you would take.</span>
          </fieldset>
          {numberField('pay', 'Minimum base pay (USD per year)', 'pay', 'Leave blank if pay does not matter.')}
          {list('deal', 'Deal-breakers', 'dealBreakers', 'One per line.', 'A job with any of these is left out, for example "Requires security clearance".')}
          {list('warn', 'Warnings', 'warnings', 'One per line.', 'A job with any of these is still shown, but flagged.')}
          {list('excl', 'Employers to exclude', 'excluded', 'One employer per line. JobMe skips their jobs.')}
          {list(
            'dnc',
            'Things not to claim',
            'doNotClaim',
            'One per line.',
            "Skills or experience you don't have. JobMe will never put these in your resume or cover letter.",
          )}
          <details>
            <summary>More options</summary>
            {numberField('commute', 'Longest commute (miles)', 'commute', 'Leave blank for no limit.')}
            {numberField('posted', 'Skip postings older than (days)', 'postedDays', 'Leave blank to see postings of any age.')}
            <h4>Search area for each weekday</h4>
            <span className="help">Optional. Where or what JobMe should search on each day. Leave a day blank to skip it.</span>
            {DAYS.map((d) => (
              <label key={d.key}>
                {d.label}
                <input
                  value={form.rotation[d.key]}
                  onChange={(e) => set({ rotation: { ...form.rotation, [d.key]: e.target.value } })}
                />
              </label>
            ))}
          </details>
        </>
      )}
    </SectionCard>
  )
}
