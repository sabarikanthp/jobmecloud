function pad(n: number): string {
  return String(n).padStart(2, '0')
}

// The LOCAL calendar date as YYYY-MM-DD. Never toISOString(), which is UTC and can be a day off.
export function localISO(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function todayISO(): string {
  return localISO(new Date())
}

export function tomorrowISO(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return localISO(d)
}

// The local calendar date `days` from today, by local date arithmetic.
export function daysFromTodayISO(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return localISO(d)
}

// A stored interview instant (ISO with Z) as the local value a datetime-local input expects.
export function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${localISO(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// A stored interview instant shown in the viewer's local time.
export function fmtInstant(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

// A logged instant as its LOCAL calendar date (formatted by `day`) plus local time, e.g. "12 Nov 2026, 9:05 pm".
export function fmtLogged(iso: string, day: (s: string) => string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${day(localISO(d))}, ${time}`
}
