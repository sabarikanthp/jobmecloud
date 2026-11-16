// What the Today screen says about the most recent run. A run started by an emailed report is a "report",
// not a "search", because no search happened.

export function lastRunText(trigger: string, dayText: string): string {
  return trigger === 'email' ? `Last report: ${dayText} (from email)` : `Last search: ${dayText}`
}

export function staleRunText(trigger: string, dayText: string): string {
  return trigger === 'email'
    ? `No report has arrived today. The results below are from your last report on ${dayText}.`
    : `No search has run today. The results below are from your last search on ${dayText}.`
}
