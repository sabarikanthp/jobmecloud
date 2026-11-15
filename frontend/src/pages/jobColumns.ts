// Which custom fields the Jobs table shows as columns and as filters, remembered in the browser.
export type BuiltinColumn = 'pay' | 'location' | 'work_mode' | 'link' | 'requisition'

/** The Jobs fields JobMe already has that can be shown as extra columns. */
export const BUILTIN_COLUMNS: { key: BuiltinColumn; label: string }[] = [
  { key: 'pay', label: 'Pay' },
  { key: 'location', label: 'Location' },
  { key: 'work_mode', label: 'Work mode' },
  { key: 'link', label: 'Link' },
  { key: 'requisition', label: 'Requisition' },
]

const DEFAULT_BUILTIN: BuiltinColumn[] = ['pay', 'location']

export interface ColumnChoice {
  columns: number[]
  filters: number[]
  builtin: BuiltinColumn[]
}

const KEY = 'jobmecloud.jobs.columns'

function ids(v: unknown): number[] {
  if (!Array.isArray(v)) return []
  return v.filter((x): x is number => typeof x === 'number' && Number.isInteger(x) && x > 0)
}

export function loadColumns(): ColumnChoice {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const p: unknown = JSON.parse(raw)
      if (p !== null && typeof p === 'object' && !Array.isArray(p)) {
        const o = p as Record<string, unknown>
        const known = BUILTIN_COLUMNS.map((b) => b.key)
        const builtin = Array.isArray(o.builtin)
          ? known.filter((k) => (o.builtin as unknown[]).includes(k))
          : DEFAULT_BUILTIN
        return { columns: ids(o.columns), filters: ids(o.filters), builtin }
      }
    }
  } catch {
    /* storage blocked or bad data */
  }
  return { columns: [], filters: [], builtin: DEFAULT_BUILTIN }
}

export function saveColumns(c: ColumnChoice) {
  try {
    localStorage.setItem(KEY, JSON.stringify(c))
  } catch {
    /* storage blocked */
  }
}
