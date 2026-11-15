import { useEffect, useState } from 'react'
import { fmtDate, getJobFields, setJobFields, type JobDetail, type JobField } from '../api.ts'
import { useNav } from '../nav.tsx'
import { errorText } from './jobFormat.ts'

function show(field: JobField, value: string): string {
  return field.type === 'date' ? fmtDate(value) : value
}

function ValueInput({
  field,
  value,
  onChange,
  label,
}: {
  field: JobField
  value: string
  onChange: (v: string) => void
  label: string
}) {
  if (field.type === 'choice') {
    return (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {field.choices.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    )
  }
  return (
    <input
      aria-label={label}
      type={field.type === 'date' ? 'date' : 'text'}
      inputMode={field.type === 'number' ? 'decimal' : undefined}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

/** The job's custom fields: the ones with a value, each editable, and a way to add another. */
export default function JobDetails({ job, onChanged }: { job: JobDetail; onChanged: () => void | Promise<void> }) {
  const { go } = useNav()
  const [fields, setFields] = useState<JobField[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState<number | ''>('')
  const [newValue, setNewValue] = useState('')

  useEffect(() => {
    let live = true
    getJobFields()
      .then((list) => {
        if (live) setFields(list)
      })
      .catch((e: unknown) => {
        if (live) setError(errorText(e))
      })
    return () => {
      live = false
    }
  }, [])

  async function save(id: number, value: string) {
    setBusy(true)
    setError('')
    try {
      await setJobFields(job.id, { [id]: value })
      setEditing(null)
      setAdding('')
      setNewValue('')
      await onChanged()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const has = (f: JobField) => job.fields[String(f.id)] !== undefined
  const filled = (fields ?? []).filter(has)
  const empty = (fields ?? []).filter((f) => !has(f))
  const addField = empty.find((f) => f.id === adding)

  return (
    <section className="card" aria-labelledby="job-details">
      <h2 id="job-details">Details</h2>
      {error && <div className="result bad">{error}</div>}
      {fields === null && !error && <p className="muted">Loading…</p>}
      {fields !== null && fields.length === 0 && (
        <p className="help">
          No extra fields yet.{' '}
          <button type="button" className="link" onClick={() => go('Settings')}>
            Add a field in Settings
          </button>
        </p>
      )}
      {filled.length > 0 && (
        <dl className="details">
          {filled.map((f) => {
            const value = job.fields[String(f.id)]
            return (
              <div key={f.id} className="detail">
                <dt>{f.name}</dt>
                {editing === f.id ? (
                  <dd className="row">
                    <ValueInput field={f} value={draft} onChange={setDraft} label={f.name} />
                    <button className="primary" disabled={busy} onClick={() => void save(f.id, draft)}>
                      Save
                    </button>
                    <button disabled={busy} onClick={() => setEditing(null)}>
                      Cancel
                    </button>
                  </dd>
                ) : (
                  <dd className="row">
                    <span>{show(f, value)}</span>
                    <button
                      aria-label={`Edit ${f.name}`}
                      disabled={busy}
                      onClick={() => {
                        setEditing(f.id)
                        setDraft(value)
                      }}
                    >
                      Edit
                    </button>
                    <button
                      className="link"
                      aria-label={`Clear ${f.name}`}
                      disabled={busy}
                      onClick={() => void save(f.id, '')}
                    >
                      Clear
                    </button>
                  </dd>
                )}
              </div>
            )
          })}
        </dl>
      )}
      {empty.length > 0 && (
        <div className="row">
          <label>
            Add detail
            <select
              value={adding}
              onChange={(e) => {
                setAdding(e.target.value ? Number(e.target.value) : '')
                setNewValue('')
              }}
            >
              <option value="">Choose a field…</option>
              {empty.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>
          {addField && (
            <>
              <ValueInput field={addField} value={newValue} onChange={setNewValue} label={`${addField.name} value`} />
              <button className="add" disabled={busy || !newValue.trim()} onClick={() => void save(addField.id, newValue)}>
                Add
              </button>
            </>
          )}
        </div>
      )}
    </section>
  )
}
