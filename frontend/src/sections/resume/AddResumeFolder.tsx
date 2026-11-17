import { useRef, useState } from 'react'
import { draftResume, saveNewResume } from '../../api.ts'

const SUPPORTED = /\.(docx|pdf|txt|md)$/i
const baseName = (filename: string) => filename.replace(/\.[^.]*$/, '')

// Add many resumes at once: choose a folder (or several files) and each is read once by the AI and saved to the
// library under its file name. They are never made the default. The browser can only hand over the files you
// choose, so this adds what is in the folder now; it does not watch the folder for later changes.
export default function AddResumeFolder({
  existingNames,
  onDone,
}: {
  existingNames: string[]
  onDone: () => void | Promise<void>
}) {
  const [files, setFiles] = useState<File[] | null>(null)
  const [skipped, setSkipped] = useState(0)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [summary, setSummary] = useState('')
  const [failures, setFailures] = useState<string[]>([])
  const folderRef = useRef<HTMLInputElement>(null)
  const filesRef = useRef<HTMLInputElement>(null)

  function chosen(e: React.ChangeEvent<HTMLInputElement>) {
    const all = Array.from(e.target.files ?? [])
    e.target.value = '' // so the same folder can be chosen again
    const known = new Set(existingNames.map((n) => n.toLowerCase()))
    const fresh = all.filter((f) => SUPPORTED.test(f.name) && !f.name.startsWith('~$'))
    const keep = fresh.filter((f) => !known.has(baseName(f.name).toLowerCase()))
    setFiles(keep)
    setSkipped(fresh.length - keep.length)
    setSummary('')
    setFailures([])
  }

  async function start() {
    if (!files?.length) return
    setBusy(true)
    setSummary('')
    const failed: string[] = []
    let added = 0
    for (const [i, file] of files.entries()) {
      setProgress(`Reading ${i + 1} of ${files.length}: ${file.name}`)
      try {
        const draft = await draftResume(file)
        await saveNewResume({
          upload_id: draft.upload_id,
          name: baseName(draft.filename),
          reading: draft.reading,
          mapping: draft.kind === 'docx' ? draft.mapping : null,
          make_default: false,
        })
        added += 1
      } catch (e) {
        failed.push(`${file.name}: ${e instanceof Error ? e.message : 'Something went wrong.'}`)
      }
    }
    setProgress('')
    setFailures(failed)
    setSummary(`Added ${added} of ${files.length}.`)
    setFiles(null)
    setBusy(false)
    await onDone()
  }

  return (
    <div className="add-resume-folder">
      <div className="row">
        <button type="button" disabled={busy} onClick={() => folderRef.current?.click()}>
          Add a folder of resumes…
        </button>
        <button type="button" disabled={busy} onClick={() => filesRef.current?.click()}>
          Add several files…
        </button>
      </div>
      <input
        ref={folderRef}
        type="file"
        hidden
        multiple
        // @ts-expect-error webkitdirectory is a widely supported attribute that React's types do not list
        webkitdirectory=""
        onChange={chosen}
      />
      <input ref={filesRef} type="file" hidden multiple accept=".docx,.pdf,.txt,.md" onChange={chosen} />
      {files && files.length > 0 && (
        <div>
          <p>
            {files.length} {files.length === 1 ? 'resume' : 'resumes'} found:{' '}
            {files.map((f) => baseName(f.name)).join(', ')}.
            {skipped > 0 && ` ${skipped} skipped because ${skipped === 1 ? 'it is' : 'they are'} already in your library.`}
          </p>
          <p className="help">
            Each one is read once by the AI, usually a cent or two. They are saved in your library and none becomes
            your default.
          </p>
          <button type="button" className="primary" disabled={busy} onClick={() => void start()}>
            Add these resumes
          </button>
        </div>
      )}
      {files && files.length === 0 && (
        <p className="help">
          No new resumes found{skipped > 0 ? ` (${skipped} already in your library)` : ''}. Word, PDF, text and
          Markdown files are read.
        </p>
      )}
      {progress && (
        <p className="help" role="status">
          {progress}
        </p>
      )}
      {summary && <p className="result ok">{summary}</p>}
      {failures.length > 0 && (
        <ul className="result bad">
          {failures.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
