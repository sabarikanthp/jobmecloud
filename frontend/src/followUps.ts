import { useEffect, useState } from 'react'
import { CHANGED_EVENT, getFollowUpCounts, type FollowUpCounts } from './api.ts'

export interface Badge {
  text: string
  label: string
  overdue: boolean
}

/** What the Follow-ups menu item should show: nothing at zero or while unknown. */
export function followUpBadge(counts: FollowUpCounts | null): Badge | null {
  if (!counts) return null
  const total = counts.overdue + counts.due_today
  if (total <= 0) return null
  const label = `Follow-ups, ${total} due` + (counts.overdue > 0 ? ` (${counts.overdue} overdue)` : '')
  return { text: total > 99 ? '99+' : String(total), label, overdue: counts.overdue > 0 }
}

const REFRESH_MS = 5 * 60_000
const SETTLE_MS = 400

/** The overdue and due-today counts, kept fresh without the person having to reload. */
export function useFollowUpCounts(): FollowUpCounts | null {
  const [counts, setCounts] = useState<FollowUpCounts | null>(null)

  useEffect(() => {
    let alive = true
    let settle: ReturnType<typeof setTimeout> | undefined
    const refresh = () => {
      getFollowUpCounts()
        .then((c) => alive && setCounts(c))
        .catch(() => {
          /* keep the last count */
        })
    }
    const afterChange = () => {
      clearTimeout(settle)
      settle = setTimeout(refresh, SETTLE_MS)
    }
    refresh()
    const timer = setInterval(refresh, REFRESH_MS)
    window.addEventListener('focus', refresh)
    window.addEventListener('hashchange', refresh)
    window.addEventListener(CHANGED_EVENT, afterChange)
    return () => {
      alive = false
      clearTimeout(settle)
      clearInterval(timer)
      window.removeEventListener('focus', refresh)
      window.removeEventListener('hashchange', refresh)
      window.removeEventListener(CHANGED_EVENT, afterChange)
    }
  }, [])

  return counts
}
