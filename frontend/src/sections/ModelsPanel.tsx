import { useEffect, useState } from 'react'
import {
  getModels,
  getSettings,
  saveSettings,
  type ModelsInfo,
  type ProviderOut,
  type Steps,
} from '../api.ts'
import Tip from '../components/Tip.tsx'

export default function ModelsPanel({
  providers,
  savedSteps,
  onSaved,
}: {
  providers: ProviderOut[]
  savedSteps: Steps
  onSaved: (steps: Steps) => void | Promise<void>
}) {
  const [info, setInfo] = useState<ModelsInfo | null>(null)
  const [steps, setSteps] = useState<Steps>(savedSteps)
  const [loadError, setLoadError] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getModels()
      .then(setInfo)
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  useEffect(() => {
    if (!saved) return
    const t = setTimeout(() => setSaved(false), 3000)
    return () => clearTimeout(t)
  }, [saved])

  if (loadError) return <p className="result bad">{loadError}</p>
  if (!info) return <p className="muted">Loading…</p>

  const kindOf = (id: string) => providers.find((p) => p.id === id)?.kind
  const providerFor = (id: string) => {
    const pid = steps[id]?.provider_id
    return pid && providers.some((p) => p.id === pid) ? pid : (providers[0]?.id ?? '')
  }
  const modelFor = (id: string) => steps[id]?.model ?? ''
  const anyOther = info.steps.some((s) => kindOf(providerFor(s.id)) === 'openai_compatible')

  function update(id: string, patch: Partial<{ provider_id: string; model: string }>) {
    setSteps((cur) => ({
      ...cur,
      [id]: {
        provider_id: cur[id]?.provider_id ?? providers[0]?.id ?? '',
        model: cur[id]?.model ?? '',
        ...patch,
      },
    }))
  }

  async function save() {
    if (!info) return
    setError('')
    const next: Steps = {}
    for (const s of info.steps) {
      const model = modelFor(s.id).trim()
      if (!model) {
        setError('Enter a model name for every job.')
        return
      }
      next[s.id] = { provider_id: providerFor(s.id), model }
    }
    setBusy(true)
    try {
      const current = await getSettings()
      await saveSettings({ ...current, steps: next })
      setSteps(next)
      setSaved(true)
      await onSaved(next)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="models-panel">
      <h4>Models for each job</h4>
      {info.steps.map((s) => {
        const kind = kindOf(providerFor(s.id))
        const listId = `models-${s.id}`
        return (
          <div className="field" key={s.id}>
            <div className="field-label">
              <label htmlFor={`model-${s.id}`}>{s.label}</label>
              <Tip text={s.help} />
            </div>
            <div className="row">
              <select
                aria-label={`${s.label} provider`}
                value={providerFor(s.id)}
                onChange={(e) => update(s.id, { provider_id: e.target.value })}
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
              <input
                id={`model-${s.id}`}
                list={listId}
                value={modelFor(s.id)}
                onChange={(e) => update(s.id, { model: e.target.value })}
              />
              <datalist id={listId}>
                {(kind ? info.recommended[kind] : []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>
          </div>
        )
      })}
      {anyOther && <p className="help">{info.local_note}</p>}
      <div className="row">
        <button type="button" className="primary" disabled={busy} onClick={save}>
          Save models
        </button>
        <span role="status" className="saved-note">
          {saved ? 'Saved' : ''}
        </span>
      </div>
      {error && <p className="result bad">{error}</p>}
    </div>
  )
}
