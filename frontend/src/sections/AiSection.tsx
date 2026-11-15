import { useCallback, useEffect, useState } from 'react'
import {
  applyDefaultSteps,
  deleteProvider,
  getProviders,
  getSearch,
  getSettings,
  saveProvider,
  saveSearch,
  testProvider,
  testSearch,
  type ConnectionResult,
  type ProviderKind,
  type ProviderOut,
  type SearchBackend,
  type SearchSaved,
  type Steps,
} from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'
import Tip from '../components/Tip.tsx'
import ModelsPanel from './ModelsPanel.tsx'

const CLAUDE_TEST_MODEL = 'claude-haiku-5-5'

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'provider'
}

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong.'
}

function Result({ r }: { r: ConnectionResult | null }) {
  if (!r) return null
  return <p className={r.ok ? 'result ok' : 'result bad'}>{r.message}</p>
}

function ProviderForm({
  editing,
  existingIds,
  onSaved,
  onCancel,
}: {
  editing: ProviderOut | null
  existingIds: string[]
  onSaved: () => void
  onCancel: () => void
}) {
  const [kind, setKind] = useState<ProviderKind>(editing?.kind ?? 'anthropic')
  const [label, setLabel] = useState(editing?.label ?? '')
  const [baseUrl, setBaseUrl] = useState(editing?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(editing?.kind === 'openai_compatible' ? '' : CLAUDE_TEST_MODEL)
  const [savedId, setSavedId] = useState<string | null>(editing?.id ?? null)
  const [saved, setSaved] = useState(
    editing
      ? { kind: editing.kind, label: editing.label, baseUrl: editing.base_url ?? '' }
      : null,
  )
  const [hasKey, setHasKey] = useState(editing?.has_key ?? false)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ConnectionResult | null>(null)

  const dirty =
    !saved ||
    kind !== saved.kind ||
    label.trim() !== saved.label ||
    (kind === 'openai_compatible' && baseUrl.trim() !== saved.baseUrl) ||
    apiKey.trim() !== ''

  function changeKind(k: ProviderKind) {
    setKind(k)
    setModel(k === 'anthropic' ? CLAUDE_TEST_MODEL : '')
  }

  async function save() {
    setError('')
    setResult(null)
    if (!label.trim()) {
      setError('Please give this connection a name.')
      return
    }
    if (kind === 'openai_compatible' && !baseUrl.trim()) {
      setError('Please enter the address of the provider.')
      return
    }
    let id = editing?.id ?? savedId
    if (!id) {
      const base = slug(label)
      id = base
      for (let n = 2; existingIds.includes(id); n++) id = `${base}-${n}`
    }
    setBusy(true)
    try {
      await saveProvider(
        {
          id,
          kind,
          label: label.trim(),
          base_url: kind === 'openai_compatible' ? baseUrl.trim() : null,
          structured_output:
            editing?.structured_output ?? (kind === 'anthropic' ? 'native' : 'prompt'),
        },
        apiKey.trim() || undefined,
      )
      setSavedId(id)
      setSaved({
        kind,
        label: label.trim(),
        baseUrl: kind === 'openai_compatible' ? baseUrl.trim() : '',
      })
      if (apiKey.trim()) setHasKey(true)
      setApiKey('')
      onSaved()
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function test() {
    if (!savedId) return
    setError('')
    setResult(null)
    setBusy(true)
    setTesting(true)
    try {
      setResult(await testProvider(savedId, model.trim()))
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusy(false)
      setTesting(false)
    }
  }

  return (
    <form className="card" onSubmit={(e) => e.preventDefault()}>
      <h3>{editing ? 'Edit provider' : 'Add provider'}</h3>
      <label>
        Type
        <select value={kind} onChange={(e) => changeKind(e.target.value as ProviderKind)}>
          <option value="anthropic">Claude (Anthropic)</option>
          <option value="openai_compatible">Other (OpenAI-compatible)</option>
        </select>
      </label>
      <label>
        Name
        <input value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      {kind === 'openai_compatible' && (
        <label>
          Address
          <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          <span className="help">For Ollama use http://localhost:11434/v1</span>
        </label>
      )}
      <label>
        API key
        <input
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={hasKey ? 'Key saved. Type a new one to replace it.' : ''}
        />
        <span className="help">Leave empty for local models</span>
      </label>
      <label>
        Model to test
        <input value={model} onChange={(e) => setModel(e.target.value)} />
      </label>
      <div className="row">
        <button type="button" className="primary" disabled={busy} onClick={save}>
          Save
        </button>
        <button
          type="button"
          disabled={busy || dirty || !savedId || !model.trim()}
          onClick={test}
        >
          {testing ? 'Testing…' : 'Test'}
        </button>
        <button type="button" className="link" onClick={onCancel}>
          Close
        </button>
      </div>
      {dirty && <p className="help">Save first, then test.</p>}
      {error && <p className="result bad">{error}</p>}
      <Result r={result} />
    </form>
  )
}

const SEARCH_OPTIONS = [
  [
    'builtin',
    'Built-in (Claude only)',
    'Claude searches the web itself, so there is no extra key. Only works with Claude.',
  ],
  [
    'tavily',
    'Tavily',
    "A search service made for AI apps. Needs its own key (free to start) from tavily.com. Use it with any AI that isn't Claude.",
  ],
  [
    'brave',
    'Brave',
    "Brave's search service. Needs its own key. Use it with any AI that isn't Claude.",
  ],
] as const

function SearchSection({
  saved,
  onSaved,
}: {
  saved: SearchSaved
  onSaved: (s: SearchSaved) => void
}) {
  const [backend, setBackend] = useState<SearchBackend>(saved.backend)
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ConnectionResult | null>(null)

  const [seen, setSeen] = useState(saved.backend)
  if (seen !== saved.backend) {
    // The saved choice finished loading (or changed): follow it.
    setSeen(saved.backend)
    setBackend(saved.backend)
  }

  const dirty = backend !== saved.backend || apiKey.trim() !== ''
  const hasKey = backend === saved.backend && saved.has_key

  async function save() {
    setError('')
    setResult(null)
    setBusy(true)
    try {
      onSaved(await saveSearch(backend, apiKey.trim() || undefined))
      setApiKey('')
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function test() {
    setError('')
    setResult(null)
    setBusy(true)
    setTesting(true)
    try {
      setResult(await testSearch())
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusy(false)
      setTesting(false)
    }
  }

  return (
    <section>
      <h4>Search</h4>
      <form className="card" onSubmit={(e) => e.preventDefault()}>
        <fieldset>
          <legend>How should JobMe search for jobs?</legend>
          {SEARCH_OPTIONS.map(([value, text, tip]) => (
            <div key={value} className="field-label">
              <label className="radio">
                <input
                  type="radio"
                  name="search"
                  checked={backend === value}
                  onChange={() => {
                    setBackend(value)
                    setResult(null)
                  }}
                />
                {text}
              </label>
              <Tip text={tip} />
            </div>
          ))}
        </fieldset>
        {backend !== 'builtin' && (
          <label>
            API key
            <input
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            {hasKey && <span className="badge">Key saved</span>}
          </label>
        )}
        <div className="row">
          <button type="button" className="primary" disabled={busy} onClick={save}>
            Save
          </button>
          <button type="button" disabled={busy || dirty} onClick={test}>
            {testing ? 'Testing…' : 'Test'}
          </button>
        </div>
        {dirty && <p className="help">Save first, then test.</p>}
        {error && <p className="result bad">{error}</p>}
        <Result r={result} />
      </form>
    </section>
  )
}

const SEARCH_LABELS: Record<SearchBackend, string> = {
  builtin: 'Built-in',
  tavily: 'Tavily',
  brave: 'Brave',
}

export default function AiSection({
  mode,
  onSaved,
}: {
  mode: SectionMode
  onSaved?: () => void | Promise<void>
}) {
  const [providers, setProviders] = useState<ProviderOut[]>([])
  const [steps, setSteps] = useState<Steps>({})
  const [search, setSearch] = useState<SearchSaved>({ backend: 'builtin', has_key: false })
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [form, setForm] = useState<{ editing: ProviderOut | null } | null>(null)
  const [showModels, setShowModels] = useState(false)
  const [model, setModel] = useState('')
  const [stepsVersion, setStepsVersion] = useState(0)

  const apply = useCallback(
    ([list, s, sr]: [ProviderOut[], Awaited<ReturnType<typeof getSettings>>, SearchSaved]) => {
      setProviders(list)
      setSteps((s.steps as Steps | undefined) ?? {})
      setStepsVersion((v) => v + 1)
      setSearch(sr)
      setLoadError('')
      setLoaded(true)
    },
    [],
  )
  const refresh = useCallback(async () => {
    try {
      apply(await Promise.all([getProviders(), getSettings(), getSearch()]))
    } catch (e) {
      setLoadError(errMessage(e))
    }
  }, [apply])

  useEffect(() => {
    Promise.all([getProviders(), getSettings(), getSearch()])
      .then(apply)
      .catch((e) => setLoadError(errMessage(e)))
  }, [apply])

  async function remove(p: ProviderOut) {
    if (!window.confirm(`Remove "${p.label}"? Its saved key will be deleted.`)) return
    try {
      await deleteProvider(p.id)
      if (form?.editing?.id === p.id) setForm(null)
      await refresh()
    } catch (e) {
      setLoadError(errMessage(e))
    }
  }

  const first = providers[0]
  const needDefaults =
    !!first &&
    (Object.keys(steps).length === 0 ||
      Object.values(steps).some((sm) => !providers.some((p) => p.id === sm.provider_id)))

  async function save() {
    if (mode !== 'wizard') return
    if (!first) throw new Error('Add an AI connection first.')
    if (needDefaults) {
      const other = first.kind !== 'anthropic'
      if (other && !model.trim()) throw new Error('Enter the model name to use.')
      setSteps(await applyDefaultSteps(first.id, other ? model.trim() : null))
      setStepsVersion((v) => v + 1)
    }
    await onSaved?.()
  }

  const summary = `${first ? first.label : 'No AI connected yet'} · search: ${SEARCH_LABELS[search.backend]}`

  return (
    <SectionCard
      title="AI connection"
      summary={summary}
      mode={mode}
      onSave={save}
      canSave={loaded && !loadError}
      saveLabel="Continue"
    >
      {loadError && <p className="result bad">{loadError}</p>}
      {providers.length === 0 && !loadError && (
        <p className="muted">No AI provider yet. Add one to get started.</p>
      )}
      <ul className="providers">
        {providers.map((p) => (
          <li key={p.id} className="card provider">
            <div>
              <strong>{p.label}</strong>{' '}
              <span className="muted">
                {p.kind === 'anthropic' ? 'Claude (Anthropic)' : `Other, ${p.base_url ?? ''}`}
              </span>{' '}
              {p.has_key && <span className="badge">Key saved</span>}
            </div>
            <div className="row">
              <button type="button" onClick={() => setForm({ editing: p })}>
                Edit
              </button>
              <button type="button" className="danger" onClick={() => remove(p)}>
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>
      {form ? (
        <ProviderForm
          key={form.editing?.id ?? 'new'}
          editing={form.editing}
          existingIds={providers.map((p) => p.id)}
          onSaved={refresh}
          onCancel={() => setForm(null)}
        />
      ) : (
        <button type="button" className="add" onClick={() => setForm({ editing: null })}>
          Add provider
        </button>
      )}
      {loaded && <SearchSection saved={search} onSaved={setSearch} />}
      {mode === 'wizard' && first && (
        <div className="card">
          <h4>Use this AI</h4>
          {!needDefaults ? (
            <p className="muted">Models are already chosen.</p>
          ) : first.kind === 'anthropic' ? (
            <p>
              JobMe will use Claude Sonnet 5.5 for searching and writing, and Claude Haiku 5.5 for
              quicker jobs.
            </p>
          ) : (
            (
              <div className="field">
                <label htmlFor="ai-model">Model name</label>
                <input id="ai-model" value={model} onChange={(e) => setModel(e.target.value)} />
                <span className="help">
                  The same model is used for every job. You can change this later in Settings.
                </span>
              </div>
            )
          )}
          {!showModels && (
            <button type="button" className="link" onClick={() => setShowModels(true)}>
              Change models
            </button>
          )}
        </div>
      )}
      {(mode === 'settings' || showModels) && first && (
        <ModelsPanel
          key={`${providers.map((p) => p.id).join(',')}:${stepsVersion}`}
          providers={providers}
          savedSteps={steps}
          onSaved={(next) => {
            setSteps(next)
          }}
        />
      )}
    </SectionCard>
  )
}
