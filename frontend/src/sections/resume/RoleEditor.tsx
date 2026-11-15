import type { RoleRow } from './form.ts'

interface Props {
  role: RoleRow
  index: number
  count: number
  onChange: (r: RoleRow) => void
  onMove: (delta: number) => void
  onRemove: () => void
}

export default function RoleEditor({ role, index, count, onChange, onMove, onRemove }: Props) {
  const set = (k: keyof RoleRow) => (e: { target: { value: string } }) => onChange({ ...role, [k]: e.target.value })
  return (
    <div className="card">
      <label>
        Employer
        <input value={role.employer} onChange={set('employer')} />
        <span className="help">The company you worked for.</span>
      </label>
      <label>
        Job title
        <input value={role.title} onChange={set('title')} />
        <span className="help">What you were called there.</span>
      </label>
      <label>
        Start
        <input value={role.start} onChange={set('start')} />
        <span className="help">For example 2021-03, or Present</span>
      </label>
      <label>
        End
        <input value={role.end} onChange={set('end')} />
        <span className="help">For example 2021-03, or Present</span>
      </label>
      <label>
        Location
        <input value={role.location} onChange={set('location')} />
        <span className="help">City or area, or Remote.</span>
      </label>
      <label>
        Achievements (one per line)
        <textarea rows={5} value={role.bullets} onChange={set('bullets')} />
        <span className="help">What you did and what came of it. Real numbers help.</span>
      </label>
      <div className="row">
        <button disabled={index === 0} onClick={() => onMove(-1)}>
          Move up
        </button>
        <button disabled={index === count - 1} onClick={() => onMove(1)}>
          Move down
        </button>
        <button className="danger" onClick={onRemove}>Remove</button>
      </div>
    </div>
  )
}
