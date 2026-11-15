import type { DayKey, SearchProfile, WorkMode } from '../../api.ts'
import { lines } from '../resume/form.ts'

export const DAYS: { key: DayKey; label: string }[] = [
  { key: 'mon', label: 'Monday' },
  { key: 'tue', label: 'Tuesday' },
  { key: 'wed', label: 'Wednesday' },
  { key: 'thu', label: 'Thursday' },
  { key: 'fri', label: 'Friday' },
  { key: 'sat', label: 'Saturday' },
  { key: 'sun', label: 'Sunday' },
]

export const MODES: { key: WorkMode; label: string }[] = [
  { key: 'remote', label: 'Remote' },
  { key: 'hybrid', label: 'Hybrid' },
  { key: 'onsite', label: 'On-site' },
]

// Lists are edited as text (one per line) and numbers as text so a half-typed value is not lost.
export interface SearchForm {
  roles: string
  positioning: string
  locations: string
  radius: string
  modes: WorkMode[]
  pay: string
  dealBreakers: string
  warnings: string
  excluded: string
  doNotClaim: string
  commute: string
  postedDays: string
  rotation: Record<DayKey, string>
}

const num = (n: number | null) => (n === null ? '' : String(n))

export function toForm(p: SearchProfile): SearchForm {
  return {
    roles: p.target_roles.join('\n'),
    positioning: p.positioning,
    locations: p.locations.join('\n'),
    radius: num(p.radius_miles),
    modes: [...p.work_modes],
    pay: num(p.min_base_pay),
    dealBreakers: p.deal_breakers.join('\n'),
    warnings: p.warnings.join('\n'),
    excluded: p.excluded_employers.join('\n'),
    doNotClaim: p.do_not_claim.join('\n'),
    commute: num(p.max_commute_miles),
    postedDays: num(p.max_posted_days),
    rotation: Object.fromEntries(DAYS.map((d) => [d.key, p.rotation[d.key] ?? ''])) as Record<DayKey, string>,
  }
}

// An imported draft replaces everything except the weekly search areas, which it never has.
export const applyDraft = (draft: SearchProfile, current: SearchForm): SearchForm => ({
  ...toForm(draft),
  rotation: current.rotation,
})

export function parseNumber(text: string): number | null {
  const t = text.trim()
  if (!t) return null
  if (!/^\d+$/.test(t)) throw new Error('Please enter a whole number of 0 or more.')
  return Number(t)
}

// Throws a plain-language Error when a number field is not valid.
export function fromForm(f: SearchForm): SearchProfile {
  const rotation: SearchProfile['rotation'] = {}
  for (const d of DAYS) if (f.rotation[d.key].trim()) rotation[d.key] = f.rotation[d.key].trim()
  return {
    target_roles: lines(f.roles),
    positioning: f.positioning.trim(),
    locations: lines(f.locations),
    radius_miles: parseNumber(f.radius),
    work_modes: f.modes,
    min_base_pay: parseNumber(f.pay),
    excluded_employers: lines(f.excluded),
    deal_breakers: lines(f.dealBreakers),
    warnings: lines(f.warnings),
    max_commute_miles: parseNumber(f.commute),
    max_posted_days: parseNumber(f.postedDays),
    do_not_claim: lines(f.doNotClaim),
    rotation,
  }
}

export const summaryOf = (p: SearchProfile | null) =>
  p && p.target_roles.length ? p.target_roles.slice(0, 3).join(', ') : 'Not filled in yet'
