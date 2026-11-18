// Every status has its own colour, so a list can be scanned at a glance. The colours are in styles.css.
export const STATUS_ORDER = [
  'New',
  'Ready',
  'Applied',
  'Interviewing',
  'Offer',
  'Accepted',
  'Rejected',
  'Withdrawn',
  'Skipped',
  'Closed',
  'Unavailable',
  'Duplicate',
] as const

export default function StatusBadge({ status }: { status: string }) {
  const known = (STATUS_ORDER as readonly string[]).includes(status)
  return <span className={`status-badge status-${known ? status.toLowerCase() : 'other'}`}>{status}</span>
}
