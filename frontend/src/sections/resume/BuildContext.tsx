import { useEffect, useState } from 'react'
import { buildContext, getContextStatus } from '../../api.ts'

// Writes a short profile of each resume (new or changed ones only), so that JobMeCloud can pick the resume closest
// to a job automatically when it makes documents. One small AI call per resume, usually a cent or two.
export default function BuildContext({ resumeCount }: { resumeCount: number }) {
  const [pending, setPending] = useState<number | null>(null)
  const [total, setTotal] = useState(0)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function refresh() {
    try {
      const s = await getContextStatus()
      setPending(s.pending)
      setTotal(s.resumes.length)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    }
  }

  useEffect(() => {
    void refresh()
  }, [resumeCount])

  async function build() {
    setBusy(true)
    setError('')
    setMessage('')
    let built = 0
    try {
      for (;;) {
        const res = await buildContext()
        built += res.built
        setPending(res.pending)
        setMessage(`Built ${built}${res.pending > 0 ? `, ${res.pending} to go…` : '.'}`)
        if (res.errors.length > 0) {
          setError(res.errors.join(' '))
          break
        }
        if (res.pending === 0 || res.built === 0) break
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
      await refresh()
    }
  }

  if (pending === null && !error) return null
  const upToDate = pending === 0 && total > 0
  return (
    <div className="build-context">
      <div className="row">
        <button type="button" disabled={busy || upToDate} onClick={() => void build()}>
          Build context
        </button>
        <span className="help">
          {upToDate
            ? 'Every resume has a profile. Documents start from the closest one automatically.'
            : pending
              ? `${pending} of ${total} resumes need a profile, so JobMeCloud can pick the closest resume for each job.`
              : ''}
        </span>
      </div>
      {message && (
        <p className="help" role="status">
          {message}
        </p>
      )}
      {error && <div className="result bad">{error}</div>}
    </div>
  )
}
