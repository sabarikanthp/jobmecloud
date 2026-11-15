import { useEffect, useRef, useState } from 'react'
import {
  deleteContact,
  listContacts,
  listFollowUps,
  listJobs,
  type ContactRow,
  type FollowUpRow,
  type JobRow,
} from '../api.ts'
import FollowUpList from '../components/FollowUpList.tsx'
import { useNav } from '../nav.tsx'
import { ContactForm } from './JobContacts.tsx'
import { AddFollowUpForm } from './JobFollowUps.tsx'
import { errorText } from './jobFormat.ts'

function ContactCard({
  contact,
  jobs,
  onChanged,
}: {
  contact: ContactRow
  jobs: JobRow[]
  onChanged: () => void | Promise<void>
}) {
  const { openJob } = useNav()
  const [mode, setMode] = useState<'view' | 'edit' | 'followup'>('view')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [followUps, setFollowUps] = useState<FollowUpRow[]>([])
  const [fuError, setFuError] = useState('')
  const [tick, setTick] = useState(0)
  const latest = useRef(0)
  const contactId = contact.id

  useEffect(() => {
    const id = ++latest.current
    listFollowUps({ contact_id: contactId })
      .then((rows) => {
        if (id !== latest.current) return
        setFollowUps(rows.filter((r) => r.status === 'Open' || r.status === 'Snoozed'))
        setFuError('')
      })
      .catch((e: unknown) => {
        if (id !== latest.current) return
        setFuError(errorText(e))
      })
  }, [contactId, tick, contact.open_followups])

  const refresh = async () => {
    setTick((t) => t + 1)
    await onChanged()
  }

  async function remove() {
    setBusy(true)
    setError('')
    try {
      await deleteContact(contact.id)
      await onChanged()
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
      setConfirming(false)
    }
  }

  const jobId = contact.job_id
  return (
    <li className="job-item">
      <div>
        <strong>{contact.name || 'Unnamed contact'}</strong>
        {[contact.role, contact.employer, contact.relationship, contact.status]
          .filter(Boolean)
          .map((t) => ` · ${t}`)
          .join('')}
      </div>
      {contact.link && (
        <div>
          <a href={contact.link} target="_blank" rel="noreferrer">
            {contact.link}
          </a>
        </div>
      )}
      {contact.notes && <div className="help">{contact.notes}</div>}
      <div>
        {jobId !== null && (
          <>
            <button type="button" className="link" onClick={() => openJob(jobId)}>
              {contact.job_title ?? `Job ${jobId}`}
            </button>
            {' · '}
          </>
        )}
        {contact.open_followups} open follow-up{contact.open_followups === 1 ? '' : 's'}
      </div>
      <div className="row">
        <button type="button" disabled={busy} onClick={() => setMode(mode === 'followup' ? 'view' : 'followup')}>
          Add follow-up
        </button>
        <button type="button" disabled={busy} onClick={() => setMode(mode === 'edit' ? 'view' : 'edit')}>
          Edit
        </button>
        {!confirming && (
          <button type="button" className="danger" disabled={busy} onClick={() => setConfirming(true)}>
            Delete
          </button>
        )}
      </div>
      {confirming && (
        <div className="row">
          <span>Delete {contact.name || 'this contact'}? Open follow-ups for this contact will be cancelled.</span>
          <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>
            Delete
          </button>
          <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
            Keep
          </button>
        </div>
      )}
      {mode === 'edit' && (
        <ContactForm jobId={null} contact={contact} jobs={jobs} onSaved={onChanged} onCancel={() => setMode('view')} />
      )}
      {mode === 'followup' && (
        <AddFollowUpForm
          jobId={jobId}
          contactId={contact.id}
          idPrefix={`contacts-fu-${contact.id}`}
          onAdded={refresh}
          onCancel={() => setMode('view')}
        />
      )}
      {followUps.length > 0 && <FollowUpList rows={followUps} onChanged={refresh} compact />}
      {fuError && <div className="result bad">{fuError}</div>}
      {error && <div className="result bad">{error}</div>}
    </li>
  )
}

export default function ContactsTab() {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [rows, setRows] = useState<ContactRow[]>([])
  const [jobs, setJobs] = useState<JobRow[]>([])
  const [loadedOnce, setLoadedOnce] = useState(false)
  const [settledKey, setSettledKey] = useState('')
  const [tick, setTick] = useState(0)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const latest = useRef(0)

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])

  const key = `${debounced}|${tick}`
  const loading = settledKey !== key

  useEffect(() => {
    const id = ++latest.current
    listContacts({ q: debounced || undefined })
      .then((res) => {
        if (id !== latest.current) return
        setRows(res)
        setError('')
        setLoadedOnce(true)
        setSettledKey(key)
      })
      .catch((e: unknown) => {
        if (id !== latest.current) return
        setError(errorText(e))
        setSettledKey(key)
      })
  }, [debounced, key])

  const load = () => setTick((t) => t + 1)

  useEffect(() => {
    let live = true
    listJobs({ sort: 'first_seen', dir: 'desc', limit: 100 })
      .then((res) => {
        if (live) setJobs(res.rows)
      })
      .catch(() => {
        if (live) setJobs([])
      })
    return () => {
      live = false
    }
  }, [])

  return (
    <div>
      <div className="row">
        <button type="button" className="add" onClick={() => setAdding((a) => !a)}>
          Add a contact
        </button>
      </div>
      {adding && (
        <div className="card">
          <h3>Add a contact</h3>
          <ContactForm jobId={null} contact={null} jobs={jobs} onSaved={load} onCancel={() => setAdding(false)} />
        </div>
      )}

      <div className="card filter-bar">
        <label>
          Search
          <input
            type="text"
            placeholder="Name, employer or role"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
      </div>

      {error && <div className="result bad">{error}</div>}
      {loading && <p className="loading">Loading…</p>}

      {loadedOnce && rows.length === 0 && !loading && !error && (
        <p className="muted">
          {debounced
            ? 'No contacts match this search.'
            : 'No contacts yet. Add a recruiter, a referral or anyone who can help.'}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="job-items">
          {rows.map((c) => (
            <ContactCard key={c.id} contact={c} jobs={jobs} onChanged={load} />
          ))}
        </ul>
      )}
    </div>
  )
}
