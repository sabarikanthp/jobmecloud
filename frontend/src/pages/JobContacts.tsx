import { useState, type FormEvent } from 'react'
import { deleteContact, saveContact, type ContactRow, type JobRow } from '../api.ts'
import { AddFollowUpForm } from './JobFollowUps.tsx'
import { errorText } from './jobFormat.ts'

const RELATIONSHIPS = ['Recruiter', 'Hiring manager', 'Referral', 'Colleague', 'Other']
const CONTACT_STATUSES = ['To contact', 'Contacted', 'Replied', 'Meeting set', 'Referred', 'No response']

// The allowed values plus a not-set choice; a legacy stored value stays selectable so editing never blanks it.
function Options({ values, current }: { values: string[]; current: string }) {
  return (
    <>
      <option value="">Not set</option>
      {current && !values.includes(current) && <option value={current}>{current}</option>}
      {values.map((v) => (
        <option key={v} value={v}>
          {v}
        </option>
      ))}
    </>
  )
}

// With `jobs` given (the Contacts tab) the form also has a free-text employer and an optional Job select.
export function ContactForm({
  jobId,
  contact,
  jobs,
  onSaved,
  onCancel,
}: {
  jobId: number | null
  contact: ContactRow | null
  jobs?: JobRow[]
  onSaved: () => void | Promise<void>
  onCancel: () => void
}) {
  const id = `contact-${contact?.id ?? 'new'}`
  const [employer, setEmployer] = useState(contact?.employer ?? '')
  const [pickedJob, setPickedJob] = useState(contact ? (contact.job_id === null ? '' : String(contact.job_id)) : '')
  const [name, setName] = useState(contact?.name ?? '')
  const [role, setRole] = useState(contact?.role ?? '')
  const [relationship, setRelationship] = useState(contact?.relationship ?? '')
  const [status, setStatus] = useState(contact?.status ?? '')
  const [link, setLink] = useState(contact?.link ?? '')
  const [notes, setNotes] = useState(contact?.notes ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await saveContact(contact?.id ?? null, {
        name: name.trim(),
        job_id: jobs ? (pickedJob ? Number(pickedJob) : null) : contact ? contact.job_id : jobId,
        employer: jobs ? employer.trim() || null : (contact?.employer ?? null),
        role: role.trim() || null,
        relationship: relationship.trim() || null,
        status: status.trim() || null,
        link: link.trim() || null,
        notes: notes.trim() || null,
      })
      await onSaved()
      onCancel()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="inline-form" onSubmit={(e) => void submit(e)}>
      <div className="field">
        <label htmlFor={`${id}-name`}>Name</label>
        <input id={`${id}-name`} type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-role`}>Role</label>
        <input id={`${id}-role`} type="text" value={role} onChange={(e) => setRole(e.target.value)} />
      </div>
      {jobs && (
        <>
          <div className="field">
            <label htmlFor={`${id}-employer`}>Employer</label>
            <input id={`${id}-employer`} type="text" value={employer} onChange={(e) => setEmployer(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor={`${id}-job`}>Job (optional)</label>
            <select id={`${id}-job`} value={pickedJob} onChange={(e) => setPickedJob(e.target.value)}>
              <option value="">No job</option>
              {contact?.job_id != null && !jobs.some((j) => j.id === contact.job_id) && (
                <option value={String(contact.job_id)}>{contact.job_title ?? `Job ${contact.job_id}`}</option>
              )}
              {jobs.map((j) => (
                <option key={j.id} value={String(j.id)}>
                  {j.employer} - {j.title}
                </option>
              ))}
            </select>
          </div>
        </>
      )}
      <div className="field">
        <label htmlFor={`${id}-rel`}>Relationship</label>
        <select id={`${id}-rel`} value={relationship} onChange={(e) => setRelationship(e.target.value)}>
          <Options values={RELATIONSHIPS} current={relationship} />
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${id}-status`}>Status</label>
        <select id={`${id}-status`} value={status} onChange={(e) => setStatus(e.target.value)}>
          <Options values={CONTACT_STATUSES} current={status} />
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${id}-link`}>Link</label>
        <input id={`${id}-link`} type="text" value={link} onChange={(e) => setLink(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-notes`}>Notes</label>
        <textarea id={`${id}-notes`} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>
      {error && <div className="result bad">{error}</div>}
      <div className="row">
        <button type="submit" className={contact ? 'primary' : 'add'} disabled={busy || !name.trim()}>
          {contact ? 'Save contact' : 'Add a contact'}
        </button>
        <button type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function ContactItem({
  jobId,
  contact,
  onChanged,
}: {
  jobId: number
  contact: ContactRow
  onChanged: () => void | Promise<void>
}) {
  const [mode, setMode] = useState<'view' | 'edit' | 'followup'>('view')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

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

  return (
    <li className="job-item">
      <div>
        <strong>{contact.name || 'Unnamed contact'}</strong>
        {[contact.role, contact.relationship, contact.status]
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
        {confirming && (
          <>
            <span>Delete?</span>
            <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>
              Yes
            </button>
            <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
              No
            </button>
          </>
        )}
      </div>
      {mode === 'edit' && (
        <ContactForm jobId={jobId} contact={contact} onSaved={onChanged} onCancel={() => setMode('view')} />
      )}
      {mode === 'followup' && (
        <AddFollowUpForm
          jobId={jobId}
          contactId={contact.id}
          idPrefix={`contact-fu-${contact.id}`}
          onAdded={onChanged}
          onCancel={() => setMode('view')}
        />
      )}
      {error && <div className="result bad">{error}</div>}
    </li>
  )
}

export default function JobContacts({
  jobId,
  contacts,
  onChanged,
}: {
  jobId: number
  contacts: ContactRow[]
  onChanged: () => void | Promise<void>
}) {
  const [adding, setAdding] = useState(false)
  return (
    <section className="card" aria-labelledby="job-contacts">
      <h2 id="job-contacts">Contacts</h2>
      {contacts.length === 0 && <p className="muted">No contacts for this job yet.</p>}
      {contacts.length > 0 && (
        <ul className="job-items">
          {contacts.map((c) => (
            <ContactItem key={c.id} jobId={jobId} contact={c} onChanged={onChanged} />
          ))}
        </ul>
      )}
      {!adding && (
        <div className="row">
          <button type="button" className="add" onClick={() => setAdding(true)}>
            Add a contact
          </button>
        </div>
      )}
      {adding && <ContactForm jobId={jobId} contact={null} onSaved={onChanged} onCancel={() => setAdding(false)} />}
    </section>
  )
}
