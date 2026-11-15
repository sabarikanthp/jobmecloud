import { useState } from 'react'
import type { JobField } from '../api.ts'
import { BUILTIN_COLUMNS, type BuiltinColumn, type ColumnChoice } from '../pages/jobColumns.ts'

function toggle<T>(list: T[], id: T, on: boolean): T[] {
  return on ? [...list.filter((x) => x !== id), id] : list.filter((x) => x !== id)
}

/** Choose which custom fields show as columns, and which choice fields also get a filter. */
export default function ColumnsPicker({
  fields,
  choice,
  onChange,
}: {
  fields: JobField[]
  choice: ColumnChoice
  onChange: (c: ColumnChoice) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="columns-picker">
      <button aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Columns
      </button>
      {open && (
        <div className="card" role="group" aria-label="Columns">
          {BUILTIN_COLUMNS.map((b) => (
            <div key={b.key} className="row">
              <label className="check">
                <input
                  type="checkbox"
                  checked={choice.builtin.includes(b.key)}
                  onChange={(e) =>
                    onChange({ ...choice, builtin: toggle<BuiltinColumn>(choice.builtin, b.key, e.target.checked) })
                  }
                />
                {b.label}
              </label>
            </div>
          ))}
          {fields.length > 0 && <h4>Your fields</h4>}
          {fields.map((f) => (
            <div key={f.id} className="row">
              <label className="check">
                <input
                  type="checkbox"
                  checked={choice.columns.includes(f.id)}
                  onChange={(e) => onChange({ ...choice, columns: toggle(choice.columns, f.id, e.target.checked) })}
                />
                {f.name}
              </label>
              {f.type === 'choice' && (
                <label className="check">
                  <input
                    type="checkbox"
                    checked={choice.filters.includes(f.id)}
                    onChange={(e) => onChange({ ...choice, filters: toggle(choice.filters, f.id, e.target.checked) })}
                  />
                  Filter by {f.name}
                </label>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
