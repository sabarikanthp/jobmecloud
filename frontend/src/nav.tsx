import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { PAGES, parseRoute, routeHash, type Page, type Route } from './route.ts'

export { PAGES }
export type { Page }

interface Nav {
  page: Page
  jobId: number | null
  go: (page: Page) => void
  openJob: (id: number) => void
}

const NavContext = createContext<Nav | null>(null)

const here = (): Route => parseRoute(window.location.hash)

// The web address (the part after the "#") is the source of truth, so a job can be opened in a new tab, the back
// button works, and a bookmark lands where it was made. Going somewhere changes the address; the address changing
// (by a link, a new tab or the back button) changes what is shown.
export function NavProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(here)

  useEffect(() => {
    const onChange = () => setRoute(here())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  const value = useMemo<Nav>(
    () => ({
      page: route.page,
      jobId: route.jobId,
      go: (p) => {
        window.location.hash = routeHash(p)
        setRoute({ page: p, jobId: null })
      },
      openJob: (id) => {
        window.location.hash = routeHash('Jobs', id)
        setRoute({ page: 'Jobs', jobId: id })
      },
    }),
    [route],
  )

  return <NavContext.Provider value={value}>{children}</NavContext.Provider>
}

export function useNav(): Nav {
  const nav = useContext(NavContext)
  if (!nav) throw new Error('useNav must be used inside NavProvider')
  return nav
}
