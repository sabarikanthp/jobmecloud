import { useEffect, useState } from 'react'
import {
  addWatchlist,
  commitWatchlistImport,
  deleteWatchlist,
  listWatchlist,
  previewWatchlistImport,
  updateWatchlist,
  type DayKey,
  type WatchlistEmployer,
  type WatchlistRow,
} from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'
import SpreadsheetImport, { type ImportField } from '../components/SpreadsheetImport.tsx'
import { DAYS } from './search/form.ts'

const PRIORITIES = [
  { value: 1, label: 'High' },
  { value: 2, label: 'Medium' },
  { value: 3, label: 'Low' },
]
const IMPORT_FIELDS: ImportField[] = [
  { key: 'name', label: 'Employer', help: 'The company name. Required.', required: true },
  { key: 'priority', label: 'Priority', help: 'P1 or High, P2 or Medium, P3 or Low. "Conditional" counts as Low; anything else as Medium.' },
  { key: 'rotation_day', label: 'Day', help: 'The weekday it starts with is used, so "Monday - Downtown" becomes Monday.' },
  { key: 'careers_url', label: 'Careers page', help: 'Used only when the cell holds a web address.' },
]
const priorityLabel = (n: number) => PRIORITIES.find((p) => p.value === n)?.label ?? String(n)
const dayLabel = (d: DayKey | null) => DAYS.find((x) => x.key === d)?.label ?? 'Any'

interface Draft {
  name: string
  priority: number
  url: string
  day: string // '' = any
}
const blankDraft = (): Draft => ({ name: '', priority: 2, url: '', day: '' })
const toDraft = (r: WatchlistRow): Draft => ({
  name: r.name,
  priority: r.priority,
  url: r.careers_url ?? '',
  day: r.rotation_day ?? '',
})
const toBody = (d: Draft): WatchlistEmployer => ({
  name: d.name.trim(),
  priority: d.priority,
  careers_url: d.url.trim() || null,
  rotation_day: (d.day || null) as DayKey | null,
})

function DraftCells({ draft, onChange, label }: { draft: Draft; onChange: (d: Draft) => void; label: string }) {
  return (
    <>
      <td data-label="Employer">
        <input aria-label={`${label}: employer`} value={draft.name} onChange={(e) => onChange({ ...draft, name: e.target.value })} />
      </td>
      <td data-label="Priority">
        <select
          aria-label={`${label}: priority`}
          value={draft.priority}
          onChange={(e) => onChange({ ...draft, priority: Number(e.target.value) })}
        >
          {PRIORITIES.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </td>
      <td data-label="Careers page">
        <input aria-label={`${label}: careers page`} value={draft.url} onChange={(e) => onChange({ ...draft, url: e.target.value })} />
      </td>
      <td data-label="Day">
        <select aria-label={`${label}: day`} value={draft.day} onChange={(e) => onChange({ ...draft, day: e.target.value })}>
          <option value="">Any</option>
          {DAYS.map((d) => (
            <option key={d.key} value={d.key}>
              {d.label}
            </option>
          ))}
        </select>
      </td>
    </>
  )
}

export default function WatchlistSection({ mode, onSaved }: { mode: SectionMode; onSaved?: () => void | Promise<void> }) {
  const [rows, setRows] = useState<WatchlistRow[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [editing, setEditing] = useState<{ id: number; draft: Draft } | null>(null)
  const [adding, setAdding] = useState<Draft>(blankDraft())
  const [busyId, setBusyId] = useState<number | 'add' | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [note, setNote] = useState('')
  const [importing, setImporting] = useState(false)
  const [importPending, setImportPending] = useState(false)

  useEffect(() => {
    listWatchlist()
      .then((r) => {
        setRows(r)
        setLoaded(true)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  // Runs one change against the API; shows the server's message next to the row on failure.
  async function change(key: number | 'add', run: () => Promise<void>) {
    setBusyId(key)
    setNote('')
    setErrors((cur) => ({ ...cur, [key]: '' }))
    try {
      await run()
      setNote('Saved')
    } catch (e) {
      setErrors((cur) => ({ ...cur, [key]: e instanceof Error ? e.message : 'Something went wrong.' }))
    } finally {
      setBusyId(null)
    }
  }

  const add = () =>
    change('add', async () => {
      const row = await addWatchlist(toBody(adding))
      setRows((cur) => [...cur, row])
      setAdding(blankDraft())
    })

  const saveEdit = (id: number, draft: Draft) =>
    change(id, async () => {
      const row = await updateWatchlist(id, toBody(draft))
      setRows((cur) => cur.map((r) => (r.id === id ? row : r)))
      setEditing(null)
    })

  const remove = (id: number) =>
    change(id, async () => {
      await deleteWatchlist(id)
      setRows((cur) => cur.filter((r) => r.id !== id))
      setEditing((cur) => (cur?.id === id ? null : cur))
    })

  async function done() {
    // Every change is already saved, so Save only closes the card (or moves the wizard on).
    await onSaved?.()
  }

  const summary = rows.length ? `${rows.length} ${rows.length === 1 ? 'employer' : 'employers'}` : 'None yet'
  const anyBusy = busyId !== null

  return (
    <SectionCard
      title="Employers to watch"
      tip="JobMe checks these employers' careers pages for new openings."
      summary={summary}
      mode={mode}
      onSave={done}
      canSave={loaded && !loadError && !anyBusy && !importPending}
      saveLabel="Continue"
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      {loaded && (
        <>
          <span className="help">Optional. Companies you would love to work for. Changes here are saved right away.</span>
          <table className="watchlist stack">
            <thead>
              <tr>
                <th>Employer</th>
                <th>Priority</th>
                <th>Careers page</th>
                <th>Day</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const isEditing = editing?.id === r.id
                const busy = busyId === r.id
                return (
                  <tr key={r.id}>
                    {isEditing ? (
                      <DraftCells draft={editing.draft} label={r.name} onChange={(d) => setEditing({ id: r.id, draft: d })} />
                    ) : (
                      <>
                        <td data-label="Employer">{r.name}</td>
                        <td data-label="Priority">{priorityLabel(r.priority)}</td>
                        <td data-label="Careers page">{r.careers_url ?? ''}</td>
                        <td data-label="Day">{dayLabel(r.rotation_day)}</td>
                      </>
                    )}
                    <td>
                      <div className="row">
                        {isEditing ? (
                          <>
                            <button className="primary" disabled={busy} onClick={() => void saveEdit(r.id, editing.draft)}>
                              Save
                            </button>
                            <button disabled={busy} onClick={() => setEditing(null)}>
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button disabled={busy} onClick={() => setEditing({ id: r.id, draft: toDraft(r) })}>
                            Edit
                          </button>
                        )}
                        <button className="danger" disabled={busy} onClick={() => void remove(r.id)}>
                          Remove
                        </button>
                      </div>
                      {errors[r.id] && <div className="result bad">{errors[r.id]}</div>}
                    </td>
                  </tr>
                )
              })}
              <tr>
                <DraftCells draft={adding} label="New employer" onChange={setAdding} />
                <td>
                  <button className="add" disabled={busyId === 'add'} onClick={() => void add()}>
                    Add
                  </button>
                  {errors.add && <div className="result bad">{errors.add}</div>}
                </td>
              </tr>
            </tbody>
          </table>
          {importing ? (
            <>
              <h4>Import from a spreadsheet</h4>
              <SpreadsheetImport
                fields={IMPORT_FIELDS}
                preview={previewWatchlistImport}
                commit={commitWatchlistImport}
                sheetHelp="Which sheet of the file holds your employers."
                requiredHelp="Choose the column for Employer to import."
                onPendingChange={setImportPending}
                onImported={async () => setRows(await listWatchlist())}
              />
              {!importPending && (
                <div className="row">
                  <button onClick={() => setImporting(false)}>Close import</button>
                </div>
              )}
            </>
          ) : (
            <div className="row">
              <button className="add" onClick={() => setImporting(true)}>Import from a spreadsheet</button>
            </div>
          )}
          <p role="status" className="saved-note">
            {mode === 'settings' ? note : ''}
          </p>
        </>
      )}
    </SectionCard>
  )
}
