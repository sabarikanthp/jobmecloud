// Addresses for the app's pages and jobs, kept in the part of the web address after the "#".
// A page is "#/jobs", a job is "#/jobs/123". Because a job has an address of its own, a link to it can open in
// a new tab (right click, Ctrl or Cmd + click, or middle click), and the back button works.

export const PAGES = ['Today', 'Jobs', 'Follow-ups', 'Dashboard', 'Settings'] as const
export type Page = (typeof PAGES)[number]

export interface Route {
  page: Page
  jobId: number | null
}

const SLUG: Record<Page, string> = {
  Today: 'today',
  Jobs: 'jobs',
  'Follow-ups': 'follow-ups',
  Dashboard: 'dashboard',
  Settings: 'settings',
}

const BY_SLUG = new Map<string, Page>(PAGES.map((p) => [SLUG[p], p]))

// Anything unreadable falls back to a safe page: an unknown page is Today, a bad job id is the jobs list.
export function parseRoute(hash: string): Route {
  const [slug = '', id = ''] = hash.replace(/^#\/?/, '').toLowerCase().split('/')
  const page = BY_SLUG.get(slug) ?? 'Today'
  const jobId = page === 'Jobs' && /^[1-9]\d*$/.test(id) ? Number(id) : null
  return { page, jobId }
}

export function routeHash(page: Page, jobId: number | null = null): string {
  return page === 'Jobs' && jobId !== null ? `#/${SLUG.Jobs}/${jobId}` : `#/${SLUG[page]}`
}

export const jobHref = (id: number): string => routeHash('Jobs', id)
