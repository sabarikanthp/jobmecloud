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
  const [done, setDone] = useState(false)
  const mine = busyId === job.id
  const shown = error || job.docs_error || ''

  async function go() {
    setError('')
    setStale(false)
    setDone(false)
    const out = await runDocs(job.id, () => makeDocs(job.id))
    if (out.error) setError(out.error)
    else setDone(true)
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
      {done && !error && <p className="result ok" role="status">New resume and cover letter created.</p>}
      {stale && !error && <p className="help">{STALE_NOTE}</p>}
      {shown && <div className="result bad">{shown}</div>}
    </>
  )
}
