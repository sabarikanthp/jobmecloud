import { useRef, useState } from 'react'
import type { ColumnMapping, ImportCommit, ImportPreview, ImportResult } from '../api.ts'

export interface ImportField {
  key: string
  label: string
  help: string
  required?: boolean
}

interface Props {
  fields: ImportField[]
  preview: (file: File) => Promise<ImportPreview>
  commit: (body: ImportCommit) => Promise<ImportResult>
  /** What the sheet picker's help says, e.g. "Which sheet of the file holds your jobs." */
  sheetHelp: string
  /** Shown under Import while a required column is unchosen. */
  requiredHelp: string
  /** Called with true while a file is uploaded but not yet imported. */
  onPendingChange?: (pending: boolean) => void
  onImported?: () => void | Promise<void>
}

const NONE = '(not in my file)'

/** Upload a .xlsx/.csv, match its columns to fields, preview, then import. */
export default function SpreadsheetImport({
  fields,
  preview: runPreview,
  commit,
  sheetHelp,
  requiredHelp,
  onPendingChange,
  onImported,
}: Props) {
  const [preview, setPreviewState] = useState<ImportPreview | null>(null)
  const [sheetName, setSheetName] = useState('')
  const [mapping, setMapping] = useState<ColumnMapping | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const sheet = preview?.sheets.find((s) => s.name === sheetName) ?? null

  function setPreview(p: ImportPreview | null) {
    setPreviewState(p)
    onPendingChange?.(p !== null)
  }

  function reset() {
    setPreview(null)
    setSheetName('')
    setMapping(null)
  }

  async function upload(file: File) {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const p = await runPreview(file)
      setPreview(p)
      setSheetName(p.sheets[0]?.name ?? '')
      setMapping(p.sheets[0]?.suggested_mapping ?? null)
    } catch (e) {
      reset()
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function pickSheet(name: string) {
    setSheetName(name)
    setMapping(preview?.sheets.find((s) => s.name === name)?.suggested_mapping ?? null)
  }

  async function runImport() {
    if (!preview || !sheet || !mapping) return
    setError('')
    setMessage('')
    setBusy(true)
    try {
      const r = await commit({ upload_id: preview.upload_id, sheet: sheet.name, mapping })
      reset()
      setMessage(r.message)
      await onImported?.()
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Something went wrong.'
      if (msg.startsWith('That upload expired')) reset()
      setError(msg)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const mapped =
    sheet && mapping ? fields.filter((f) => mapping[f.key] != null && sheet.columns.includes(mapping[f.key] as string)) : []
  const canImport = !!mapping && fields.every((f) => !f.required || !!mapping[f.key])

  return (
    <>
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
        <span className="help">A .xlsx or .csv file.</span>
      </label>
      {busy && <p className="muted">Working…</p>}
      {error && <div className="result bad">{error}</div>}
      {message && <div className="result ok">{message}</div>}
      {preview && (
        <p className="help">
          Press Import, or remove the file to stop.{' '}
          <button type="button" className="link" disabled={busy} onClick={reset}>
            Remove file
          </button>
        </p>
      )}

      {preview && sheet && mapping && (
        <>
          {preview.sheets.length > 1 && (
            <label>
              Sheet
              <select value={sheetName} disabled={busy} onChange={(e) => pickSheet(e.target.value)}>
                {preview.sheets.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
              <span className="help">{sheetHelp}</span>
            </label>
          )}
          {fields.map((f) => (
            <label key={f.key}>
              {f.label}
              {f.required ? '*' : ''}
              <select
                value={mapping[f.key] ?? ''}
                disabled={busy}
                onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value || null })}
              >
                <option value="">{NONE}</option>
                {sheet.columns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <span className="help">{f.help}</span>
            </label>
          ))}
          <h4>Preview</h4>
          {sheet.sample_rows.length === 0 || mapped.length === 0 ? (
            <p className="muted">(no rows)</p>
          ) : (
            <table className="stack">
              <thead>
                <tr>
                  {mapped.map((f) => (
                    <th key={f.key}>{f.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sheet.sample_rows.slice(0, 5).map((row, i) => (
                  <tr key={i}>
                    {mapped.map((f) => (
                      <td key={f.key} data-label={f.label}>{row[sheet.columns.indexOf(mapping[f.key] as string)] ?? ''}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="row">
            <button className="primary" disabled={busy || !canImport} onClick={() => void runImport()}>
              Import
            </button>
          </div>
          {!canImport && <span className="help">{requiredHelp}</span>}
        </>
      )}
    </>
  )
}
