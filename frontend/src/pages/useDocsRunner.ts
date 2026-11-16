import { useState } from 'react'
import { errorText } from './jobFormat.ts'
import type { DocsRunner } from './docsTypes.ts'

// Runs a document action for one job at a time, then refreshes what is on screen.
// `reload` should throw if it cannot refresh: the action itself still worked, so that is reported as "stale".
export function useDocsRunner(reload: () => Promise<void>): { busyId: number | null; runDocs: DocsRunner } {
  const [busyId, setBusyId] = useState<number | null>(null)

  const runDocs: DocsRunner = async (jobId, action) => {
    setBusyId(jobId)
    try {
      try {
        await action()
      } catch (e) {
        return { error: errorText(e), stale: false }
      }
      try {
        await reload()
      } catch {
        return { error: null, stale: true }
      }
      return { error: null, stale: false }
    } finally {
      setBusyId(null)
    }
  }

  return { busyId, runDocs }
}
