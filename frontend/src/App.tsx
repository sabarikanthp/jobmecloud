import { useEffect, useState } from 'react'
import { getSetup } from './api.ts'
import { followUpBadge, useFollowUpCounts } from './followUps.ts'
import { authEnabled, logout } from './auth.ts'
import { NavProvider, PAGES, useNav } from './nav.tsx'
import Connect from './pages/Connect.tsx'
import Dashboard from './pages/Dashboard.tsx'
import FollowUps from './pages/FollowUps.tsx'
import Jobs from './pages/Jobs.tsx'
import Placeholder from './pages/Placeholder.tsx'
import Settings from './pages/Settings.tsx'
import Today from './pages/Today.tsx'
import Wizard from './setup/Wizard.tsx'

export default function App() {
  // A connector (ChatGPT, Claude) asking for access lands here after the normal sign-in.
  if (window.location.hash.startsWith('#/connect')) return <Connect />
  return (
    <NavProvider>
      <Shell />
    </NavProvider>
  )
}

function Shell() {
  const { page, go } = useNav()
  const [finished, setFinished] = useState<boolean | null>(null)
  const [error, setError] = useState('')
  const badge = followUpBadge(useFollowUpCounts())

  useEffect(() => {
    getSetup()
      .then((s) => setFinished(s.finished))
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <div className="result bad">{error}</div>
  if (finished === null) return <p className="loading">Loading…</p>
  if (!finished) return <Wizard onFinished={() => setFinished(true)} />

  return (
    <div className="shell">
      <nav className="nav" aria-label="Main">
        <div className="brand">JobMeCloud</div>
        {PAGES.map((p) => (
          <button
            key={p}
            className={p === page ? 'nav-item active' : 'nav-item'}
            aria-current={p === page ? 'page' : undefined}
            onClick={() => go(p)}
          >
            {p}
            {p === 'Follow-ups' && badge && (
              <span className={badge.overdue ? 'nav-count overdue' : 'nav-count'} role="img" aria-label={badge.label}>
                {badge.text}
              </span>
            )}
          </button>
        ))}
        {authEnabled() && (
          <button className="nav-item" onClick={logout}>
            Sign out
          </button>
        )}
      </nav>
      <main className="content">
        {page === 'Settings' ? (
          <Settings />
        ) : page === 'Today' ? (
          <Today />
        ) : page === 'Jobs' ? (
          <Jobs />
        ) : page === 'Follow-ups' ? (
          <FollowUps />
        ) : page === 'Dashboard' ? (
          <Dashboard />
        ) : (
          <Placeholder title={page} />
        )}
      </main>
    </div>
  )
}
