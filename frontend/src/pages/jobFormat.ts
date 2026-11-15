export function formatPay(min: number | null, max: number | null): string {
  const f = (n: number) => `$${n.toLocaleString('en-US')}`
  if (min != null && max != null) return `${f(min)}–${f(max)}`
  if (max != null) return `Up to ${f(max)}`
  if (min != null) return `From ${f(min)}`
  return 'Pay not posted'
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : 'Something went wrong.'
}

// "86% match", or nothing when the job has no score (never a bare "% match").
export function matchText(score: number | null): string | null {
  return score == null ? null : `${score}% match`
}

// Docs can be made while the job is still waiting to be applied for.
export function canMakeDocs(status: string): boolean {
  return status === 'New' || status === 'Ready'
}
