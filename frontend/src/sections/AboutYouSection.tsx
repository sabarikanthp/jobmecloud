import { useEffect, useState } from 'react'
import { getUser, saveUser, type UserProfile } from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'

const EMPTY: UserProfile = { name: '', email: '', phone: '', location: '', linkedin_url: '', links: [] }

export default function AboutYouSection({ mode, onSaved }: { mode: SectionMode; onSaved?: () => void | Promise<void> }) {
  const [user, setUser] = useState<UserProfile>(EMPTY)
  const [savedUser, setSavedUser] = useState<UserProfile>(EMPTY)
  const [links, setLinks] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')

  function apply(u: UserProfile) {
    setUser(u)
    setSavedUser(u)
    setLinks(u.links.join('\n'))
  }

  useEffect(() => {
    getUser()
      .then((u) => {
        apply(u)
        setLoaded(true)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  async function save() {
    const saved = await saveUser({
      ...user,
      links: links
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean),
    })
    apply(saved)
    await onSaved?.()
  }

  const set = (k: keyof UserProfile) => (e: { target: { value: string } }) =>
    setUser({ ...user, [k]: e.target.value })

  const summary =
    savedUser.name || savedUser.email ? `${savedUser.name} · ${savedUser.email}` : 'Not filled in yet'

  return (
    <SectionCard title="About you" summary={summary}
      mode={mode}
      onSave={save}
      canSave={loaded && !loadError}
      onCancel={() => apply(savedUser)}
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      {loaded && (
        <>
          <label>
            Name
            <input value={user.name} onChange={set('name')} />
            <span className="help">As you want it to appear on your resume.</span>
          </label>
          <label>
            Email
            <input type="email" value={user.email} onChange={set('email')} />
            <span className="help">Where employers can reach you.</span>
          </label>
          <label>
            Phone
            <input value={user.phone} onChange={set('phone')} />
            <span className="help">Optional. Shown on your resume.</span>
          </label>
          <label>
            City or area
            <input value={user.location} onChange={set('location')} />
            <span className="help">For example, Austin, TX.</span>
          </label>
          <label>
            LinkedIn profile address
            <input value={user.linkedin_url} onChange={set('linkedin_url')} />
            <span className="help">Used on your resume. JobMe never signs in to LinkedIn.</span>
          </label>
          <label>
            Other links (one per line)
            <textarea rows={3} value={links} onChange={(e) => setLinks(e.target.value)} />
            <span className="help">Your website, portfolio or anything else you want on your resume.</span>
          </label>
        </>
      )}
    </SectionCard>
  )
}
