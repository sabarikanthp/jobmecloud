import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

export const PAGES = ['Today', 'Jobs', 'Follow-ups', 'Dashboard', 'Settings'] as const
export type Page = (typeof PAGES)[number]

interface Nav {
  page: Page
  jobId: number | null
  go: (page: Page) => void
  openJob: (id: number) => void
}

const NavContext = createContext<Nav | null>(null)

export function NavProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<Page>('Today')
  const [jobId, setJobId] = useState<number | null>(null)

  const value = useMemo<Nav>(
    () => ({
      page,
      jobId,
      go: (p) => {
        setPage(p)
        setJobId(null)
      },
      openJob: (id) => {
        setPage('Jobs')
        setJobId(id)
      },
    }),
    [page, jobId],
  )

  return <NavContext.Provider value={value}>{children}</NavContext.Provider>
}

export function useNav(): Nav {
  const nav = useContext(NavContext)
  if (!nav) throw new Error('useNav must be used inside NavProvider')
  return nav
}
