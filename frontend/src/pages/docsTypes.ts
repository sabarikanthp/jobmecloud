// Result of a docs request for one job.
// error: the server's message when the action failed. stale: the action worked but the page could not refresh.
export interface DocsOutcome {
  error: string | null
  stale: boolean
}

export type DocsRunner = (jobId: number, action: () => Promise<unknown>) => Promise<DocsOutcome>

export const STALE_NOTE = 'Your documents were made. Reload the page to see them.'
