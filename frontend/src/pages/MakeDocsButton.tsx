import { useState } from 'react'
import { makeDocs, type JobSummary } from '../api.ts'
import { STALE_NOTE, type DocsRunner } from './docsTypes.ts'

export default function MakeDocsButton({
  job,
  busyId,
  runDocs,
}: {
  job: JobSummary
  busyId: number | null
  runDocs: DocsRunner
}) {
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)
  const mine = busyId === job.id
  const shown = error || job.docs_error || ''

  async function go() {
    setError('')
    setStale(false)
    const out = await runDocs(job.id, () => makeDocs(job.id))
    if (out.error) setError(out.error)
    setStale(out.stale)
  }

  return (
    <>
      <button type="button" className="add" disabled={busyId !== null} onClick={() => void go()}>
        Make docs
      </button>
      {mine && (
        <p className="help" role="status">Writing documents… this can take a minute.</p>
      )}
      {stale && !error && <p className="help">{STALE_NOTE}</p>}
      {shown && <div className="result bad">{shown}</div>}
    </>
  )
}
