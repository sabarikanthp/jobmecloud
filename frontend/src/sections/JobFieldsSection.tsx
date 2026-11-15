import { useCallback, useEffect, useState } from 'react'
import {
  createJobField,
  deleteJobField,
  getJobFields,
  updateJobField,
  type JobField,
  type JobFieldType,
} from '../api.ts'

const TYPES: { value: JobFieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'date', label: 'Date' },
  { value: 'choice', label: 'Choice' },
]

function splitOptions(text: string): string[] {
  return text.split(',').map((o) => o.trim()).filter(Boolean)
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong.'
}

export default function JobFieldsSection() {
  const [fields, setFields] = useState<JobField[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [type, setType] = useState<JobFieldType>('text')
  const [options, setOptions] = useState('')
  const [editing, setEditing] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editOptions, setEditOptions] = useState('')
  const [confirming, setConfirming] = useState<number | null>(null)

  const load = useCallback(async () => {
    setFields(await getJobFields())
    setLoaded(true)
  }, [])

  useEffect(() => {
    let live = true
    getJobFields()
      .then((list) => {
        if (!live) return
        setFields(list)
        setLoaded(true)
      })
      .catch((e: unknown) => {
        if (live) setError(errorText(e))
      })
    return () => {
      live = false
    }
  }, [])

  async function act(work: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try {
      await work()
      await load()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function add() {
    await act(async () => {
      await createJobField({
        name,
        type,
        choices: type === 'choice' ? splitOptions(options) : undefined,
      })
      setName('')
      setOptions('')
      setType('text')
    })
  }

  function startEdit(f: JobField) {
    setEditing(f.id)
    setEditName(f.name)
    setEditOptions(f.choices.join(', '))
    setConfirming(null)
  }

  async function saveEdit(f: JobField) {
    await act(async () => {
      await updateJobField(f.id, {
        name: editName,
        choices: f.type === 'choice' ? splitOptions(editOptions) : undefined,
      })
      setEditing(null)
    })
  }

  async function move(i: number, by: -1 | 1) {
    const a = fields[i]
    const b = fields[i + by]
    await act(async () => {
      await updateJobField(a.id, { position: b.position })
      await updateJobField(b.id, { position: a.position })
    })
  }

  async function remove(f: JobField) {
    await act(async () => {
      await deleteJobField(f.id)
      setConfirming(null)
    })
  }

  const summary = !loaded ? '' : fields.length === 0 ? 'No fields yet' : `${fields.length} ${fields.length === 1 ? 'field' : 'fields'}`

  return (
    <section className="card section-card">
      <div className="section-head">
        <h2>Job fields</h2>
        <span className="section-summary muted">{summary}</span>
      </div>
      <p className="help">
        Fields you add show on every job, and you can use them as columns and filters on the Jobs page.
      </p>
      {error && <div className="result bad">{error}</div>}
      {!loaded && !error && <p className="muted">Loading…</p>}
      {loaded && fields.length > 0 && (
        <ul className="plain job-fields" role="list">
          {fields.map((f, i) => (
            <li key={f.id}>
              {editing === f.id ? (
                <div className="row">
                  <label>
                    Name
                    <input value={editName} maxLength={40} onChange={(e) => setEditName(e.target.value)} />
                  </label>
                  {f.type === 'choice' && (
                    <label>
                      Options (separated by commas)
                      <input value={editOptions} onChange={(e) => setEditOptions(e.target.value)} />
                    </label>
                  )}
                  <button className="primary" disabled={busy} onClick={() => void saveEdit(f)}>
                    Save
                  </button>
                  <button disabled={busy} onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="row">
                  <strong>{f.name}</strong>
                  <span className="muted">
                    {TYPES.find((t) => t.value === f.type)?.label}
                    {f.type === 'choice' && f.choices.length > 0 ? `: ${f.choices.join(', ')}` : ''}
                    {' · '}
                    {f.used} {f.used === 1 ? 'job' : 'jobs'}
                  </span>
                  <button aria-label={`Move ${f.name} up`} disabled={busy || i === 0} onClick={() => void move(i, -1)}>
                    Up
                  </button>
                  <button
                    aria-label={`Move ${f.name} down`}
                    disabled={busy || i === fields.length - 1}
                    onClick={() => void move(i, 1)}
                  >
                    Down
                  </button>
                  <button aria-label={`Edit ${f.name}`} disabled={busy} onClick={() => startEdit(f)}>
                    Edit
                  </button>
                  <button
                    className="danger"
                    aria-label={`Delete ${f.name}`}
                    disabled={busy}
                    onClick={() => setConfirming(f.id)}
                  >
                    Delete
                  </button>
                </div>
              )}
              {confirming === f.id && (
                <div className="result" role="alert">
                  <p>
                    Delete {f.name}? {f.used} {f.used === 1 ? 'job has' : 'jobs have'} a value. The values are
                    deleted too.
                  </p>
                  <div className="row">
                    <button className="danger" disabled={busy} onClick={() => void remove(f)}>
                      Delete
                    </button>
                    <button disabled={busy} onClick={() => setConfirming(null)}>
                      Keep
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <h3>Add a field</h3>
      <div className="row">
        <label>
          Name
          <input value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Type
          <select value={type} onChange={(e) => setType(e.target.value as JobFieldType)}>
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        {type === 'choice' && (
          <label>
            Options (separated by commas)
            <input value={options} onChange={(e) => setOptions(e.target.value)} />
          </label>
        )}
        <button className="add" disabled={busy || !name.trim()} onClick={() => void add()}>
          Add field
        </button>
      </div>
    </section>
  )
}
