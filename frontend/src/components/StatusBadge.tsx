const ROLE: Record<string, string> = {
  Applied: 'blue',
  Interviewing: 'blue',
  Offer: 'blue',
  Accepted: 'green',
  Skipped: 'grey',
  Withdrawn: 'grey',
  Closed: 'grey',
  Rejected: 'red',
}

export default function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge ${ROLE[status] ?? 'neutral'}`}>{status}</span>
}
