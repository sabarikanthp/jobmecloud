import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  addJob,
  fmtDate,
  getJobFacets,
  getJobFields,
  listJobs,
  type JobField,
  type JobListParams,
  type JobRow,
} from '../api.ts'
import { todayISO } from '../dates.ts'
import ColumnsPicker from '../components/ColumnsPicker.tsx'
import JobLink from '../components/JobLink.tsx'
import SheetImport from '../components/SheetImport.tsx'
import StatusBadge from '../components/StatusBadge.tsx'
import { useNav } from '../nav.tsx'
import ContactsTab from './ContactsTab.tsx'
import JobPage from './JobPage.tsx'
import { formatPay } from './jobFormat.ts'
import { loadColumns, saveColumns, type BuiltinColumn, type ColumnChoice } from './jobColumns.ts'

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
const PAGE_SIZE = 50
const STORAGE_KEY = 'jobmecloud.jobs.filters'

type SortKey = NonNullable<JobListParams['sort']>

interface Filters {
  status: string
  q: string
  source: string
  from: string
  to: string
  followup: 'any' | 'yes' | 'no'
  /** Custom choice filters: field id (as text) to the chosen value. */
  cf: Record<string, string>
  sort: SortKey
  dir: 'asc' | 'desc'
}

const DEFAULTS: Filters = {
  status: '',
  q: '',
  source: '',
  from: '',
  to: '',
  followup: 'any',
  cf: {},
  sort: 'first_seen',
  dir: 'desc',
}

function loadFilters(): Filters {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) {
      const p: unknown = JSON.parse(raw)
      if (p === null || typeof p !== 'object' || Array.isArray(p)) return DEFAULTS
      const o = p as Record<string, unknown>
      const text = (v: unknown, d: string) => (typeof v === 'string' ? v.slice(0, 200) : d)
      const date = (v: unknown) => (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : '')
      const sorts: SortKey[] = ['first_seen', 'match', 'employer', 'status', 'applied']
      const followups: Filters['followup'][] = ['any', 'yes', 'no']
      const cf: Record<string, string> = {}
      if (o.cf !== null && typeof o.cf === 'object' && !Array.isArray(o.cf)) {
        for (const [k, v] of Object.entries(o.cf as Record<string, unknown>)) {
          if (/^\d+$/.test(k) && typeof v === 'string' && v) cf[k] = v.slice(0, 200)
        }
      }
      const field = typeof o.sort === 'string' && /^field:\d+$/.test(o.sort) ? (o.sort as SortKey) : null
      return {
        // Older versions stored a `statuses` array (and minScore/flag); those keys are ignored,
        // except that an old array maps to its first valid status. Unknown values become All.
        status: STATUSES.includes(o.status as string)
          ? (o.status as string)
          : Array.isArray(o.statuses)
            ? (STATUSES.find((x) => (o.statuses as unknown[]).includes(x)) ?? '')
            : '',
        q: text(o.q, ''),
        source: text(o.source, ''),
        from: date(o.from),
        to: date(o.to),
        followup: followups.find((x) => x === o.followup) ?? DEFAULTS.followup,
        cf,
        sort: field ?? sorts.find((x) => x === o.sort) ?? DEFAULTS.sort,
        dir: o.dir === 'asc' || o.dir === 'desc' ? o.dir : DEFAULTS.dir,
      }
    }
  } catch {
    /* storage blocked or bad data */
  }
  return DEFAULTS
}

function saveFilters(f: Filters) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(f))
  } catch {
    /* storage blocked */
  }
}

function toParams(f: Filters, offset: number, fieldIds: number[], cf: Record<string, string>): JobListParams {
  return {
    status: f.status ? [f.status] : undefined,
    q: f.q.trim() || undefined,
    source: f.source || undefined,
    from: f.from || undefined,
    to: f.to || undefined,
    has_followup: f.followup === 'any' ? undefined : f.followup === 'yes',
    fields: fieldIds.length > 0 ? fieldIds : undefined,
    cf: Object.entries(cf).map(([id, v]) => `${id}:${v}`),
    sort: f.sort,
    dir: f.dir,
    limit: PAGE_SIZE,
    offset,
  }
}

function isFiltered(f: Filters): boolean {
  return (
    f.status !== '' ||
    f.q.trim() !== '' ||
    f.source !== '' ||
    f.from !== '' ||
    f.to !== '' ||
    f.followup !== 'any' ||
    Object.keys(f.cf).length > 0
  )
}

const BUILTIN_LABELS: Record<BuiltinColumn, string> = {
  pay: 'Pay',
  location: 'Location',
  work_mode: 'Work mode',
  link: 'Link',
  requisition: 'Requisition',
}

function builtinCell(b: BuiltinColumn, r: JobRow) {
  switch (b) {
    case 'pay':
      return r.pay_min == null && r.pay_max == null ? '' : formatPay(r.pay_min, r.pay_max)
    case 'location':
      return r.location ?? ''
    case 'work_mode':
      return r.work_mode ?? ''
    case 'requisition':
      return r.requisition_id ?? ''
    case 'link':
      return r.apply_url ? (
        <a href={r.apply_url} target="_blank" rel="noreferrer">
          Open
        </a>
      ) : (
        ''
      )
  }
}

export default function Jobs() {
  const { jobId } = useNav()
  const [tab, setTab] = useState<'jobs' | 'contacts'>('jobs')

  if (jobId !== null) return <JobPage key={jobId} id={jobId} />

  return (
    <div>
      <h1>Jobs</h1>
      <div className="tabs" role="tablist" aria-label="Jobs and contacts">
        <button
          role="tab"
          id="tab-jobs"
          aria-selected={tab === 'jobs'}
          aria-controls="panel-jobs"
          className={tab === 'jobs' ? 'tab active' : 'tab'}
          onClick={() => setTab('jobs')}
        >
          Jobs
        </button>
        <button
          role="tab"
          id="tab-contacts"
          aria-selected={tab === 'contacts'}
          aria-controls="panel-contacts"
          className={tab === 'contacts' ? 'tab active' : 'tab'}
          onClick={() => setTab('contacts')}
        >
          Contacts
        </button>
      </div>
      {tab === 'jobs' ? (
        <div role="tabpanel" id="panel-jobs" aria-labelledby="tab-jobs">
          <JobsTab />
        </div>
      ) : (
        <div role="tabpanel" id="panel-contacts" aria-labelledby="tab-contacts">
          <ContactsTab />
        </div>
      )}
    </div>
  )
}

function JobsTab() {
  const { openJob } = useNav()
  const [f, setF] = useState<Filters>(loadFilters)
  const [debounced, setDebounced] = useState<Filters>(f)
  const [offset, setOffset] = useState(0)
  const [rows, setRows] = useState<JobRow[]>([])
  const [total, setTotal] = useState(0)
  const [settledKey, setSettledKey] = useState('')
  const [loadedOnce, setLoadedOnce] = useState(false)
  const [error, setError] = useState('')
  const [sources, setSources] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const [importing, setImporting] = useState(false)
  const [version, setVersion] = useState(0)
  const [fields, setFields] = useState<JobField[]>([])
  const [choice, setChoice] = useState<ColumnChoice>(loadColumns)
  const latest = useRef(0)

  function update(patch: Partial<Filters>) {
    setF((prev) => ({ ...prev, ...patch }))
    setOffset(0)
  }

  useEffect(() => {
    saveFilters(f)
    const t = setTimeout(() => setDebounced(f), 300)
    return () => clearTimeout(t)
  }, [f])

  useEffect(() => {
    getJobFields()
      .then(setFields)
      .catch(() => setFields([]))
  }, [])

  async function afterImport() {
    setVersion((v) => v + 1)
    try {
      const next = await getJobFields()
      // Fields the import just created show up as columns, so the new data is visible at once.
      const known = new Set(fields.map((x) => x.id))
      const fresh = next.filter((x) => !known.has(x.id)).map((x) => x.id)
      if (fresh.length > 0) chooseColumns({ ...choice, columns: [...choice.columns, ...fresh] })
      setFields(next)
    } catch {
      /* the list still reloads */
    }
  }

  function chooseColumns(c: ColumnChoice) {
    setChoice(c)
    saveColumns(c)
  }

  useEffect(() => {
    getJobFacets()
      .then((x) => setSources(x.sources))
      .catch(() => setSources([]))
  }, [])

  // A field that was deleted simply stops showing; its saved id is ignored.
  const shown = fields.filter((x) => choice.columns.includes(x.id))
  const filterFields = fields.filter((x) => x.type === 'choice' && choice.filters.includes(x.id))
  // A choice filter counts only while its dropdown is showing and still offers that value.
  const activeCf = (cf: Record<string, string>) =>
    Object.fromEntries(
      Object.entries(cf).filter(([id, v]) => filterFields.some((x) => String(x.id) === id && x.choices.includes(v))),
    )
  const key = JSON.stringify(toParams(debounced, offset, shown.map((x) => x.id), activeCf(debounced.cf)))
  const fetchKey = `${key}#${version}`
  const loading = settledKey !== fetchKey

  useEffect(() => {
    const id = ++latest.current
    listJobs(JSON.parse(key) as JobListParams)
      .then((res) => {
        if (id !== latest.current) return
        setRows(res.rows)
        setTotal(res.total)
        setError('')
        setLoadedOnce(true)
        setSettledKey(fetchKey)
      })
      .catch((e: Error) => {
        if (id !== latest.current) return
        setError(e.message)
        setSettledKey(fetchKey)
      })
  }, [key, fetchKey])

  function sortBy(key: SortKey) {
    if (f.sort === key) update({ dir: f.dir === 'asc' ? 'desc' : 'asc' })
    else update({ sort: key, dir: key === 'employer' || key === 'status' || key.startsWith('field:') ? 'asc' : 'desc' })
  }

  function sortHeader(key: SortKey, label: string) {
    const active = f.sort === key
    return (
      <th scope="col" aria-sort={active ? (f.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
        <button className="link sort-btn" onClick={() => sortBy(key)}>
          {label}
          {active ? (f.dir === 'asc' ? ' ▲' : ' ▼') : ''}
        </button>
      </th>
    )
  }

  const today = todayISO()
  const first = total === 0 ? 0 : offset + 1
  const last = Math.min(offset + PAGE_SIZE, total)
  const filtered = isFiltered({ ...debounced, cf: activeCf(debounced.cf) })

  return (
    <div>
      <div className="row">
        <button className="add" onClick={() => setAdding((a) => !a)}>
          Add a job
        </button>
        <button onClick={() => setImporting((i) => !i)}>Import</button>
      </div>
      {adding && <AddJobForm onCancel={() => setAdding(false)} onAdded={openJob} />}
      {importing && (
        <SheetImport fields={fields} onClose={() => setImporting(false)} onImported={afterImport} />
      )}

      <div className="card filter-bar">
        <div className="filter-row">
          <label>
            Status
            <select value={f.status} onChange={(e) => update({ status: e.target.value })}>
              <option value="">All</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label>
            Search Text
            <input
              type="text"
              placeholder="Employer or title"
              value={f.q}
              onChange={(e) => update({ q: e.target.value })}
            />
          </label>
          <label>
            Source
            <select value={f.source} onChange={(e) => update({ source: e.target.value })}>
              <option value="">Any source</option>
              {sources.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label>
            Found from
            <input type="date" value={f.from} onChange={(e) => update({ from: e.target.value })} />
          </label>
          <label>
            Found to
            <input type="date" value={f.to} onChange={(e) => update({ to: e.target.value })} />
          </label>
          <label>
            Has an open follow-up
            <select
              value={f.followup}
              onChange={(e) => update({ followup: e.target.value as Filters['followup'] })}
            >
              <option value="any">Any</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
          {filterFields.map((x) => (
            <label key={x.id}>
              {x.name}
              <select
                value={f.cf[String(x.id)] ?? ''}
                onChange={(e) => {
                  const next = { ...f.cf }
                  if (e.target.value) next[String(x.id)] = e.target.value
                  else delete next[String(x.id)]
                  update({ cf: next })
                }}
              >
                <option value="">All</option>
                {x.choices.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <button
            onClick={() => {
              setF({ ...DEFAULTS, sort: f.sort, dir: f.dir })
              setOffset(0)
            }}
          >
            Clear filters
          </button>
        </div>
      </div>

      <ColumnsPicker fields={fields} choice={choice} onChange={chooseColumns} />

      {error && <div className="result bad">{error}</div>}
      {loading && <p className="loading">Loading…</p>}

      {loadedOnce && total === 0 && !loading && !error && (
        <p className="muted">
          {filtered ? 'No jobs match these filters.' : 'No jobs yet. Press Run now on Today, or add one by hand.'}
        </p>
      )}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="jobs-table">
            <thead>
              <tr>
                {sortHeader('employer', 'Employer')}
                <th scope="col">Title</th>
                {sortHeader('status', 'Status')}
                {sortHeader('match', 'Match %')}
                {sortHeader('applied', 'Applied')}
                <th scope="col">Response</th>
                {sortHeader('first_seen', 'Found')}
                <th scope="col">Source</th>
                <th scope="col">Docs</th>
                {choice.builtin.map((b) => (
                  <th key={b} scope="col">
                    {BUILTIN_LABELS[b]}
                  </th>
                ))}
                {shown.map((x) => sortHeader(`field:${x.id}`, x.name))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <JobLink id={r.id}>{r.employer}</JobLink>
                  </td>
                  <td>
                    <JobLink id={r.id}>{r.title}</JobLink>
                    {r.next_followup_due && (
                      <div className={r.next_followup_due < today ? 'followup-mark overdue' : 'followup-mark'}>
                        Follow-up due {fmtDate(r.next_followup_due)}
                        {r.next_followup_due < today ? ' (overdue)' : ''}
                      </div>
                    )}
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td>{r.match_score == null ? '' : `${r.match_score}%`}</td>
                  <td>{fmtDate(r.applied_date)}</td>
                  <td>{fmtDate(r.first_response_date)}</td>
                  <td>{fmtDate(r.first_seen_date)}</td>
                  <td>
                    {r.source}
                    {r.linkedin && <span className="chip">LinkedIn</span>}
                  </td>
                  <td>{r.docs_ready && <span className="docs-mark">Docs</span>}</td>
                  {choice.builtin.map((b) => (
                    <td key={b}>{builtinCell(b, r)}</td>
                  ))}
                  {shown.map((x) => {
                    const v = r.fields?.[String(x.id)] ?? ''
                    return <td key={x.id}>{x.type === 'date' ? fmtDate(v || null) : v}</td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > 0 && (
        <div className="row pager">
          <span>
            Showing {first}-{last} of {total}
          </span>
          <button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            Previous
          </button>
          <button disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next
          </button>
        </div>
      )}
    </div>
  )
}

function AddJobForm({ onCancel, onAdded }: { onCancel: () => void; onAdded: (id: number) => void }) {
  const [employer, setEmployer] = useState('')
  const [title, setTitle] = useState('')
  const [link, setLink] = useState('')
  const [location, setLocation] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await addJob({
        employer: employer.trim(),
        title: title.trim(),
        apply_url: link.trim() || null,
        location: location.trim() || null,
        notes: notes.trim() || null,
      })
      onAdded(res.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>Add a job</h3>
      <div className="form-grid">
        <label>
          Employer
          <input type="text" value={employer} onChange={(e) => setEmployer(e.target.value)} />
        </label>
        <label>
          Job title
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Link
          <input type="text" value={link} onChange={(e) => setLink(e.target.value)} />
        </label>
        <label>
          Location
          <input type="text" value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
        <label className="span-all">
          Notes
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
        </label>
      </div>
      {error && <div className="result bad">{error}</div>}
      <div className="row">
        <button type="submit" className="add" disabled={busy}>
          Add a job
        </button>
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  )
}
