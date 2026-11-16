import { describe, expect, it } from 'vitest'
import { inboundNoticeText, lastRunText, staleRunText } from './runLabels.ts'

describe('lastRunText', () => {
  it('says report and mentions the email for a run started by an emailed report', () => {
    expect(lastRunText('email', 'Nov 16, 8:00 AM')).toBe('Last report: Nov 16, 8:00 AM (from email)')
  })
  it('keeps the search wording for scheduled and manual runs', () => {
    expect(lastRunText('schedule', 'Nov 16, 8:00 AM')).toBe('Last search: Nov 16, 8:00 AM')
    expect(lastRunText('manual', 'Nov 16, 8:00 AM')).toBe('Last search: Nov 16, 8:00 AM')
  })
})

describe('staleRunText', () => {
  it('says no report has arrived today for an email run', () => {
    expect(staleRunText('email', 'Nov 15')).toBe(
      'No report has arrived today. The results below are from your last report on Nov 15.',
    )
  })
  it('keeps the search wording for other runs', () => {
    expect(staleRunText('schedule', 'Nov 15')).toBe(
      'No search has run today. The results below are from your last search on Nov 15.',
    )
    expect(staleRunText('manual', 'Nov 15')).toBe(
      'No search has run today. The results below are from your last search on Nov 15.',
    )
  })
})

describe('inboundNoticeText', () => {
  it('explains an email that did not start a run', () => {
    expect(inboundNoticeText('rejected', 'The sender is not the allowed sender.')).toBe(
      'The last emailed report was not accepted: The sender is not the allowed sender.',
    )
    expect(inboundNoticeText('skipped', null)).toBe('The last emailed report was not run: the daily limit was reached.')
    expect(inboundNoticeText('waiting', null)).toBe(
      'The last emailed report is waiting: another job was running. Run scripts/reprocess_email.py to start it.',
    )
    expect(inboundNoticeText('failed', 'The email could not be read.')).toBe(
      'The last emailed report failed: The email could not be read.',
    )
  })
  it('says nothing for emails that are fine', () => {
    for (const status of ['received', 'processing', 'started', 'done']) expect(inboundNoticeText(status, null)).toBeNull()
  })
})
