import type { TimelineEntry } from '../api.ts'

const FOLLOWUP: Record<string, string> = {
  followup_created: 'added',
  followup_done: 'done',
  followup_snoozed: 'snoozed',
  followup_rescheduled: 'rescheduled',
  followup_cancelled: 'cancelled',
}

// One plain sentence for an Activity Log entry.
export function describe(e: TimelineEntry): string {
  let text: string
  const verb = e.action.split('_')[1] ?? ''
  switch (e.action) {
    case 'status_changed':
      text =
        e.from_value && e.to_value
          ? `Status changed from ${e.from_value} to ${e.to_value}`
          : e.to_value
            ? `Status changed to ${e.to_value}`
            : 'Status changed'
      break
    case 'found':
      text = 'Found by JobMe'
      break
    case 'imported':
      text = 'Imported from a spreadsheet'
      break
    case 'added':
      text = 'Added by hand'
      break
    case 'docs_ready':
      text = 'Documents prepared'
      break
    case 'docs_regenerated':
      text = 'Documents regenerated'
      break
    case 'docs_as_is':
      text = 'Used your resume as-is'
      break
    case 'contact_added':
    case 'contact_updated':
    case 'contact_deleted':
      text = `Contact ${verb}`
      break
    case 'interview_added':
    case 'interview_updated':
    case 'interview_deleted':
      text = `Interview ${verb}`
      break
    case 'reopened':
      text = 'Reopened'
      break
    case 'field_changed': {
      const name = e.note ?? 'A detail'
      text = !e.to_value
        ? `${name} cleared`
        : e.from_value
          ? `${name} changed from ${e.from_value} to ${e.to_value}`
          : `${name} set to ${e.to_value}`
      break
    }
    case 'note':
      text = e.note || 'Note'
      break
    case 'edited':
      text = 'Edited'
      break
    default:
      text = FOLLOWUP[e.action]
        ? `Follow-up ${FOLLOWUP[e.action]}`
        : e.action.replace(/_/g, ' ')
  }
  if (e.actor === 'system') return `${text} (automatic)`
  if (e.actor.startsWith('claude:')) return `${text} (by Claude: ${e.actor.slice(7)})`
  return text
}

// Entries whose note is shown beside the sentence.
export function noteFor(e: TimelineEntry): string {
  // These entries already say their note in the sentence.
  if (e.action === 'field_changed' || e.action === 'note') return ''
  return e.note ?? ''
}
