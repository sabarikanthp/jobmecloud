import { useRef, useState } from 'react'
import {
  sheetImport,
  sheetPreview,
  type JobField,
  type JobFieldType,
  type KeepAs,
  type SheetImportBody,
  type SheetInfo,
  type SheetKind,
  type SheetPreview,
  type SheetReport,
} from '../api.ts'

const KIND_LABELS: Record<SheetKind, string> = {
  jobs: 'Jobs',
  applications: 'Applications & follow-ups',
  contacts: 'Contacts',
}
const STATUSES = [
  'New',
  'Ready',
  'Applied',
  'Interviewing',
  'Offer',
  'Accepted',
  'Skipped',
  'Rejected',
  'Withdrawn',
  'Closed',
]
const TYPES: { value: JobFieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'date', label: 'Date' },
  { value: 'choice', label: 'Choice' },
]
const NONE = '(not in my file)'

/** What to do with a column that is not matched to a JobMe field. */
interface Keep {
  mode: 'ignore' | 'field' | 'new'
  fieldId: number | null
  name: string
  type: JobFieldType
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong.'
}

function countsText(c: SheetReport['counts']): string {
  return `${c.new} new, ${c.updated} updated, ${c.unchanged} already in JobMe, ${c.left_out} left out`
}

interface Props {
  fields: JobField[]
  onClose: () => void
  onImported: () => void | Promise<void>
}

/** Import a workbook: choose the sheet and what it holds, match columns, check, then import. */
export default function SheetImport({ fields, onClose, onImported }: Props) {
  const [preview, setPreview] = useState<SheetPreview | null>(null)
  const [sheetName, setSheetName] = useState('')
  const [kind, setKind] = useState<SheetKind>('jobs')
  const [mapping, setMapping] = useState<Record<string, string | null>>({})
  const [keep, setKeep] = useState<Record<string, Keep>>({})
  const [words, setWords] = useState<Record<string, string>>({})
  const [report, setReport] = useState<SheetReport | null>(null)
  const [checkedKey, setCheckedKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const sheet: SheetInfo | null = preview?.sheets.find((s) => s.name === sheetName) ?? null
  const kindFields = preview ? preview.kinds[kind] : []
  const canKeep = kind !== 'contacts'
  const used = new Set(Object.values(mapping).filter((c): c is string => !!c))
  const required = new Set(kindFields.filter((f) => f.required).map((f) => mapping[f.key]).filter(Boolean))
  // Every column can be kept as a field of your own, except the ones that name the job or contact.
  const spare = sheet ? sheet.columns.filter((c) => c && !required.has(c)) : []
  const missing = kindFields.some((f) => f.required && !mapping[f.key])
  const requiredHelp =
    kind === 'contacts'
      ? "Choose which column holds the contact's name."
      : 'Choose which columns hold the employer and the job title.'
  const badNew = canKeep && spare.some((c) => keep[c]?.mode === 'new' && !keep[c].name.trim())

  function reset() {
    setPreview(null)
    setSheetName('')
    setMapping({})
    setKeep({})
    setWords({})
    setReport(null)
    setCheckedKey('')
  }

  function chooseSheet(s: SheetInfo, k: SheetKind) {
    setSheetName(s.name)
    setKind(k)
    setMapping({ ...s.suggested[k] })
    setKeep({})
    setWords({})
    setReport(null)
    setCheckedKey('')
  }

  async function upload(file: File) {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const p = await sheetPreview(file)
      setPreview(p)
      const first = p.sheets[0]
      if (first) chooseSheet(first, first.guessed_kind)
    } catch (e) {
      reset()
      setError(errorText(e))
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function keepFor(col: string): Keep {
    const info = sheet?.columns_info[col]
    // A column matched to a JobMe field starts on Ignore; a column with no home starts on New custom field.
    const mode = used.has(col) ? 'ignore' : 'new'
    return keep[col] ?? { mode, fieldId: null, name: info?.name ?? col, type: info?.type ?? 'text' }
  }

  function setKeepFor(col: string, patch: Partial<Keep>) {
    setKeep((prev) => ({ ...prev, [col]: { ...keepFor(col), ...patch } }))
    setCheckedKey('')
  }

  function body(overrides: Record<string, string>, dry: boolean): SheetImportBody {
    const keepOut: Record<string, KeepAs> = {}
    if (canKeep) {
      for (const col of spare) {
        const k = keepFor(col)
        if (k.mode === 'field' && k.fieldId !== null) keepOut[col] = { field_id: k.fieldId }
        if (k.mode === 'new') {
          keepOut[col] = {
            new: { name: k.name.trim(), type: k.type, choices: sheet?.columns_info[col]?.choices ?? [] },
          }
        }
      }
    }
    const map: Record<string, string | null> = {}
    for (const f of kindFields) map[f.key] = mapping[f.key] || null
    return {
      upload_id: preview?.upload_id ?? '',
      sheet: sheetName,
      kind,
      mapping: map,
      keep: keepOut,
      status_words: overrides,
      dry_run: dry,
    }
  }

  async function check(overrides: Record<string, string> = words) {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const b = body(overrides, true)
      const r = await sheetImport(b)
      setReport(r)
      setCheckedKey(JSON.stringify({ ...b, dry_run: false }))
    } catch (e) {
      setReport(null)
      setCheckedKey('')
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function runImport() {
    setError('')
    setBusy(true)
    try {
      const r = await sheetImport(body(words, false))
      reset()
      setMessage(r.message)
      await onImported()
    } catch (e) {
      const msg = errorText(e)
      if (msg.startsWith('That upload expired')) reset()
      setError(msg)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function changeWord(word: string, status: string) {
    const next = { ...words, [word.trim().toLowerCase()]: status }
    setWords(next)
    void check(next)
  }

  const currentKey = preview && sheet ? JSON.stringify(body(words, false)) : ''
  const checked = report !== null && checkedKey === currentKey
  const rowsWithWords = report?.words ?? []

  return (
    <section className="card" aria-labelledby="import-heading">
      <div className="section-head">
        <h3 id="import-heading">Import a spreadsheet</h3>
        <button onClick={onClose}>Close</button>
      </div>
      <label>
        Spreadsheet
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.csv"
          disabled={busy}
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void upload(f)
          }}
        />
        <span className="help">A .xlsx or .csv file. Nothing changes until you press Import.</span>
      </label>
      {busy && <p className="muted">Working…</p>}
      {error && <div className="result bad">{error}</div>}
      {message && <div className="result ok">{message}</div>}

      {preview && sheet && (
        <>
          <div className="form-grid">
            {preview.sheets.length > 1 && (
              <label>
                Sheet
                <select
                  value={sheetName}
                  disabled={busy}
                  onChange={(e) => {
                    const s = preview.sheets.find((x) => x.name === e.target.value)
                    if (s) chooseSheet(s, s.guessed_kind)
                  }}
                >
                  {preview.sheets.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              This sheet holds
              <select value={kind} disabled={busy} onChange={(e) => chooseSheet(sheet, e.target.value as SheetKind)}>
                {(Object.keys(KIND_LABELS) as SheetKind[]).map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <h4>Match your columns</h4>
          <div className="form-grid">
            {kindFields.map((f) => (
              <label key={f.key}>
                {f.label}
                {f.required ? '*' : ''}
                <select
                  value={mapping[f.key] ?? ''}
                  disabled={busy}
                  onChange={(e) => {
                    setMapping({ ...mapping, [f.key]: e.target.value || null })
                    setCheckedKey('')
                  }}
                >
                  <option value="">{NONE}</option>
                  {sheet.columns
                    .filter((c) => c)
                    .map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                </select>
                <span className="help">{f.help}</span>
              </label>
            ))}
          </div>

          {canKeep && spare.length > 0 && (
            <>
              <h4>Keep other columns</h4>
              <p className="help">
                Columns with no JobMe field start as a new custom field, so nothing in your file is lost. You can also
                keep a matched column, such as your own status words, as a field. Set a column to Ignore to leave it out.
              </p>
              <div className="form-grid">
                {spare.map((col) => {
                  const k = keepFor(col)
                  const value = k.mode === 'field' ? `f:${k.fieldId}` : k.mode
                  return (
                    <div key={col} className="keep">
                      <label>
                        Keep “{col}” as
                        <select
                          value={value}
                          disabled={busy}
                          onChange={(e) => {
                            const v = e.target.value
                            if (v === 'ignore' || v === 'new') setKeepFor(col, { mode: v, fieldId: null })
                            else setKeepFor(col, { mode: 'field', fieldId: Number(v.slice(2)) })
                          }}
                        >
                          <option value="ignore">Ignore</option>
                          {fields.map((f) => (
                            <option key={f.id} value={`f:${f.id}`}>
                              {f.name}
                            </option>
                          ))}
                          <option value="new">New custom field…</option>
                        </select>
                      </label>
                      {k.mode === 'new' && (
                        <div className="row">
                          <label>
                            Field name
                            <input
                              value={k.name}
                              maxLength={40}
                              onChange={(e) => setKeepFor(col, { name: e.target.value })}
                            />
                          </label>
                          <label>
                            Type
                            <select
                              value={k.type}
                              onChange={(e) => setKeepFor(col, { type: e.target.value as JobFieldType })}
                            >
                              {TYPES.map((t) => (
                                <option key={t.value} value={t.value}>
                                  {t.label}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </>
          )}

          <div className="row">
            <button disabled={busy || missing || badNew} onClick={() => void check()}>
              Check
            </button>
            <button className="primary" disabled={busy || !checked} onClick={() => void runImport()}>
              Import
            </button>
            <button className="link" disabled={busy} onClick={reset}>
              Remove file
            </button>
          </div>
          {missing && <span className="help">{requiredHelp}</span>}
          {!missing && !checked && <span className="help">Press Check to see what Import will do.</span>}

          {report && (
            <div className="check-result" aria-live="polite">
              <h4>What Import will do</h4>
              <p>
                <strong>{countsText(report.counts)}</strong>
              </p>
              {report.sample.length > 0 && (
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Row</th>
                      <th scope="col">Employer or name</th>
                      <th scope="col">Title</th>
                      <th scope="col">Result</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.sample.map((r) => (
                      <tr key={r.row}>
                        <td>{r.row}</td>
                        <td>{r.employer}</td>
                        <td>{r.title}</td>
                        <td>{r.action}</td>
                        <td>{r.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {rowsWithWords.length > 0 && (
                <>
                  <h4>Status words</h4>
                  <p className="help">Choose the JobMe status for each word in your file. Words set to Don't set are left to the next column, or land as New.</p>
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Word in your file</th>
                        <th scope="col">Rows</th>
                        <th scope="col">JobMe status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rowsWithWords.map((w) => (
                        <tr key={w.word}>
                          <td>{w.word}</td>
                          <td>{w.count}</td>
                          <td>
                            <select
                              aria-label={`Status for ${w.word}`}
                              value={w.status}
                              disabled={busy}
                              onChange={(e) => changeWord(w.word, e.target.value)}
                            >
                              <option value="">Don't set</option>
                              {STATUSES.map((s) => (
                                <option key={s} value={s}>
                                  {s}
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
              {report.attention.length > 0 && (
                <details>
                  <summary>
                    {report.attention.length} {report.attention.length === 1 ? 'row needs' : 'rows need'} a look
                  </summary>
                  <ul>
                    {report.attention.map((a, i) => (
                      <li key={i}>
                        {a.row > 0 ? `Row ${a.row}: ` : ''}
                        {a.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}
