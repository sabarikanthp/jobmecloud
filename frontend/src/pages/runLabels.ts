// What the Today screen says about the most recent run. A run started by an emailed report is a "report",
// not a "search", because no search happened.

export function lastRunText(trigger: string, dayText: string): string {
  return trigger === 'email' ? `Last report: ${dayText} (from email)` : `Last search: ${dayText}`
}

// A line for the most recent emailed report when it did NOT start a run, so the person is not left guessing why
// no report shows up. Emails that are fine (received, processing, started, done) say nothing.
export function inboundNoticeText(status: string, note: string | null): string | null {
  switch (status) {
    case 'rejected':
      return `The last emailed report was not accepted${note ? `: ${note}` : '.'}`
    case 'skipped':
      return 'The last emailed report was not run: the daily limit was reached.'
    case 'waiting':
      return 'The last emailed report is waiting: another job was running. Run scripts/reprocess_email.py to start it.'
    case 'failed':
      return `The last emailed report failed${note ? `: ${note}` : '.'}`
    default:
      return null
  }
}

export function staleRunText(trigger: string, dayText: string): string {
  return trigger === 'email'
    ? `No report has arrived today. The results below are from your last report on ${dayText}.`
    : `No search has run today. The results below are from your last search on ${dayText}.`
}
