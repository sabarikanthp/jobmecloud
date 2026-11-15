import { useEffect, useState } from 'react'
import { getSettings, saveSettings, type Settings } from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'
import Tip from '../components/Tip.tsx'

interface PriceRow {
  model: string
  input: string
  output: string
}

interface Snapshot {
  searches: string
  spend: string
  apps: string
  rows: PriceRow[]
}

interface Caps {
  max_searches_per_run?: number
  max_spend_per_run_usd?: number
  max_applications_per_run?: number
}

type Prices = Record<string, { input_per_mtok: number; output_per_mtok: number }>

const NUMBER_ERROR = 'Enter a number of 0 or more.'

function validNumber(text: string): boolean {
  const t = text.trim()
  return t !== '' && Number.isFinite(Number(t)) && Number(t) >= 0
}

function validWhole(text: string): boolean {
  return validNumber(text) && Number.isInteger(Number(text.trim()))
}

export default function LimitsSection({ mode }: { mode: SectionMode }) {
  const [searches, setSearches] = useState('0')
  const [spend, setSpend] = useState('0')
  const [apps, setApps] = useState('0')
  const [rows, setRows] = useState<PriceRow[]>([])
  const [saved, setSaved] = useState<Snapshot>({ searches: '0', spend: '0', apps: '0', rows: [] })
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')

  function apply(s: Snapshot) {
    setSearches(s.searches)
    setSpend(s.spend)
    setApps(s.apps)
    setRows(s.rows)
  }

  useEffect(() => {
    getSettings()
      .then((s) => {
        const caps = (s.caps ?? {}) as Caps
        const prices = (s.prices ?? {}) as Prices
        const snap: Snapshot = {
          searches: String(caps.max_searches_per_run ?? 0),
          spend: String(caps.max_spend_per_run_usd ?? 0),
          apps: String(caps.max_applications_per_run ?? 0),
          rows: Object.entries(prices).map(([model, p]) => ({
            model,
            input: String(p.input_per_mtok),
            output: String(p.output_per_mtok),
          })),
        }
        apply(snap)
        setSaved(snap)
        setLoaded(true)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  const names = rows.map((r) => r.model.trim()).filter((m) => m)
  const duplicates = new Set(names.filter((m, i) => names.indexOf(m) !== i))
  const searchesOk = validWhole(searches)
  const spendOk = validNumber(spend)
  const appsOk = validWhole(apps)
  // Blank-model rows are dropped on save, so they are not checked.
  const rowsOk = rows.every((r) => !r.model.trim() || (validNumber(r.input) && validNumber(r.output)))
  const valid = searchesOk && spendOk && appsOk && rowsOk && duplicates.size === 0

  function setRow(i: number, patch: Partial<PriceRow>) {
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  }

  async function save() {
    if (!valid) throw new Error(NUMBER_ERROR)
    const kept = rows
      .filter((r) => r.model.trim())
      .map((r) => ({ model: r.model.trim(), input: r.input.trim(), output: r.output.trim() }))
    const prices: Prices = {}
    for (const r of kept) prices[r.model] = { input_per_mtok: Number(r.input), output_per_mtok: Number(r.output) }
    const current = await getSettings()
    const caps = {
      ...((current.caps ?? {}) as Caps),
      max_searches_per_run: Number(searches.trim()),
      max_spend_per_run_usd: Number(spend.trim()),
      max_applications_per_run: Number(apps.trim()),
    }
    const next: Settings = { ...current, caps, prices }
    await saveSettings(next)
    const snap: Snapshot = {
      searches: String(Number(searches.trim())), spend: String(Number(spend.trim())),
      apps: String(Number(apps.trim())),
      rows: kept,
    }
    apply(snap)
    setSaved(snap)
  }

  const summary = `Up to ${saved.searches} searches · $${saved.spend} per run`

  return (
    <SectionCard
      title="Search limits and prices"
      summary={summary}
      mode={mode}
      onSave={save}
      canSave={loaded && !loadError && valid}
      onCancel={() => apply(saved)}
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      {loaded && (
        <>
          <div className="field">
            <div className="field-label">
              <label htmlFor="max-searches">Searches per run</label>
            </div>
            <input
              id="max-searches"
              inputMode="numeric"
              value={searches}
              onChange={(e) => setSearches(e.target.value)}
            />
            {!searchesOk && <span className="result bad">{NUMBER_ERROR}</span>}
            <span className="help">The most web searches one run can make.</span>
          </div>
          <div className="field">
            <div className="field-label">
              <label htmlFor="max-spend">Spending limit per run (USD)</label>
            </div>
            <input id="max-spend" inputMode="decimal" value={spend} onChange={(e) => setSpend(e.target.value)} />
            {!spendOk && <span className="result bad">{NUMBER_ERROR}</span>}
            <span className="help">A run stops early when its estimated cost reaches this. 0 means no limit.</span>
          </div>
          <div className="field">
            <div className="field-label">
              <label htmlFor="max-apps">Applications per run</label>
            </div>
            <input id="max-apps" inputMode="numeric" value={apps} onChange={(e) => setApps(e.target.value)} />
            {!appsOk && <span className="result bad">{NUMBER_ERROR}</span>}
            <span className="help">How many top matches get a tailored resume and cover letter in each run.</span>
          </div>
          <div className="field">
            <div className="field-label">
              Prices
              <Tip text="Used only to estimate what a run costs. Local models cost nothing, so they don't need a row." />
            </div>
            {rows.length > 0 && (
              <table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Input ($ per million tokens)</th>
                    <th>Output ($ per million tokens)</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const name = r.model.trim()
                    const active = name !== ''
                    return (
                      <tr key={i}>
                        <td>
                          <input
                            aria-label={`Model ${i + 1}`}
                            value={r.model}
                            onChange={(e) => setRow(i, { model: e.target.value })}
                          />
                          {duplicates.has(name) && <div className="result bad">Each model can appear only once.</div>}
                        </td>
                        <td>
                          <input
                            aria-label={`Input price ${i + 1}`}
                            inputMode="decimal"
                            value={r.input}
                            onChange={(e) => setRow(i, { input: e.target.value })}
                          />
                          {active && !validNumber(r.input) && <div className="result bad">{NUMBER_ERROR}</div>}
                        </td>
                        <td>
                          <input
                            aria-label={`Output price ${i + 1}`}
                            inputMode="decimal"
                            value={r.output}
                            onChange={(e) => setRow(i, { output: e.target.value })}
                          />
                          {active && !validNumber(r.output) && <div className="result bad">{NUMBER_ERROR}</div>}
                        </td>
                        <td>
                          <button className="danger" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
            <div>
              <button className="add" onClick={() => setRows([...rows, { model: '', input: '0', output: '0' }])}>Add a model</button>
            </div>
          </div>
        </>
      )}
    </SectionCard>
  )
}
