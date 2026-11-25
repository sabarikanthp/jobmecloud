import { useEffect, useState } from 'react'
import { createApiKey, listApiKeys, revokeApiKey, type ApiKeyCreated, type ApiKeyOut } from '../api.ts'
import Tip from '../components/Tip.tsx'

type Scope = 'read' | 'readwrite'

const SCOPE_LABEL: Record<Scope, string> = { read: 'Read only', readwrite: 'Read and change' }
const EXPIRY_CHOICES: { label: string; days: number | null }[] = [
  { label: 'Never expires', days: null },
  { label: 'Expires in 30 days', days: 30 },
  { label: 'Expires in 90 days', days: 90 },
  { label: 'Expires in a year', days: 365 },
]

/** The block to paste into Claude Desktop's config file. The key goes in an environment variable because
 *  a space inside an argument is mangled on Windows. */
export function desktopConfig(origin: string, key: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        jobme: {
          command: 'npx',
          args: ['-y', 'mcp-remote', `${origin}/api/mcp`, '--header', 'Authorization:${AUTH_HEADER}'],
          env: { AUTH_HEADER: `Bearer ${key}` },
        },
      },
    },
    null,
    2,
  )
}

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : '')

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export default function ClaudeAccessSection() {
  const [keys, setKeys] = useState<ApiKeyOut[]>([])
  const [loadError, setLoadError] = useState('')
  const [name, setName] = useState('')
  const [scope, setScope] = useState<Scope>('read')
  const [days, setDays] = useState<number | null>(null)
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [copied, setCopied] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () =>
    listApiKeys()
      .then((k) => {
        setKeys(k)
        setLoadError('')
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : "Couldn't load your keys."))

  useEffect(() => {
    void load()
  }, [])

  async function create() {
    setBusy(true)
    setError('')
    try {
      setCreated(await createApiKey(name.trim(), scope, days))
      setName('')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  async function revoke(k: ApiKeyOut) {
    if (!window.confirm(`Revoke "${k.name}"? Anything using this key stops working straight away.`)) return
    try {
      await revokeApiKey(k.id)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    }
  }

  async function copyText(label: string, text: string) {
    setCopied((await copy(text)) ? label : '')
  }

  return (
    <section className="card section-card">
      <div className="section-head">
        <h3>
          Claude access
          <Tip text="Let your Claude Desktop chats read and update JobMe. Each key is shown once; revoke it here at any time." />
        </h3>
      </div>
      <p className="muted">
        Create a key, then paste the settings into Claude Desktop. A read-only key can look at your jobs but change
        nothing.
      </p>
      {loadError && <p role="alert">{loadError}</p>}

      {created && (
        <div className="notice" role="status">
          <p>
            <strong>Copy this key now.</strong> It is shown only once.
          </p>
          <pre>{created.key}</pre>
          <button type="button" onClick={() => copyText('key', created.key)}>
            Copy key
          </button>{' '}
          <button type="button" onClick={() => copyText('config', desktopConfig(window.location.origin, created.key))}>
            Copy Claude Desktop settings
          </button>
          {copied && <span className="saved-note"> Copied</span>}
          <p className="muted">
            Add this to the <code>mcpServers</code> part of Claude Desktop's <code>claude_desktop_config.json</code>{' '}
            (Settings, Developer, Edit config), then restart Claude Desktop. The connection address is{' '}
            <code>{window.location.origin}/api/mcp</code>.
          </p>
          <pre>{desktopConfig(window.location.origin, created.key)}</pre>
          <button type="button" onClick={() => setCreated(null)}>
            Done
          </button>
        </div>
      )}

      {keys.length > 0 && (
        <table className="table stack">
          <thead>
            <tr>
              <th>Name</th>
              <th>Access</th>
              <th>Key</th>
              <th>Last used</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>
                  {k.name}
                  {k.via === 'sign-in' && (
                    <span className="muted">
                      {' '}
                      · Connected via sign-in{k.app_name ? ` (${k.app_name})` : ''}
                    </span>
                  )}
                </td>
                <td data-label="Access">{SCOPE_LABEL[k.scope]}</td>
                <td data-label="Key">
                  <code>{k.prefix}…</code>
                </td>
                <td data-label="Last used">
                  {k.revoked_at ? `Revoked ${day(k.revoked_at)}` : k.last_used_at ? day(k.last_used_at) : 'Never used'}
                  {!k.revoked_at && k.expires_at ? ` · expires ${day(k.expires_at)}` : ''}
                </td>
                <td>
                  {!k.revoked_at && (
                    <button type="button" onClick={() => revoke(k)}>
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h4>New key</h4>
      <label>
        Name{' '}
        <input type="text" value={name} maxLength={60} placeholder="e.g. Laptop" onChange={(e) => setName(e.target.value)} />
      </label>
      <fieldset>
        <legend>What can it do?</legend>
        {(['read', 'readwrite'] as Scope[]).map((s) => (
          <label key={s}>
            <input type="radio" name="scope" value={s} checked={scope === s} onChange={() => setScope(s)} />{' '}
            {SCOPE_LABEL[s]}
          </label>
        ))}
        {scope === 'readwrite' && (
          <p className="muted">
            A chat with this key can change your jobs, contacts, follow-ups and documents. Job postings it reads are
            untrusted text, so use a read-only key unless you need changes.
          </p>
        )}
      </fieldset>
      <label>
        Expiry{' '}
        <select value={String(days)} onChange={(e) => setDays(e.target.value === 'null' ? null : Number(e.target.value))}>
          {EXPIRY_CHOICES.map((c) => (
            <option key={c.label} value={String(c.days)}>
              {c.label}
            </option>
          ))}
        </select>
      </label>
      <p>
        <button type="button" disabled={busy || !name.trim()} onClick={create}>
          Create key
        </button>
      </p>
      {error && <p role="alert">{error}</p>}
    </section>
  )
}
