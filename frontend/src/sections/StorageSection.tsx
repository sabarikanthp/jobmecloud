import { useEffect, useState } from 'react'
import { getStorage, saveStorage } from '../api.ts'
import SectionCard, { type SectionMode } from '../components/SectionCard.tsx'
import Tip from '../components/Tip.tsx'

export default function StorageSection({ mode, onSaved }: { mode: SectionMode; onSaved?: () => void | Promise<void> }) {
  const [dataDir, setDataDir] = useState('')
  const [appsDir, setAppsDir] = useState('')
  const [saved, setSaved] = useState({ data: '', apps: '' })
  const [locked, setLocked] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    getStorage()
      .then((s) => {
        setDataDir(s.data_dir)
        setAppsDir(s.applications_dir)
        setSaved({ data: s.data_dir, apps: s.applications_dir })
        setLocked(s.locked)
        setLoaded(true)
      })
      .catch((e: Error) => setLoadError(e.message))
  }, [])

  async function save() {
    // Send the applications folder only when the user changed it ('' resets it to the default).
    const appsChanged = appsDir.trim() !== saved.apps.trim()
    const s = await saveStorage(dataDir, appsChanged ? appsDir.trim() : undefined)
    if (s.data_dir !== saved.data) {
      // The data folder moved: reload so every section and the setup check use the new folder.
      window.location.reload()
      return
    }
    setDataDir(s.data_dir)
    setAppsDir(s.applications_dir)
    setSaved({ data: s.data_dir, apps: s.applications_dir })
    setLocked(s.locked)
    await onSaved?.()
  }

  return (
    <SectionCard title="Where JobMe keeps your files" summary={saved.data || 'Loading…'}
      mode={mode}
      onSave={save}
      canSave={loaded && !loadError}
      onCancel={() => {
        setDataDir(saved.data)
        setAppsDir(saved.apps)
      }}
    >
      {loadError && <div className="result bad">{loadError}</div>}
      {!loaded && !loadError && <p className="muted">Loading…</p>}
      {loaded && (
        <>
          <div className="field">
            <div className="field-label">
              <label htmlFor="data-dir">Data folder</label>
              <Tip text="Pick a folder that is backed up, such as one inside OneDrive or Dropbox, if you want a copy elsewhere." />
            </div>
            <input
              id="data-dir"
              value={dataDir}
              disabled={locked}
              onChange={(e) => setDataDir(e.target.value)}
            />
            <span className="help">Where JobMe keeps your profile, settings and job list.</span>
          </div>
          <label>
            Applications folder
            <input value={appsDir} onChange={(e) => setAppsDir(e.target.value)} />
            <span className="help">Where each job's resume and cover letter are saved, one folder per job.</span>
          </label>
        </>
      )}
    </SectionCard>
  )
}
