import { useEffect, useState } from 'react'
import { approveOAuth, getOAuthClient, type OAuthClientInfo } from '../api.ts'
import { nav } from '../auth.ts'

type Scope = 'read' | 'readwrite'

// The connector (ChatGPT, Claude) sends the browser here, as "#/connect?client_id=...&redirect_uri=...&state=...".
// The query is read from the part after the "#", which survives the trip to the sign-in page.
function readRequest() {
  const query = new URLSearchParams(window.location.hash.split('?')[1] ?? '')
  return {
    clientId: query.get('client_id') ?? '',
    redirectUri: query.get('redirect_uri') ?? '',
    state: query.get('state') ?? '',
    challenge: query.get('code_challenge') ?? '',
  }
}

export default function Connect() {
  const [req] = useState(readRequest)
  const valid = Boolean(req.clientId && req.redirectUri && req.challenge)
  const [app, setApp] = useState<OAuthClientInfo | null>(null)
  const [scope, setScope] = useState<Scope>('read')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!valid) return
    getOAuthClient(req.clientId)
      .then(setApp)
      .catch((e: Error) => setError(e.message))
  }, [req.clientId, valid])

  async function answer(approve: boolean) {
    setBusy(true)
    setError('')
    try {
      const { redirect_to } = await approveOAuth({
        client_id: req.clientId,
        redirect_uri: req.redirectUri,
        state: req.state,
        code_challenge: req.challenge,
        scope,
        approve,
      })
      nav.to(redirect_to)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
      setBusy(false)
    }
  }

  if (!valid) {
    return (
      <main className="content">
        <p role="alert">This link is not valid. Go back to the app and try connecting again.</p>
      </main>
    )
  }

  return (
    <main className="content">
      <section className="card section-card">
        <h3>Connect {app?.name ?? 'an app'} to JobMeCloud</h3>
        {error && <p role="alert">{error}</p>}
        {app && (
          <>
            <p>
              <strong>{app.name}</strong> is asking to read{scope === 'readwrite' ? ' and change' : ''} your jobs, follow-ups
              and contacts. After you answer, you will be sent back to <strong>{app.redirect_hosts.join(', ')}</strong>.
            </p>
            <fieldset>
              <legend>What can it do?</legend>
              <label>
                <input type="radio" name="scope" value="read" checked={scope === 'read'} onChange={() => setScope('read')} />{' '}
                Read only
              </label>
              <label>
                <input
                  type="radio"
                  name="scope"
                  value="readwrite"
                  checked={scope === 'readwrite'}
                  onChange={() => setScope('readwrite')}
                />{' '}
                Read and change
              </label>
              {scope === 'readwrite' && (
                <p className="muted">
                  It can then change your jobs, statuses, follow-ups and contacts. Job postings it reads are untrusted text, so
                  choose read only unless you need changes.
                </p>
              )}
            </fieldset>
            <p className="muted">Only approve if you just started this from ChatGPT or Claude.</p>
            <button type="button" disabled={busy} onClick={() => answer(true)}>
              Approve
            </button>{' '}
            <button type="button" disabled={busy} onClick={() => answer(false)}>
              Cancel
            </button>
            <p className="muted">You can see and revoke this connection any time in Settings, Claude access.</p>
          </>
        )}
      </section>
    </main>
  )
}
