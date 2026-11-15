import { useEffect, useState } from 'react'
import { getSettings, saveSettings, type Settings } from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'

type Tone = 'formal' | 'warm' | 'direct'

const TONES: [Tone, string][] = [
  ['formal', 'Formal'],
  ['warm', 'Warm'],
  ['direct', 'Direct'],
]

interface Snapshot {
  tone: Tone
  pattern: string
}

export default function DocumentsSection({ mode }: { mode: SectionMode }) {
  const [tone, setTone] = useState<Tone>('warm')
  const [pattern, setPattern] = useState('')
  const [saved, setSaved] = useState<Snapshot>({ tone: 'warm', pattern: '' })
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')

  function apply(s: Snapshot) {
    setTone(s.tone)
    setPattern(s.pattern)
  }

  useEffect(() => {
    getSettings()
      .then((s) => {
        const snap: Snapshot = {
          tone: (s.cover_letter_tone as Tone | undefined) ?? 'warm',
          pattern: String(s.folder_pattern ?? ''),
        }
        apply(snap)
        setSaved(snap)
        setLoaded(true)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  async function save() {
    const folder = pattern.trim()
    if (!folder) throw new Error('Enter a folder name.')
    const current = await getSettings()
    const next: Settings = { ...current, cover_letter_tone: tone, folder_pattern: folder }
    await saveSettings(next)
    const snap: Snapshot = { tone, pattern: folder }
    apply(snap)
    setSaved(snap)
  }

  return (
    <SectionCard
      title="Documents"
      summary={`Cover letter tone: ${saved.tone}`}
      mode={mode}
      onSave={save}
      canSave={loaded && !loadError}
      onCancel={() => apply(saved)}
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      {loaded && (
        <>
          <div className="field">
            <div className="field-label">
              <label htmlFor="cover-tone">Cover letter tone</label>
            </div>
            <select id="cover-tone" value={tone} onChange={(e) => setTone(e.target.value as Tone)}>
              {TONES.map(([k, name]) => (
                <option key={k} value={k}>
                  {name}
                </option>
              ))}
            </select>
            <span className="help">How your cover letters sound.</span>
          </div>
          <div className="field">
            <div className="field-label">
              <label htmlFor="folder-name">Folder name</label>
            </div>
            <input id="folder-name" value={pattern} onChange={(e) => setPattern(e.target.value)} />
            <span className="help">How each job's folder is named. You can use {'{date}'}, {'{company}'} and {'{title}'}.</span>
          </div>
        </>
      )}
    </SectionCard>
  )
}
